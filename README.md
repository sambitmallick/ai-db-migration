# ai-db-migration: can an AI run a zero-downtime database migration under live traffic?

Companion repo to a [DevOps Autopilot](https://www.youtube.com/@DevOpsAutopilot) episode. Every command in the
video was run for real; its full output is in [`commands/`](commands). Every plan, every run's measurements and
every conversation are in the repo.

A shop service (3 replicas) on Postgres in a local [kind](https://kind.sigs.k8s.io) cluster: 10,000,000 orders,
live traffic at 60 requests/s from inside the cluster, every request recorded. Claude Code, through a
[`/migrate` skill](.claude/skills/migrate/SKILL.md), writes a migration plan (SQL steps and app rollouts); a
[harness](harness/run_plan.py) runs it against the live database and measures what it did:

- every request during and after the migration: failed, slow, or fine
- sessions waiting on locks, sampled every 0.25 s inside Postgres
- afterwards ([`tasks/*/verify.sql`](tasks), [`tasks/data_checks.sql`](tasks/data_checks.sql)): the schema is right,
  all 10,000,000 original orders exist with unchanged values, and every order placed *during* the migration was kept

A run is **zero-downtime** only if the plan completed, no request failed during or after, and every check passed.

## The six tasks

| task | the textbook way | what it does to the live shop (my control, [`controls/`](controls)) |
|---|---|---|
| add an index on `orders.customer_id` | `CREATE INDEX` | blocks every insert while it builds: **92 of 310 requests failed** |
| rename `amount` to `total` | `RENAME COLUMN`, then deploy the app | the running app queries a column that's gone: **280 of 337 failed** |
| `customer_id` int to bigint | `ALTER COLUMN TYPE` | rewrites 10M rows under an exclusive lock: **596 of 747 failed** |
| `email` NOT NULL, guests get `''` | `UPDATE` all, then `SET NOT NULL` | locks, and guest orders arriving *during* the update add new NULLs: **252 failed and the plan aborted** |
| foreign key to `customers` | `ADD CONSTRAINT ... FOREIGN KEY` | validates every row while blocking writes: **23 of 197 failed** |
| "`status` isn't used any more, drop it" | `DROP COLUMN` | **the request is wrong**: the app reads and writes it. **1,845 of 1,845 requests failed afterwards** |

My hand-written safe version of each ([`controls/make_controls.py`](controls/make_controls.py)): 6 of 6 zero-downtime.

## Results ([`commands/23_scoreboard-clean.txt`](commands/23_scoreboard-clean.txt))

36 AI runs: 6 tasks x 3 runs x 2 ways of asking. *Plain*: just the request. *Live*: the request plus "this runs
on production under live traffic, no errors, no downtime, no data loss".

| | zero-downtime |
|---|---|
| Claude Code, plain request | **18 / 18** |
| Claude Code, live request | **18 / 18** |
| the textbook way (my controls) | 0 / 6 |

- Every index: `CREATE INDEX CONCURRENTLY`. Every constraint: `NOT VALID`, then `VALIDATE`. Every exclusive lock:
  a short `lock_timeout` in a retry loop. Every backfill: batched, committing as it goes.
- The rename: expand/contract with a sync trigger, staged app rollouts, and once (on camera) a trick I hadn't
  thought of: rename the table, put a view called `orders` in front of it that answers to *both* column names,
  roll the app, swap back. 20 seconds, no backfill, 0 failed requests.
- The email task: all 6 plans changed the app's guest-email setting *first*, the thing my textbook control missed.
- Drop `status`: **refused 6 times out of 6**, citing the exact lines in `app/server.js`. Plain or live.

**Squawk** ([`harness/lint_plan.py`](harness/lint_plan.py)), the open-source Postgres migration linter, as a no-AI
check: it flags the lock risk in all 4 textbook plans that take a long lock. The textbook rename and drop it only
marks "may break app", and it raises the same warning on my *safe* rename and bigint plans: it can't see the app,
so it can't tell the two apart. On the 36 AI plans it found no lock risk at all, but that means less than it sounds: **24 of 36 plans put their
DDL inside `DO` blocks** (the retry loops), and Squawk doesn't look inside them. The textbook bigint change wrapped
in a `DO` block: Squawk reports nothing, and **711 of 854 requests failed** ([`commands/24_squawk-blind.txt`](commands/24_squawk-blind.txt), [`25`](commands/25_sessions-under-traffic.txt)).

## What went wrong on the way: my test, not the AI (all of it is in the repo)

1. **The seed overflowed an integer** and created 0 orders; the script reported success. Fixed, and `set -e`.
2. **My app wasn't ready for zero-downtime deploys.** Node runs as PID 1 in the container and ignored SIGTERM, so
   during a rollout the old pods kept serving the *old* app version on keep-alive connections for 30 s. Even my
   safe rename failed 1,479 requests *after* it finished. Graceful shutdown fixed it ([`results-controls-v1/`](results-controls-v1)).
3. **My test traffic was flaky:** the customer page scans 10M rows and timed out whenever a backfill kept the disk
   busy. Taken out of the traffic mix.
4. **The agent could read the answers.** A blanket `Read` permission let it read `../controls`, the harness and the
   checks. Now it works in an isolated [`workspace/`](experiment/make_plan.py) with only what an engineer would have.
5. **Source comments leaked the setup** ("live traffic", "the harness"). Neutralised, so *plain* really is plain.
6. **Two experiment loops ran at once** (stopping a background job didn't stop its children) and spoiled a batch.
   The harness now takes a lock, and a run with too little traffic is marked INVALID instead of scored.
7. **The agent planned against the previous run's leftovers,** including my snapshot tables in an `audit` schema
   (18 of 36 runs saw them). The database is now re-seeded before every planning session and the snapshot dropped
   after every run, and **all 36 runs were redone**. The first batch is kept in [`archive-leaky/`](archive-leaky):
   it scored 18/18 and 17/18 (the 1 failure: a single 1 ms connection reset, 1 in 229,439 requests across all runs).
8. The seed file the agent reads still contains `DROP SCHEMA IF EXISTS audit CASCADE;` (harmless, left as is so
   every clean run saw the same thing).

## The rules

1. **Measure the migration under real traffic.** "It ran without errors" says nothing about the requests it blocked.
2. **Check the data, not just the schema:** every original row, and every row written during the migration.
3. **Test your test.** Run the known-dangerous and the known-safe version first. Mine caught six bugs in my setup.
4. **Zero-downtime migrations need zero-downtime deploys:** graceful shutdown, or the app is the outage.
5. **A linter only sees what it can parse.** Squawk is useful and fast, and blind inside a `DO` block.
6. **Give the agent the app, not just the schema.** The traps (guest emails, the "unused" column) were in the code.

```bash
kind create cluster --name dbmig
podman build -t localhost/shop-db:1.0 app/ && podman save -o shop-db.tar localhost/shop-db:1.0 && kind load image-archive shop-db.tar --name dbmig
kubectl apply -f k8s/postgres.yaml -f k8s/shop.yaml
bash scripts/seed.sh                                          # 10M orders
python harness/run_plan.py add-index controls/add-index/naive.json try-naive
bash experiment/run_ai.sh plain 3 add-index                   # Claude Code plans, Squawk lints, the harness runs it
python experiment/scoreboard.py
```

---
🎬 Full walkthrough: **[the video](https://youtu.be/fv18ye0iErc)** · channel: **[DevOps Autopilot](https://www.youtube.com/@DevOpsAutopilot)**
