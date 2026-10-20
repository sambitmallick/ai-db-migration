---
name: migrate
description: Write a database migration plan for the shop's Postgres database, for one of the tasks in tasks/. Use when asked to plan or write a migration.
argument-hint: "<task> <plan-file>"
---

# Migration planner

Arguments: `$ARGUMENTS`. The first word is the task (its request is in `tasks/<task>/task.md`), the second is the
file to write the plan to.

## What you have

- The schema and how the data was created: `db/seed.sql`.
- The app that uses the database: `app/server.js` (three replicas, deployed by `k8s/shop.yaml`). Its settings
  `AMOUNT_READ`, `AMOUNT_WRITE` and `GUEST_EMAIL` decide which columns it reads and writes.
- The live database, read-only: `bash scripts/db-ro.sh "<SQL>"`.

## What you write

One JSON file, the plan, and nothing else. You don't run it: it is run for you, step by step, in order.

```json
{"task": "<task>", "steps": [
  {"note": "what this step does", "sql": "SQL; more SQL;"},
  {"note": "...", "deploy": {"AMOUNT_READ": "..."}},
  {"note": "...", "wait": 5}
]}
```

- `sql`: run by `psql` in autocommit mode: each statement commits on its own unless you write `BEGIN`/`COMMIT`.
- `deploy`: sets the app's environment variables and waits until the rolling update has finished.
- `wait`: seconds.
- If a step fails, the plan stops there.

When the file is written, say in a few lines what the plan does.
