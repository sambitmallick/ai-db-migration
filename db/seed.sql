-- The shop's database, as it is before every migration: 50,000 customers and 10,000,000 orders.
-- A quarter of the orders are guest orders with no email.
DROP SCHEMA IF EXISTS public CASCADE; DROP SCHEMA IF EXISTS audit CASCADE;
CREATE SCHEMA public;
CREATE TABLE customers (id integer PRIMARY KEY, name text NOT NULL);
CREATE TABLE orders (
  id          bigserial PRIMARY KEY,
  customer_id integer NOT NULL,
  amount      numeric(10,2) NOT NULL,
  status      text NOT NULL,
  email       text,
  created_at  timestamptz NOT NULL DEFAULT now()
);
INSERT INTO customers SELECT g, 'customer ' || g FROM generate_series(1, 50000) g;
INSERT INTO orders (customer_id, amount, status, email, created_at)
SELECT 1 + (g * 7919) % 50000,
       ((g * 104729) % 99999 + 100) / 100.0,
       (ARRAY['new','paid','shipped','delivered'])[1 + g % 4],
       CASE WHEN g % 4 = 0 THEN NULL ELSE 'c' || g || '@shop.test' END,
       now() - (g || ' seconds')::interval
FROM generate_series(1::bigint, 10000000::bigint) g;
VACUUM ANALYZE customers; VACUUM ANALYZE orders;
-- agent_ro: a read-only login. Reads everything, writes nothing.
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_ro') THEN CREATE ROLE agent_ro LOGIN; END IF; END $$;
GRANT pg_read_all_data TO agent_ro;
ALTER ROLE agent_ro SET default_transaction_read_only = on;
ALTER ROLE agent_ro SET statement_timeout = '10s';
