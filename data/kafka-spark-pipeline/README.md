# Kafka to Spark Structured Streaming to Postgres with docker compose: KRaft broker, checkpoints on a volume, acks=all producer

**Level: lab.** Every PR gets the static checks (`make lint`). The full smoke run (`make test`) runs weekly and on demand, not on every PR.

A synthetic order producer writes JSON events to Kafka, a Spark Structured Streaming job aggregates revenue per product in 1-minute windows, and the results are upserted into Postgres.

## Problem

The first version of this pipeline worked on the day it was written and then failed in small ways:
- the Spark job kept its checkpoint inside the container, so a restart started over from the earliest offset and re-read the whole topic;
- the Spark job downloaded the Kafka connector from Maven Central on every start, so a cold start needed the internet and took a long time;
- `localhost:29092` was advertised to host clients but never published, while the internal port 9092 was published on all interfaces;
- the producer never called `flush()` and used default acks, so events in flight were lost on shutdown.

## Quick start

```bash
make up      # builds two images, starts Kafka, Postgres, the producer and the Spark job
make psql    # then: SELECT * FROM product_revenue_by_window ORDER BY window_start DESC LIMIT 10;
make test    # static checks, then an end-to-end smoke run (a few minutes)
make reset   # removes containers and all data
```

Expected: about a minute after `make up`, `make logs` shows lines like `batch 0: upserted 18 aggregated rows into postgres`, and the query above returns one row per product and window with `orders_count` and `revenue` growing while the window is open. `make test` ends with `SMOKE PASSED`.

Requirements: docker with compose v2, python3, make. Budget several GB of RAM for Docker: Kafka and Spark both run a JVM. `make check-prereqs` verifies the tools.

| Verified on | RAM | First run (cold image cache) |
|---|---|---|
| 2026-09-29, macOS arm64, colima 4 CPU / 8 GB, `make test`: SMOKE PASSED (not yet run on an ubuntu-24.04 runner) | about 1.5 GiB in total, Spark about 1.1 GiB, Kafka about 0.3 GiB (`docker stats`) | about 60 s for build, start and first rows with the base images already pulled; the pull of the Spark, Kafka and Postgres images is extra |

## Traps this avoids

1. **Checkpoint on a volume, not in the container.** `checkpointLocation` points at `/checkpoints/orders`, a named volume. `startingOffsets=earliest` only applies to the very first run; a restarted job resumes from its last committed offsets. The smoke test checks that the checkpoint exists on the volume.
2. **Connector baked into the image.** The Kafka connector and its dependencies are resolved at build time into an Ivy cache (`spark-job/Dockerfile`), so `docker compose up` needs no Maven Central. The base image is the explicit `apache/spark:4.1.3-python3` tag, so the Python that PySpark needs is part of the tag's contract.
3. **Listeners.** Kafka 4.3 in KRaft mode has an `INTERNAL` listener (`kafka:9092`, for containers) and an `EXTERNAL` one (`localhost:29092`, for clients on your machine). Only the external one is published, and only on 127.0.0.1 (checked by `tests/check_compose.py`, which is first run against a bad sample config and must flag it).
4. **Producer durability.** `acks=all` with idempotence, delivery callbacks that count failures, and a SIGTERM handler that calls `flush()` before exiting, with a 30 second stop grace period in compose.
5. **Upsert, not append.** `outputMode("update")` re-emits a window's aggregate on every trigger, so the sink must be an `INSERT ... ON CONFLICT DO UPDATE`. That also makes a replayed batch harmless.

6. **Schema baked into the Postgres image.** `postgres-init/Dockerfile` copies the init SQL into `/docker-entrypoint-initdb.d/` instead of bind-mounting it. A bind mount from a path the Docker VM cannot see (for example a copy under macOS `$TMPDIR` with colima, or a remote daemon) arrives empty, the table is never created and the Spark job fails at its first write. Also, a failed run leaves the Postgres volume initialized, so run `make reset` before retrying.

Topics are created by a `kafka-init` service and auto-creation is off, so a typo in a topic name fails instead of creating an empty topic.

## What the test proves / does NOT prove

`make test` runs `tests/check_compose.py` (pinned image tags, loopback-only ports, in the compose file and all Dockerfiles), then `tests/smoke.sh`.

Proves:
- the stack starts from scratch and aggregated rows with a non-zero order count reach Postgres;
- the producer received delivery confirmations;
- the external listener is published on 127.0.0.1;
- a Spark checkpoint exists on the volume.

Does NOT prove:
- That a restart resumes without reprocessing. The test looks for the checkpoint but does not restart the job and compare counts.
- Behavior under broker failure, rebalances or a slow Postgres.
- Exactly-once delivery. The path is at-least-once into Postgres, made safe by the upsert.
- Anything about late data beyond the 1 minute watermark.
- That the base image tags are current: they are pinned, not verified against a registry by this test.

## Local demo vs production

One broker with replication factor 1, no authentication or TLS, one Spark process in local mode, a Postgres with a password from `.env`. For production you also need:
- 3 brokers, `min.insync.replicas=2`, authentication and TLS on the listeners;
- Spark on a cluster manager, with checkpoints on durable shared storage (HDFS or object storage), not a local volume;
- a schema for the events (schema registry) instead of "whatever JSON arrives", and a dead-letter path for events that fail to parse: today they become NULL columns;
- monitoring of consumer lag and of the streaming query's progress;
- retention and compaction settings chosen for the topic.

## Copy it into your project

`producer/producer.py` shows the durable producer settings; `spark-job/Dockerfile` shows how to bake the connector into the image; the Kafka block of `docker-compose.yml` is a working single-node KRaft setup with two listeners. The whole folder also works on its own: `cp -r data/kafka-spark-pipeline /elsewhere && cd /elsewhere && make test`.

Pins: Apache Kafka 4.3.1, Apache Spark 4.1.3 with `spark-sql-kafka-0-10_2.13:4.1.3` (Spark 4 is built for Scala 2.13), PostgreSQL 18.6, psycopg 3.3.6, confluent-kafka 2.15.1 on Python 3.12.
