#!/usr/bin/env python3
"""
run_plan.py -- run ONE migration plan against the live shop, under traffic, and measure what it did.

  python harness/run_plan.py <task> <plan.json> <label>

1. reset   : re-seed the database (10M orders), put the app back to its original schema view, snapshot every order
2. traffic : start the in-cluster load generator (60 req/s) and a lock sampler inside the Postgres pod
3. baseline: 20 s of normal traffic
4. migrate : run the plan's steps in order, timing each one. A step that fails stops the plan.
              {"sql": "..."}                      psql, autocommit, ON_ERROR_STOP
              {"deploy": {"AMOUNT_READ": "..."}}   roll out the app with new settings (kubectl set env + rollout)
              {"wait": seconds}
5. after   : 30 s more traffic on the migrated system, then collect every request
6. verify  : tasks/<task>/verify.sql (schema is right, no order lost, no value changed, every write kept)

Writes results/<label>/: requests.jsonl, steps.json, locks.txt, verify.txt, summary.json.
"""
import json, os, statistics, subprocess, sys, tempfile, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PSQL = ["kubectl", "exec", "-i", "deploy/postgres", "--", "psql", "-U", "postgres", "-d", "shop", "-X", "-q", "-v", "ON_ERROR_STOP=1"]
APP_DEFAULTS = {"AMOUNT_READ": "amount", "AMOUNT_WRITE": "amount", "GUEST_EMAIL": "null"}
BASELINE, AFTER, STEP_TIMEOUT = 20, 30, 600
BASH = r"C:\Program Files\Git\bin\bash.exe"   # not the WSL launcher that "bash" can resolve to on Windows


def sh(cmd, inp=None, timeout=600, check=True):
    r = subprocess.run(cmd, input=inp, capture_output=True, text=True, encoding="utf-8", timeout=timeout, cwd=ROOT)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:6])}... failed: {(r.stderr or r.stdout)[-600:]}")
    return r


def psql(sql, timeout=600, check=True):
    return sh(PSQL + ["-At"], inp=sql, timeout=timeout, check=check)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def prepare():
    """The state a planner should see: freshly seeded, the app on its original settings, no harness tables."""
    sh([BASH, "scripts/seed.sh"], timeout=900)
    sh(["kubectl", "set", "env", "deployment/shop"] + [f"{k}={v}" for k, v in APP_DEFAULTS.items()])
    sh(["kubectl", "rollout", "status", "deployment/shop", "--timeout=180s"])


def reset():
    log("reset: re-seed 10,000,000 orders, app back to its original schema view")
    sh([BASH, "scripts/seed.sh"], timeout=900)
    sh(["kubectl", "set", "env", "deployment/shop"] + [f"{k}={v}" for k, v in APP_DEFAULTS.items()])
    sh(["kubectl", "rollout", "status", "deployment/shop", "--timeout=180s"])
    psql("CREATE SCHEMA audit; CREATE TABLE audit.snap AS SELECT id, customer_id, amount, email FROM public.orders;"
         "ALTER TABLE audit.snap ADD PRIMARY KEY (id);")


def cluster_offset_ms():
    """cluster clock minus host clock, from the Postgres pod (the load generator runs on the same node)."""
    best = None
    for _ in range(3):
        t0 = time.time() * 1000
        out = psql("SELECT (extract(epoch FROM clock_timestamp()) * 1000)::bigint;").stdout.strip()   # busybox date has no ms
        t1 = time.time() * 1000
        if best is None or (t1 - t0) < best[0]:
            best = (t1 - t0, int(out) - (t0 + t1) / 2)
    return best[1]


def start_locks(seconds):
    # every 0.25 s: how many sessions are waiting on a lock, and the longest wait so far
    loop = (f"end=$(( $(date +%s) + {seconds} )); while [ $(date +%s) -lt $end ]; do "
            "psql -U postgres -d shop -At -c \"SELECT (extract(epoch from now())*1000)::bigint, "
            "count(*) FILTER (WHERE wait_event_type = 'Lock'), "
            "coalesce(round(max(extract(epoch from now() - query_start)) FILTER (WHERE wait_event_type = 'Lock'), 2), 0) "
            "FROM pg_stat_activity WHERE datname = 'shop'\" >> /tmp/locks.txt; sleep 0.25; done")
    sh(["kubectl", "exec", "deploy/postgres", "--", "rm", "-f", "/tmp/locks.txt"])
    return subprocess.Popen(["kubectl", "exec", "deploy/postgres", "--", "sh", "-c", loop],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=ROOT)


def run_step(step):
    t0 = time.time()
    try:
        if "sql" in step:
            r = psql(step["sql"], timeout=STEP_TIMEOUT, check=False)
            ok, out = r.returncode == 0, (r.stdout + r.stderr).strip()
        elif "deploy" in step:
            sh(["kubectl", "set", "env", "deployment/shop"] + [f"{k}={v}" for k, v in step["deploy"].items()])
            r = sh(["kubectl", "rollout", "status", "deployment/shop", "--timeout=300s"], check=False)
            ok, out = r.returncode == 0, (r.stdout + r.stderr).strip()[-300:]
        elif "wait" in step:
            time.sleep(float(step["wait"])); ok, out = True, ""
        else:
            ok, out = False, "unknown step type"
    except subprocess.TimeoutExpired:
        ok, out = False, f"step timed out after {STEP_TIMEOUT}s"
    return {"note": step.get("note", ""), "kind": next((k for k in ("sql", "deploy", "wait") if k in step), "?"),
            "start": t0, "end": time.time(), "ok": ok, "output": out[-1500:]}


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))] if xs else 0


def single_run_lock():
    """Only one harness at a time: two would reseed and re-point each other's traffic."""
    lock = ROOT / "results" / ".lock"
    lock.parent.mkdir(exist_ok=True)
    if lock.exists():
        pid = int(lock.read_text() or 0)
        alive = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
        if str(pid) in alive:
            raise SystemExit(f"another harness (pid {pid}) is running")
    lock.write_text(str(os.getpid()))
    return lock


def main(task, plan_path, label):
    lock = single_run_lock()
    out = ROOT / "results" / label
    out.mkdir(parents=True, exist_ok=True)
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    steps = plan["steps"] if isinstance(plan, dict) else plan
    reset()
    offset = cluster_offset_ms()

    log("traffic: load generator (60 req/s) + lock sampler")
    # the previous run's load generator must be GONE first, or "wait for ready" finds the old pod
    sh(["kubectl", "delete", "job", "loadgen", "--ignore-not-found", "--cascade=foreground", "--wait=true"], timeout=180)
    for _ in range(60):
        if not sh(["kubectl", "get", "pods", "-l", "job-name=loadgen", "-o", "name"]).stdout.strip():
            break
        time.sleep(2)
    lg = (ROOT / "k8s" / "loadgen.yaml").read_text(encoding="utf-8").replace('value: "150"', 'value: "1500"')
    sh(["kubectl", "apply", "-f", "-"], inp=lg)
    for _ in range(60):                  # traffic has really started: the new pod has logged its first request
        if '{"at"' in sh(["kubectl", "logs", "job/loadgen", "--tail=5"], check=False).stdout:
            break
        time.sleep(2)
    else:
        raise RuntimeError("the load generator never started")
    locks = start_locks(1500)
    time.sleep(BASELINE)

    log(f"migrate: {len(steps)} steps")
    done = []
    for i, st in enumerate(steps, 1):
        r = run_step(st)
        done.append(r)
        log(f"  step {i}/{len(steps)} {r['kind']:6} {r['end'] - r['start']:6.1f}s {'ok' if r['ok'] else 'FAILED'}  {r['note'][:70]}")
        if not r["ok"]:
            log("  " + r["output"].replace("\n", " | ")[:300])
            break
    if not done:                         # an empty plan: the agent chose to change nothing
        mig_start = mig_end = time.time()
    else:
        mig_start, mig_end = done[0]["start"], done[-1]["end"]
    completed = all(r["ok"] for r in done) and len(done) == len(steps)
    time.sleep(AFTER)

    log("collect: every request, the lock samples")
    raw = sh(["kubectl", "logs", "job/loadgen"], timeout=300).stdout
    sh(["kubectl", "delete", "job", "loadgen", "--wait=false"])
    locks.kill()
    (out / "requests.jsonl").write_text("\n".join(l for l in raw.splitlines() if l.startswith("{")) + "\n", encoding="utf-8")
    lk = sh(["kubectl", "exec", "deploy/postgres", "--", "cat", "/tmp/locks.txt"], check=False).stdout
    (out / "locks.txt").write_text(lk, encoding="utf-8")
    (out / "steps.json").write_text(json.dumps(done, indent=1), encoding="utf-8")
    reqs = [json.loads(l) for l in raw.splitlines() if l.startswith("{")]
    for r in reqs:                       # put every request on the host clock
        r["t"] = (r["at"] - offset) / 1000

    log("verify")
    written = [r for r in reqs if r["kind"] == "write" and r["status"] == 200 and r.get("id")]
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
        for r in written:
            f.write(f"{r['id']},{r['amount']},{r['customer']},{r['email'] or ''},{'t' if r['email'] is None else 'f'}\n")
    csv = Path(f.name).read_text(encoding="utf-8"); os.unlink(f.name)
    psql("CREATE TABLE audit.written (id bigint PRIMARY KEY, amount numeric(10,2), customer_id bigint, email text, guest boolean);"
         "COPY audit.written FROM STDIN WITH (FORMAT csv);\n" + csv + "\\.\n")
    v = psql((ROOT / "tasks" / task / "verify.sql").read_text(encoding="utf-8") + "\n"
             + (ROOT / "tasks" / "data_checks.sql").read_text(encoding="utf-8"), check=False)
    checks = [dict(zip(("check", "passed", "detail"), l.split("|", 2))) for l in v.stdout.splitlines() if l.count("|") >= 1]
    for c in checks:
        c["passed"] = c["passed"] == "t"
    if v.returncode != 0:
        checks.append({"check": "verify.sql ran", "passed": False, "detail": v.stderr.strip()[-300:]})
    app_env = sh(["kubectl", "get", "deployment/shop", "-o", "jsonpath={range .spec.template.spec.containers[0].env[*]}{.name}={.value} {end}"]).stdout.strip()
    want = ROOT / "tasks" / task / "app.json"
    if want.exists():
        env = dict(kv.split("=", 1) for kv in app_env.split())
        for k, val in json.loads(want.read_text(encoding="utf-8")).items():
            checks.append({"check": f"app runs with {k}={val}", "passed": env.get(k) == val, "detail": f"now {k}={env.get(k)}"})
    (out / "verify.txt").write_text("\n".join(f"{'PASS' if c['passed'] else 'FAIL'}  {c['check']}  {c.get('detail','')}" for c in checks) + f"\napp: {app_env}\n", encoding="utf-8")

    def window(a, b):
        w = [r for r in reqs if a <= r["t"] < b]
        bad = [r for r in w if r["status"] not in (200, 404)]
        return {"requests": len(w), "failed": len(bad), "failed_writes": sum(1 for r in bad if r["kind"] == "write"),
                "p50_ms": pct([r["ms"] for r in w], 0.5), "p99_ms": pct([r["ms"] for r in w], 0.99),
                "max_ms": max([r["ms"] for r in w], default=0)}
    t_first = min(r["t"] for r in reqs)
    lock_rows = [l.split("|") for l in lk.splitlines() if l.count("|") == 2]
    lock_rows = [((int(a) - offset) / 1000, int(b), float(c)) for a, b, c in lock_rows]
    in_mig = [x for x in lock_rows if mig_start <= x[0] <= mig_end + 5]
    def rate(w, secs):
        return w["requests"] / secs if secs > 0 else 0
    base_s, dur_s = mig_start - t_first, mig_end - mig_start
    traffic = {"baseline_rps": round(rate(window(t_first, mig_start), base_s), 1),
               "during_rps": round(rate(window(mig_start, mig_end), dur_s), 1) if dur_s >= 1 else None,
               "after_rps": round(rate(window(mig_end, mig_end + AFTER), AFTER), 1)}
    traffic_ok = all(v is None or v >= 40 for v in traffic.values())    # 60 req/s offered: below 40 the run measured nothing
    summary = {
        "task": task, "label": label, "plan": str(plan_path), "steps": len(steps), "steps_run": len(done), "completed": completed,
        "empty_plan": not steps,
        "failed_step": next(({"n": i + 1, "note": r["note"], "output": r["output"][-400:]} for i, r in enumerate(done) if not r["ok"]), None),
        "migration_seconds": round(mig_end - mig_start, 1),
        "baseline": window(t_first, mig_start), "during": window(mig_start, mig_end), "after": window(mig_end, mig_end + AFTER),
        "max_sessions_waiting_on_lock": max([x[1] for x in in_mig], default=0),
        "longest_lock_wait_s": max([x[2] for x in in_mig], default=0.0),
        "traffic": traffic, "traffic_ok": traffic_ok,
        "checks_passed": sum(c["passed"] for c in checks), "checks": len(checks),
        "failed_checks": [c["check"] for c in checks if not c["passed"]], "app_env": app_env,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    psql("DROP SCHEMA IF EXISTS audit CASCADE;", check=False)   # the snapshot is the harness's, not something an agent should find
    lock.unlink(missing_ok=True)
    d, a = summary["during"], summary["after"]
    log(f"RESULT {label}: plan {'completed' if completed else 'STOPPED at step ' + str(len(done))} in {summary['migration_seconds']}s | "
        f"during: {d['failed']}/{d['requests']} failed, p99 {d['p99_ms']} ms | after: {a['failed']}/{a['requests']} failed | "
        f"lock waiters max {summary['max_sessions_waiting_on_lock']}, longest wait {summary['longest_lock_wait_s']}s | "
        f"checks {summary['checks_passed']}/{summary['checks']} {summary['failed_checks']}"
        + ("" if traffic_ok else f" | INVALID: too little traffic {traffic}"))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--prepare"]:
        prepare(); log("prepared: fresh seed, original app settings, no audit tables")
    else:
        main(*sys.argv[1:4])
