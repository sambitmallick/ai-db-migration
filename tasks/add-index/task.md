The customer page (GET /customer/ID) is slow: it scans the whole orders table. Add an index on orders.customer_id.
