#!/usr/bin/env bash
# Smoke test with one trap in it:
#   1. the naive loader (plain INSERT), run twice, must leave DUPLICATE rows (20);
#   2. the idempotent loader, run twice on top of that, must leave exactly 10 rows;
#   3. the example queries must return the expected numbers.
set -euo pipefail

cd "$(dirname "$0")/.."
TIMEOUT="${SMOKE_TIMEOUT:-300}"
COMPOSE=(docker compose)

fail() {
  echo "SMOKE FAILED: $*" >&2
  "${COMPOSE[@]}" ps >&2 || true
  "${COMPOSE[@]}" logs --tail 40 trino iceberg-rest s3 >&2 || true
  exit 1
}

trino_sql() {
  "${COMPOSE[@]}" exec -T trino trino --output-format CSV_UNQUOTED --execute "$1"
}

trino_file() {
  "${COMPOSE[@]}" exec -T trino trino --output-format CSV_UNQUOTED -f "$1"
}

row_count() {
  trino_sql 'SELECT count(*) FROM iceberg.sales.orders' | tail -n 1
}

"${COMPOSE[@]}" up -d --build

echo "waiting up to ${TIMEOUT}s for Trino ..."
deadline=$((SECONDS + TIMEOUT))
until trino_sql 'SELECT 1' >/dev/null 2>&1; do
  [ "$SECONDS" -lt "$deadline" ] || fail "Trino did not accept queries within ${TIMEOUT}s"
  sleep 5
done
echo "ok: Trino answers queries"

# --- the trap: a naive loader duplicates rows when it runs twice
trino_sql "CREATE SCHEMA IF NOT EXISTS iceberg.sales WITH (location = 's3://warehouse/sales')" >/dev/null
trino_sql 'DROP TABLE IF EXISTS iceberg.sales.orders' >/dev/null
trino_file /traps/load_naive.sql >/dev/null
trino_file /traps/load_naive.sql >/dev/null
naive="$(row_count)"
[ "$naive" = "20" ] || fail "trap not reproduced: naive loader run twice left ${naive} rows, expected 20"
echo "ok: trap reproduced, naive loader run twice left ${naive} rows"

# --- the fix: same table, idempotent loader, twice
trino_file /sample_data/load_sample_data.sql >/dev/null
trino_file /sample_data/load_sample_data.sql >/dev/null
fixed="$(row_count)"
[ "$fixed" = "10" ] || fail "idempotent loader run twice left ${fixed} rows, expected 10"
echo "ok: idempotent loader run twice left ${fixed} rows"

# --- the example queries return data
out="$(trino_file /sample_data/example_queries.sql)"
echo "$out" | grep -q '^audio,387.00,2$' || fail "revenue by category is missing 'audio,387.00,2'"
echo "$out" | grep -q '^CUST-01,' || fail "top customers query returned nothing"
echo "$out" | grep -q ',append$' || fail "no append snapshots in the Iceberg history"
echo "ok: example queries return the expected rows"

published="$("${COMPOSE[@]}" port trino 8080)"
case "$published" in
  127.0.0.1:*) echo "ok: Trino published on ${published}" ;;
  *) fail "Trino is published on ${published}, expected 127.0.0.1" ;;
esac

echo "SMOKE PASSED"
