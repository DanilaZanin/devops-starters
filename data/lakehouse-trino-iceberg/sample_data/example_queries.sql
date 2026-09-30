-- Revenue by category
SELECT category,
       SUM(quantity * unit_price) AS revenue,
       COUNT(*) AS order_count
FROM iceberg.sales.orders
GROUP BY category
ORDER BY revenue DESC;

-- Top customers by total spend
SELECT customer_id, SUM(quantity * unit_price) AS total_spend
FROM iceberg.sales.orders
GROUP BY customer_id
ORDER BY total_spend DESC
LIMIT 3;

-- Iceberg snapshot history: every write above (including each reload) is a commit
SELECT snapshot_id, committed_at, operation
FROM iceberg.sales."orders$snapshots"
ORDER BY committed_at;
