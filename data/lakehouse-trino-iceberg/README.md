# lakehouse-sandbox

A local "lakehouse" stack: MinIO as S3-compatible object storage, an Iceberg
REST catalog, and Trino as the query engine. Load some data, run SQL against
it, poke at Iceberg's snapshot history — a sandbox for learning or
prototyping without needing an actual cloud data platform.

## Structure

```
docker-compose.yml
trino/catalog/iceberg.properties   # Trino's Iceberg connector config (REST catalog + MinIO)
sample_data/
  load_sample_data.sql              # creates a partitioned Iceberg table, inserts sample rows
  example_queries.sql               # aggregations + Iceberg snapshot history query
```

## Why these specific pieces

- **MinIO** — S3 API without needing an AWS account, and it's what the
  target job posting's stack actually uses (MinIO, not raw AWS S3).
- **Iceberg REST catalog** — the standard way modern engines (Trino, Spark,
  Flink) discover and agree on Iceberg table metadata, instead of each
  engine needing its own catalog implementation (Hive metastore, glue, etc).
- **Trino** — a distributed SQL engine that can create *and* query Iceberg
  tables on its own, so this sandbox doesn't need a second compute engine
  (like Spark) just to get data in.

## Usage

```bash
docker compose up -d
docker exec -it lakehouse-trino trino -f /path/to/load_sample_data.sql
docker exec -it lakehouse-trino trino --catalog iceberg --schema sales
```

```sql
SELECT category, SUM(quantity * unit_price) AS revenue
FROM iceberg.sales.orders
GROUP BY category
ORDER BY revenue DESC;
```

## Verified — real queries against real Parquet files in MinIO

```
$ docker exec lakehouse-trino trino -f load_sample_data.sql
CREATE SCHEMA
CREATE TABLE
INSERT: 10 rows

$ docker exec lakehouse-trino trino -f example_queries.sql
"audio","387.00","2"
"peripherals","378.92","5"
"accessories","215.90","3"
"CUST-01","270.98"
"CUST-04","258.00"
"CUST-02","238.99"
"8397879165621625696","2026-07-31 09:35:10... UTC","append"
"9039158642022859286","2026-07-31 09:35:13... UTC","append"
```

The last two rows are from querying `iceberg.sales."orders$snapshots"` —
proof this is a real Iceberg table with commit history, not just a Parquet
file with a SQL wrapper on top.

And the data really is sitting in MinIO as partitioned Parquet, not just
referenced by the catalog:

```
$ mc find local/warehouse --name "*.parquet"
local/warehouse/sales/orders-.../data/category=accessories/....parquet
local/warehouse/sales/orders-.../data/category=audio/....parquet
local/warehouse/sales/orders-.../data/category=peripherals/....parquet
```

Table was created with `partitioning = ARRAY['category']` and the physical
layout on S3 shows exactly that partitioning — `category=accessories/`,
`category=audio/`, `category=peripherals/` — confirming Trino's Iceberg
writer actually partitioned the data, not just tagged it in metadata.

Stack: MinIO (latest), `apache/iceberg-rest-fixture` (REST catalog backed by
SQLite metadata store), Trino 455, tested on Ubuntu 22.04.
