#!/bin/bash
# seed.sh: (re)create the shop database from db/seed.sql: 50,000 customers, 10,000,000 orders.
set -e
cd "$(dirname "$0")/.."
kubectl exec -i deploy/postgres -- psql -U postgres -d shop -q -v ON_ERROR_STOP=1 < db/seed.sql
kubectl exec deploy/postgres -- psql -U postgres -d shop -At -c "SELECT 'orders: ' || count(*) || ', guest orders (email NULL): ' || count(*) FILTER (WHERE email IS NULL) || ', table size: ' || pg_size_pretty(pg_total_relation_size('orders')) FROM orders"
