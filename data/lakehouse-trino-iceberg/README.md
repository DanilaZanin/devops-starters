# Local lakehouse with Trino, Iceberg REST catalog and an S3 server: idempotent loads, pinned images, no duplicate rows on re-run

**Level: lab.** Every PR gets the static checks (`make lint`). The full smoke run (`make test`) runs weekly and on demand, not on every PR.

RustFS as S3-compatible storage, an Iceberg REST catalog, and Trino as the query engine. Trino creates and writes the Iceberg table itself, so no second compute engine is needed to get data in.

## Problem

Load scripts for a sandbox like this are usually a `CREATE TABLE IF NOT EXISTS` followed by a plain `INSERT`. The first run is fine. Run it again (a retried job, a second `make load`, a teammate following the README) and every row exists twice, so every aggregate is doubled and nothing reports an error.

The stack itself also drifts: `:latest` tags of the S3 server and `apache/iceberg-rest-fixture:latest` move under you, and the root credentials were written into committed files.

## Quick start

```bash
make up      # starts the S3 server, the catalog and Trino, waits until all three are healthy
make load    # loads 10 sample orders; run it as often as you like
make query   # revenue by category, top customers, Iceberg snapshot history
make test    # static checks, then the smoke run including the duplicate-load trap
make reset   # removes containers and all data
```

Expected `make query` output (the Trino CLI prints CSV with quoted values). First the revenue by category, then the top three customers, then one line per Iceberg snapshot:

```
"audio","387.00","2"
"peripherals","378.92","5"
"accessories","215.90","3"
"CUST-01","270.98"
"CUST-04","258.00"
"CUST-02","238.99"
"<snapshot id>","<timestamp> UTC","append"
...
```

Every load adds a `delete` and an `append` snapshot, so the list grows with each `make load`.

`make test` ends with `SMOKE PASSED`. Trino's UI is at http://127.0.0.1:8080 and the RustFS console at http://127.0.0.1:9001 (`S3_ACCESS_KEY` and `S3_SECRET_KEY` from `.env`).

Requirements: docker with compose v2, python3, make. Budget several GB of RAM for Docker (Trino is a JVM). `make check-prereqs` verifies the tools.

| Verified on | RAM | First run (cold image cache) |
|---|---|---|
| 2026-09-29, macOS arm64, colima 4 CPU / 8 GB, `make test`: SMOKE PASSED, twice in a row (not yet run on an ubuntu-24.04 runner) | about 1.4 GiB in total, Trino about 1.0 GiB (`docker stats`) | about 30 s for `make test` (it starts from clean volumes) with the images already pulled; the image pull is extra |

## Traps this avoids

1. **Non-idempotent load** (reproduced in tests). `sample_data/load_sample_data.sql` deletes the table's rows before inserting, so running it twice leaves 10 rows. `traps/load_naive.sql` is the plain-INSERT version.
2. **`latest` tags.** Every image is pinned (`tests/check_compose.py` fails on `latest` or a missing tag, in the compose file and in Dockerfiles).
3. **Credentials in committed files.** S3 credentials come from `.env`. Trino reads them into `iceberg.properties` with its `${ENV:NAME}` substitution, so the file has no secret in it.
4. **Data lost on restart of the S3 server.** Object data lives on a named volume.
5. **Trino "ready" but the catalog is not** (reproduced in tests). `SELECT 1` succeeds as soon as Trino is up, because Trino talks to the REST catalog lazily; the first `CREATE SCHEMA` after it can then fail. The catalog has its own healthcheck (it lists namespaces), Trino waits for it with `service_healthy`, and Trino's healthcheck runs `SHOW SCHEMAS FROM iceberg`, which goes through the catalog. `make up` and the smoke test use `docker compose up --wait`.

Ports are published on 127.0.0.1 only.

## What the test proves / does NOT prove

The smoke test starts from clean volumes (it deletes this module's containers and data first). It creates the table with the naive loader and runs it twice: it must see 20 rows (the trap is real). It then runs the idempotent loader twice on the same table and must see exactly 10. Before that, it starts Trino alone, without the catalog, and requires that `SELECT 1` works while Trino's healthcheck fails. It then brings up the whole stack with `--wait` and runs the first statement with no polling. The test also checks the example queries (`audio,387.00,2`, a top customer, `append` snapshots in the Iceberg history) and that Trino is published on loopback.

Does NOT prove:
- Atomic reloads. Between the `DELETE` and the `INSERT` the table is briefly empty; concurrent readers can see that. `MERGE INTO` keyed on `order_id` avoids the gap.
- Anything about scale: 10 rows.
- That the catalog survives a restart. `apache/iceberg-rest-fixture` is a test fixture: its table registry is in memory, so recreating the `iceberg-rest` container forgets the tables while the data files stay in the bucket. `make reset` gives a clean start.
- Compatibility with newer Trino releases. The stack was verified with Trino 483, the version pinned in `trino/Dockerfile` (`make test` passes on it); bump it deliberately and rerun `make test`.

## Local demo vs production

- **S3 server.** The first version of this stack used MinIO. Its `minio/minio` and `minio/mc` release tags are no longer available on Docker Hub (the community images were withdrawn), so a pinned MinIO tag cannot be pulled any more. This module uses `rustfs/rustfs:1.0.0` (S3-compatible, Apache-2.0) and `amazon/aws-cli` to create the bucket. RustFS is young; for anything real, use a supported S3-compatible store or cloud object storage.
- **Bind mounts.** Trino's catalog file, the sample data and the trap script are copied into a small image built from `trino/Dockerfile` instead of bind-mounted, so the stack also starts from a copy of the directory that the Docker VM cannot see (macOS `$TMPDIR` with colima).
- **Catalog.** Use a real Iceberg catalog (a JDBC catalog on Postgres, Nessie, Polaris, Lakekeeper, or your cloud's) instead of the REST fixture.
- **Security.** Trino runs without authentication or TLS, the S3 server with root credentials, and the S3 endpoint is plain HTTP. Add authentication, per-service credentials and TLS.
- **Maintenance.** Iceberg tables need snapshot expiry and compaction (`expire_snapshots`, `optimize`) or metadata and small files pile up.
- **Sizing.** One Trino node acts as coordinator and worker.

## Copy it into your project

`trino/catalog/iceberg.properties` plus the three Iceberg-related services in `docker-compose.yml` are the reusable part. Use `sample_data/load_sample_data.sql` as a pattern for loads you want to be safe to repeat. The whole folder also works on its own: `cp -r data/lakehouse-trino-iceberg /elsewhere && cd /elsewhere && make test`.

Pins: Trino 483, Apache Iceberg REST fixture 1.10.1, RustFS 1.0.0, AWS CLI 2.37.6 (bucket creation only).
