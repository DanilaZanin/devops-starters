CREATE TABLE IF NOT EXISTS product_revenue_by_window (
    window_start   TIMESTAMP NOT NULL,
    window_end     TIMESTAMP NOT NULL,
    product        TEXT NOT NULL,
    orders_count   BIGINT NOT NULL,
    revenue        NUMERIC(12, 2) NOT NULL,
    PRIMARY KEY (window_start, product)
);
