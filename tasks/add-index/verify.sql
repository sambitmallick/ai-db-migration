\set amount amount
\set email_expect s.email
SELECT 'an index on orders(customer_id) exists and is valid', EXISTS (
  SELECT 1 FROM pg_index i JOIN pg_class t ON t.oid = i.indrelid JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = i.indkey[0]
   WHERE t.relname = 'orders' AND a.attname = 'customer_id' AND i.indisvalid AND i.indisready), '';
SELECT 'no invalid index left behind', NOT EXISTS (
  SELECT 1 FROM pg_index i JOIN pg_class t ON t.oid = i.indrelid WHERE t.relname = 'orders' AND NOT i.indisvalid), '';
