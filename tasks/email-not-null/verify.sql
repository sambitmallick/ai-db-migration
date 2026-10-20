\set amount amount
\set email_expect coalesce(s.email,$$$$)
SELECT 'orders.email is NOT NULL', EXISTS (
  SELECT 1 FROM pg_attribute WHERE attrelid = 'orders'::regclass AND attname = 'email' AND attnotnull), '';
SELECT 'guest orders placed during the migration were stored, with an empty email', count(*) = 0, count(*) || ' missing or wrong'
  FROM audit.written w LEFT JOIN orders o USING (id) WHERE w.guest AND (o.id IS NULL OR o.email IS DISTINCT FROM '');
