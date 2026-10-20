-- shared: nothing lost, nothing changed. :amount / :email are the expressions for the orders columns after the task.
SELECT 'all 10,000,000 original orders still exist', count(*) = 0, count(*) || ' missing'
  FROM audit.snap s LEFT JOIN orders o USING (id) WHERE o.id IS NULL;
SELECT 'original orders: amount, customer and email unchanged', count(*) = 0, count(*) || ' changed'
  FROM audit.snap s JOIN orders o USING (id)
 WHERE o.:amount <> s.amount OR o.customer_id <> s.customer_id OR o.email IS DISTINCT FROM :email_expect;
SELECT 'every order placed during the migration is there, unchanged', count(*) = 0, count(*) || ' of ' || (SELECT count(*) FROM audit.written) || ' missing or changed'
  FROM audit.written w LEFT JOIN orders o USING (id)
 WHERE o.id IS NULL OR o.:amount <> w.amount OR o.customer_id <> w.customer_id;
