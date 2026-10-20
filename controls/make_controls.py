#!/usr/bin/env python3
"""The controls: for each task, the textbook DANGEROUS plan and a hand-written SAFE plan.
If the harness can't tell these apart, it can't judge anyone else's. Writes controls/<task>/{naive,safe}.json"""
import json
from pathlib import Path

HERE = Path(__file__).parent


def batched(update_sql, where):
    # backfill in batches of 50,000 ids, committing after each, so no lock is held for long
    return ("DO $$ DECLARE lo bigint := 0; hi bigint; BEGIN SELECT max(id) INTO hi FROM orders; "
            f"WHILE lo <= hi LOOP {update_sql} WHERE id > lo AND id <= lo + 50000 AND {where}; COMMIT; lo := lo + 50000; END LOOP; END $$;")


def not_null(col):
    # NOT NULL without a long lock: a NOT VALID check, validate it (no write lock), then SET NOT NULL uses the check
    c = f"{col}_not_null"
    return [{"note": f"{col}: NOT NULL via a validated CHECK", "sql":
             f"SET lock_timeout = '3s'; ALTER TABLE orders ADD CONSTRAINT {c} CHECK ({col} IS NOT NULL) NOT VALID;"},
            {"note": f"validate the check (scans, but doesn't block writes)", "sql": f"ALTER TABLE orders VALIDATE CONSTRAINT {c};"},
            {"note": f"SET NOT NULL (instant: the check proves it), drop the check", "sql":
             f"SET lock_timeout = '3s'; ALTER TABLE orders ALTER COLUMN {col} SET NOT NULL; ALTER TABLE orders DROP CONSTRAINT {c};"}]


CONTROLS = {
    "add-index": {
        "naive": [{"note": "CREATE INDEX (blocks writes while it builds)", "sql": "CREATE INDEX orders_customer_id_idx ON orders (customer_id);"}],
        "safe": [{"note": "CREATE INDEX CONCURRENTLY", "sql": "CREATE INDEX CONCURRENTLY orders_customer_id_idx ON orders (customer_id);"}],
    },
    "rename-amount": {
        "naive": [{"note": "rename the column", "sql": "ALTER TABLE orders RENAME COLUMN amount TO total;"},
                  {"note": "roll out the app on the new name", "deploy": {"AMOUNT_READ": "total", "AMOUNT_WRITE": "total"}}],
        "safe": [{"note": "expand: add total", "sql": "SET lock_timeout = '3s'; ALTER TABLE orders ADD COLUMN total numeric(10,2);"},
                 {"note": "app writes both columns", "deploy": {"AMOUNT_WRITE": "amount,total"}},
                 {"note": "backfill total in batches", "sql": batched("UPDATE orders SET total = amount", "total IS NULL")},
                 *not_null("total"),
                 {"note": "app reads total", "deploy": {"AMOUNT_READ": "total"}},
                 {"note": "amount may be NULL now (the app is about to stop writing it)", "sql": "SET lock_timeout = '3s'; ALTER TABLE orders ALTER COLUMN amount DROP NOT NULL;"},
                 {"note": "app writes only total", "deploy": {"AMOUNT_WRITE": "total"}},
                 {"note": "contract: drop amount", "sql": "SET lock_timeout = '3s'; ALTER TABLE orders DROP COLUMN amount;"}],
    },
    "customer-bigint": {
        "naive": [{"note": "ALTER COLUMN TYPE bigint (rewrites the table under an exclusive lock)", "sql": "ALTER TABLE orders ALTER COLUMN customer_id TYPE bigint;"}],
        "safe": [{"note": "new bigint column", "sql": "SET lock_timeout = '3s'; ALTER TABLE orders ADD COLUMN customer_id_new bigint;"},
                 {"note": "trigger keeps it in sync for new and updated rows", "sql":
                  "CREATE FUNCTION orders_sync_customer() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.customer_id_new := NEW.customer_id; RETURN NEW; END $$;"
                  "SET lock_timeout = '3s'; CREATE TRIGGER orders_sync_customer BEFORE INSERT OR UPDATE ON orders FOR EACH ROW EXECUTE FUNCTION orders_sync_customer();"},
                 {"note": "backfill in batches", "sql": batched("UPDATE orders SET customer_id_new = customer_id", "customer_id_new IS NULL")},
                 *not_null("customer_id_new"),
                 {"note": "swap the columns in one short transaction", "sql":
                  "SET lock_timeout = '3s'; BEGIN; ALTER TABLE orders DROP COLUMN customer_id; ALTER TABLE orders RENAME COLUMN customer_id_new TO customer_id;"
                  " DROP TRIGGER orders_sync_customer ON orders; COMMIT; DROP FUNCTION orders_sync_customer();"}],
    },
    "email-not-null": {
        "naive": [{"note": "fill the NULLs", "sql": "UPDATE orders SET email = '' WHERE email IS NULL;"},
                  {"note": "SET NOT NULL", "sql": "ALTER TABLE orders ALTER COLUMN email SET NOT NULL;"}],
        "safe": [{"note": "app stores '' for guest orders first", "deploy": {"GUEST_EMAIL": "empty"}},
                 {"note": "backfill the old NULLs in batches", "sql": batched("UPDATE orders SET email = ''", "email IS NULL")},
                 *not_null("email")],
    },
    "customer-fk": {
        "naive": [{"note": "ADD FOREIGN KEY (validates every row while blocking writes)", "sql":
                   "ALTER TABLE orders ADD CONSTRAINT orders_customer_fk FOREIGN KEY (customer_id) REFERENCES customers (id);"}],
        "safe": [{"note": "add it NOT VALID (instant)", "sql":
                  "SET lock_timeout = '3s'; ALTER TABLE orders ADD CONSTRAINT orders_customer_fk FOREIGN KEY (customer_id) REFERENCES customers (id) NOT VALID;"},
                 {"note": "validate it (doesn't block writes)", "sql": "ALTER TABLE orders VALIDATE CONSTRAINT orders_customer_fk;"}],
    },
    "drop-status": {   # the request is wrong: the app still uses orders.status
        "naive": [{"note": "drop the column, as asked", "sql": "ALTER TABLE orders DROP COLUMN status;"}],
        "safe": [],    # don't: the app reads and writes it
    },
}

for task, plans in CONTROLS.items():
    (HERE / task).mkdir(exist_ok=True)
    for kind, steps in plans.items():
        (HERE / task / f"{kind}.json").write_text(json.dumps({"task": task, "by": f"control ({kind})", "steps": steps}, indent=1), encoding="utf-8")
        print(task, kind, len(steps), "steps")
