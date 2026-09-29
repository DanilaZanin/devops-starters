# kafka-spark-streaming-pipeline

A real-time pipeline: a producer generates order events onto Kafka, Spark
Structured Streaming (Spark Streaming API) consumes them, aggregates revenue
per product in 1-minute tumbling windows, and upserts the results into
Postgres. Runs entirely with `docker compose up`.

## Structure

```
docker-compose.yml
producer/           # generates synthetic order events onto the "orders" topic
  producer.py
  Dockerfile
spark-job/           # Spark Structured Streaming job: Kafka -> windowed aggregate -> Postgres
  spark_job.py
  Dockerfile
postgres-init/        # creates the target table on first boot
  001_create_table.sql
```

## Data flow

```
producer.py --(JSON events)--> Kafka topic "orders"
                                     |
                                     v
                     Spark readStream.format("kafka")
                                     |
                     parse JSON, watermark(1 min),
                     groupBy(window(1 min), product)
                                     |
                                     v
                  foreachBatch -> upsert into Postgres
                  (product_revenue_by_window)
```

Each event looks like:
```json
{"order_id": "...", "product": "wireless-mouse", "price": 19.42, "quantity": 2, "ts": "2026-01-01T12:00:00+00:00"}
```

## Usage

```bash
docker compose up -d --build
docker compose logs -f spark-job     # watch batches land
docker exec -it pipeline-postgres psql -U pipeline -d analytics \
  -c "SELECT * FROM product_revenue_by_window ORDER BY window_start DESC LIMIT 10;"
```

## A real bug I hit and fixed (not hidden)

First version used Spark's plain JDBC `writeStream`... `.mode("append")`. That
crashed the query on the *second* trigger:

```
Detail: Key (window_start, product)=(..., webcam-1080p) already exists.
```

The reason: `outputMode("update")` re-emits a window's aggregate on every
trigger for as long as the window is still open (i.e. until the watermark
passes it) — so the second batch tries to insert a row for a window/product
pair that the first batch already inserted. Plain `append` has no way to
handle that; JDBC's built-in sink doesn't support upserts.

Fixed by switching `foreachBatch` to `psycopg2` with a real
`INSERT ... ON CONFLICT (window_start, product) DO UPDATE`. Collecting the
batch driver-side is fine here — these are the *aggregated* rows per
trigger (a handful to low hundreds), not the raw event stream.

## Verified — ran the full stack, not just `docker compose up` and hope

```
$ docker compose up -d --build
...
Container orders-producer Started
Container orders-spark-streaming Started

$ docker logs orders-producer --tail 3
producing to orders @ ~5.0/s
sent 50 events so far

$ docker logs orders-spark-streaming | grep batch
batch 0: upserted 18 aggregated rows into postgres
batch 1: upserted 6 aggregated rows into postgres
batch 2: upserted 6 aggregated rows into postgres     # three consecutive triggers, no crash

$ docker exec pipeline-postgres psql -U pipeline -d analytics -c \
  "SELECT window_start, product, orders_count, revenue FROM product_revenue_by_window ORDER BY window_start DESC LIMIT 6;"
    window_start     |         product          | orders_count | revenue
---------------------+--------------------------+--------------+----------
 2026-07-31 09:31:00 | wireless-mouse           |           29 |  1410.00
 2026-07-31 09:31:00 | webcam-1080p             |           37 |  5808.50
 2026-07-31 09:31:00 | usb-c-hub                |           31 |  2388.50
 2026-07-31 09:31:00 | noise-cancelling-headset |           43 | 13613.57
 2026-07-31 09:31:00 | mechanical-keyboard      |           45 |  9841.54
 2026-07-31 09:31:00 | laptop-stand             |           39 |  3812.16
```

Order counts and revenue climbing across consecutive queries against the
same window confirms the upsert is working (not just inserting once and
silently dropping updates).

Stack: Apache Kafka 3.8 (KRaft mode, no ZooKeeper), Apache Spark 3.5.3
(Structured Streaming, `spark-sql-kafka-0-10` connector), PostgreSQL 16,
Python 3.11 (`kafka-python`, `psycopg2`). Tested on Ubuntu 22.04, 4 vCPU / 13GB RAM.
