\set amount amount
\set email_expect s.email
SELECT 'a validated foreign key orders.customer_id -> customers.id', EXISTS (
  SELECT 1 FROM pg_constraint WHERE conrelid = 'orders'::regclass AND contype = 'f' AND confrelid = 'customers'::regclass
     AND convalidated AND conkey = ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid = 'orders'::regclass AND attname = 'customer_id' AND NOT attisdropped)]), '';
