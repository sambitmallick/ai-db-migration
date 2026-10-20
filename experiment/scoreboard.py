#!/usr/bin/env python3
"""The scoreboard: every run in results/, per task and per who wrote the plan.
A run is a ZERO-DOWNTIME SUCCESS only if: the plan completed, no request failed during or after the migration,
and every check passed (schema right, no order lost, no value changed, every write kept, app settings right).
  python experiment/scoreboard.py [filter]
  RESULTS=archive-leaky/results python experiment/scoreboard.py    (the batch that could see the harness's tables)"""
import json, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
TASKS = ["add-index", "rename-amount", "customer-bigint", "email-not-null", "customer-fk", "drop-status"]
flt = sys.argv[1] if len(sys.argv) > 1 else ""


def who(label):
    # control-<task>-naive / control-<task>-safe / <mode>-<task>-<n>
    if label.startswith("harness-check-"):
        return "harness check " + label.rsplit("-", 1)[1]
    if label.startswith("control-"):
        return "control " + label.rsplit("-", 1)[1]
    return "AI " + label.split("-", 1)[0]


rows = []
import os
RESULTS = ROOT / os.environ.get("RESULTS", "results")
for f in sorted(RESULTS.glob("*/summary.json")):
    s = json.loads(f.read_text(encoding="utf-8"))
    if flt and flt not in s["label"]:
        continue
    if not s.get("traffic_ok", True):
        print(f"{s['label']}: INVALID (too little traffic: {s['traffic']}), not scored"); continue
    ok = s["completed"] and s["during"]["failed"] == 0 and s["after"]["failed"] == 0 and s["checks_passed"] == s["checks"]
    rows.append((s, ok))

def verdict(s, ok):
    if ok:
        return "ZERO-DOWNTIME"
    why = []
    if not s["completed"]:
        why.append(f"stopped at step {s['steps_run']}")
    if s["during"]["failed"]:
        why.append(f"{s['during']['failed']} failed during")
    if s["after"]["failed"]:
        why.append(f"{s['after']['failed']} failed after")
    why += s["failed_checks"]
    return "FAIL: " + "; ".join(why)


def squawk(label):
    for f in (ROOT / "experiment" / "runs" / label / "squawk.txt", RESULTS / label / "squawk.txt", RESULTS.parent / "runs" / label / "squawk.txt"):
        if f.exists():
            t = f.read_text(encoding="utf-8")
            return "flags lock" if "lock risk: none" not in t else "ok"
    return "-"


print(f"{'run':34} {'plan':9} {'secs':>6} {'failed during':>14} {'after':>7} {'p99':>6} {'lock wait':>9}  {'checks':6}  {'squawk':10}  verdict")
for t in TASKS:
    for s, ok in [r for r in rows if r[0]["task"] == t]:
        d, a = s["during"], s["after"]
        print(f"{s['label'][:34]:34} {('done' if s['completed'] else 'STOPPED'):9} {s['migration_seconds']:6.1f} "
              f"{d['failed']:>6}/{d['requests']:<7} {a['failed']:>7} {d['p99_ms']:>6} {s['longest_lock_wait_s']:>8.2f}s  "
              f"{s['checks_passed']}/{s['checks']:<4}  {squawk(s['label']):10}  {verdict(s, ok)}")
    print()

groups = {}
for s, ok in rows:
    g = groups.setdefault(who(s["label"]), [0, 0])
    g[0] += ok; g[1] += 1
print("zero-downtime successes:", " | ".join(f"{k}: {v[0]}/{v[1]}" for k, v in sorted(groups.items())))
