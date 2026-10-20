#!/bin/bash
# the plans from the conversations recorded on screen, run under live traffic, plus the dangerous bigint change
# wrapped in a DO block (Squawk sees nothing; does the database care?)
cd "$(dirname "$0")/.."
python harness/run_plan.py rename-amount plans/tui-rename.json session-rename 2>&1 | grep RESULT
python harness/run_plan.py email-not-null plans/tui-email.json session-email 2>&1 | grep RESULT
python harness/run_plan.py drop-status plans/tui-drop.json session-drop 2>&1 | grep RESULT
python harness/run_plan.py customer-bigint controls/customer-bigint/naive-wrapped.json control-customer-bigint-naive-wrapped 2>&1 | grep RESULT
python harness/lint_plan.py controls/customer-bigint/naive-wrapped.json | tail -1 > results/control-customer-bigint-naive-wrapped/squawk.txt
