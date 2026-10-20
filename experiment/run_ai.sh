#!/bin/bash
# run_ai.sh <mode> <runs> [task...]: for each task, <runs> times: Claude Code writes a plan (/migrate), Squawk lints it,
# then the harness runs it against the live shop under traffic. Label: <mode>-<task>-<n>.
cd "$(dirname "$0")/.."
MODE="$1"; N="$2"; shift 2
TASKS="${*:-add-index rename-amount customer-bigint email-not-null customer-fk}"
for t in $TASKS; do
  for n in $(seq 1 "$N"); do
    id="$MODE-$t-$n"
    python harness/run_plan.py --prepare      # the agent inspects exactly the state its plan will run against
    python experiment/make_plan.py "$t" "$MODE" "$id"
    if [ ! -f "plans/$id.json" ]; then   # writing no plan is an answer too ("don't do this"): run it as an empty plan
      echo "{\"task\": \"$t\", \"steps\": [], \"note\": \"the agent wrote no plan\"}" > "plans/$id.json"
    fi
    if [ -f "plans/$id.json" ]; then
      python harness/lint_plan.py "plans/$id.json" | tail -1 | tee "experiment/runs/$id/squawk.txt"
      python harness/run_plan.py "$t" "plans/$id.json" "$id" 2>&1 | grep RESULT
    else
      echo "$id: no plan written"
    fi
  done
done
