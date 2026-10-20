\set amount amount
\set email_expect s.email
SELECT 'orders.customer_id is bigint NOT NULL', EXISTS (
  SELECT 1 FROM pg_attribute WHERE attrelid = 'orders'::regclass AND attname = 'customer_id' AND NOT attisdropped
     AND attnotnull AND atttypid = 'bigint'::regtype), '';
