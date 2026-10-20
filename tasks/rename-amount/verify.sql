\set amount total
\set email_expect s.email
SELECT 'orders.total exists, numeric(10,2), NOT NULL', EXISTS (
  SELECT 1 FROM pg_attribute WHERE attrelid = 'orders'::regclass AND attname = 'total' AND NOT attisdropped
     AND attnotnull AND format_type(atttypid, atttypmod) = 'numeric(10,2)'), '';
SELECT 'orders.amount is gone', NOT EXISTS (
  SELECT 1 FROM pg_attribute WHERE attrelid = 'orders'::regclass AND attname = 'amount' AND NOT attisdropped), '';
