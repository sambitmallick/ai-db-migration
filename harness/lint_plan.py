#!/usr/bin/env python3
"""lint_plan.py <plan.json> -- the no-AI check: Squawk (an open-source Postgres migration linter) on every SQL step.
Squawk only sees the SQL: not the traffic, not the app. Its findings are grouped:
  lock risk       the statement takes a lock that blocks traffic for as long as it runs
  may break app   renames and drops: fine if the app was moved off first, which Squawk can't know
  hygiene         timeouts, re-runnable statements, style
Prints each finding and a one-line verdict."""
import json, os, subprocess, sys, tempfile
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NODE = r"C:\Users\sambi\node24\node-v24.19.0-win-x64"
LOCK = {"require-concurrent-index-creation", "require-concurrent-index-deletion", "changing-column-type",
        "adding-foreign-key-constraint", "constraint-missing-not-valid", "adding-not-nullable-field", "adding-required-field",
        "disallowed-unique-constraint", "adding-serial-primary-key-field", "adding-field-with-default", "ban-alter-domain-with-add-constraint"}
BREAK = {"renaming-column", "renaming-table", "ban-drop-column", "ban-drop-table", "ban-drop-constraint", "ban-drop-function",
         "ban-drop-database", "ban-drop-not-null", "ban-truncate-cascade"}


def lint(plan_path):
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    sql = "\n".join(s["sql"].rstrip().rstrip(";") + ";" for s in plan["steps"] if "sql" in s)
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "migration.sql"
        f.write_text(sql + "\n", encoding="utf-8")
        env = dict(os.environ, PATH=NODE + os.pathsep + os.environ["PATH"])
        r = subprocess.run([os.path.join(NODE, "npx.cmd"), "--yes", "squawk-cli@2.70.0", "--reporter", "gcc", "migration.sql"],
                           capture_output=True, text=True, encoding="utf-8", env=env, cwd=d)
    found = []
    for l in (r.stdout + r.stderr).splitlines():
        if ": warning: " in l:
            rule, msg = l.split(": warning: ", 1)[1].split(" ", 1)
            kind = "lock risk" if rule in LOCK else "may break app" if rule in BREAK else "hygiene"
            found.append({"rule": rule, "kind": kind, "message": msg})
    return found


if __name__ == "__main__":
    found = lint(sys.argv[1])
    for k in ("lock risk", "may break app", "hygiene"):
        for x in found:
            if x["kind"] == k:
                print(f"  {k:13}  {x['rule']}: {x['message'][:110]}")
    by = {k: sorted({x["rule"] for x in found if x["kind"] == k}) for k in ("lock risk", "may break app", "hygiene")}
    print(f"SQUAWK lock risk: {', '.join(by['lock risk']) or 'none'} | may break app: {', '.join(by['may break app']) or 'none'} | hygiene: {len([x for x in found if x['kind'] == 'hygiene'])}")
