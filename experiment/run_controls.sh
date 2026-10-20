#!/bin/bash
# run_controls.sh: every hand-written control under live traffic: the dangerous plan and the safe plan per task.
cd "$(dirname "$0")/.."
for t in add-index rename-amount customer-bigint email-not-null customer-fk; do
  for k in naive safe; do python harness/run_plan.py $t controls/$t/$k.json control-$t-$k 2>&1 | grep RESULT; done
done
# the no-AI linter on every control plan
for t in add-index rename-amount customer-bigint email-not-null customer-fk; do
  for k in naive safe; do python harness/lint_plan.py controls/$t/$k.json | tail -1 > results/control-$t-$k/squawk.txt; done
done
