#!/bin/bash
# task 6, where the request itself is wrong: the two controls, then 3 plain + 3 live AI runs
cd "$(dirname "$0")/.."
for k in naive safe; do python harness/run_plan.py drop-status controls/drop-status/$k.json control-drop-status-$k 2>&1 | grep RESULT
  python harness/lint_plan.py controls/drop-status/$k.json | tail -1 > results/control-drop-status-$k/squawk.txt; done
bash experiment/run_ai.sh plain 3 drop-status
bash experiment/run_ai.sh live 3 drop-status
