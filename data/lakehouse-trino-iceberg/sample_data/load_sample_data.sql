-- Loads a small sales dataset into an Iceberg table on MinIO, via Trino's
-- Iceberg connector. Nothing here needs Spark — Trino can create and write
-- Iceberg tables on its own, which is the whole point of this sandbox: kick
-- the tires on the query engine without standing up a second compute engine
-- just to get data in.

CREATE SCHEMA IF NOT EXISTS iceberg.sales
WITH (location = 's3://warehouse/sales');

CREATE TABLE IF NOT EXISTS iceberg.sales.orders (
    order_id     VARCHAR,
    customer_id  VARCHAR,
    product      VARCHAR,
    category     VARCHAR,
    quantity     INTEGER,
    unit_price   DECIMAL(10, 2),
    order_date   DATE
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['category']
);

INSERT INTO iceberg.sales.orders VALUES
    ('ORD-1001', 'CUST-01', 'wireless-mouse',            'peripherals', 2, 19.99,  DATE '2026-01-05'),
    ('ORD-1002', 'CUST-02', 'mechanical-keyboard',       'peripherals', 1, 89.50,  DATE '2026-01-05'),
    ('ORD-1003', 'CUST-01', 'usb-c-hub',                 'accessories', 3, 34.00,  DATE '2026-01-06'),
    ('ORD-1004', 'CUST-03', 'laptop-stand',               'accessories', 1, 45.90,  DATE '2026-01-06'),
    ('ORD-1005', 'CUST-02', 'webcam-1080p',               'peripherals', 1, 59.99,  DATE '2026-01-07'),
    ('ORD-1006', 'CUST-04', 'noise-cancelling-headset',   'audio',       2, 129.00, DATE '2026-01-07'),
    ('ORD-1007', 'CUST-01', 'noise-cancelling-headset',   'audio',       1, 129.00, DATE '2026-01-08'),
    ('ORD-1008', 'CUST-05', 'wireless-mouse',             'peripherals', 5, 19.99,  DATE '2026-01-08'),
    ('ORD-1009', 'CUST-03', 'usb-c-hub',                  'accessories', 2, 34.00,  DATE '2026-01-09'),
    ('ORD-1010', 'CUST-02', 'mechanical-keyboard',        'peripherals', 1, 89.50,  DATE '2026-01-09');
