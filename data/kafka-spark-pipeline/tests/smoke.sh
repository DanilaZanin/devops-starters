#!/usr/bin/env bash
# End-to-end smoke test: producer -> Kafka -> Spark -> Postgres.
# Brings the stack up (if it is not already) and waits until aggregated rows show up.
set -euo pipefail

cd "$(dirname "$0")/.."
TIMEOUT="${SMOKE_TIMEOUT:-420}"
COMPOSE=(docker compose)

# shellcheck source=/dev/null
set -a && . ./.env && set +a

query() {
  "${COMPOSE[@]}" exec -T postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -tAc "$1"
}

fail() {
  echo "SMOKE FAILED: $*" >&2
  "${COMPOSE[@]}" ps >&2 || true
  "${COMPOSE[@]}" logs --tail 40 producer spark-job >&2 || true
  exit 1
}

"${COMPOSE[@]}" up -d --build

echo "waiting up to ${TIMEOUT}s for rows in product_revenue_by_window ..."
deadline=$((SECONDS + TIMEOUT))
rows=0
while [ "$SECONDS" -lt "$deadline" ]; do
  rows="$(query 'SELECT count(*) FROM product_revenue_by_window' 2>/dev/null || echo 0)"
  [ "${rows:-0}" -gt 0 ] && break
  sleep 5
done
[ "${rows:-0}" -gt 0 ] || fail "no rows reached Postgres within ${TIMEOUT}s"
echo "ok: ${rows} aggregated rows in Postgres"

orders="$(query 'SELECT coalesce(sum(orders_count), 0) FROM product_revenue_by_window')"
[ "${orders}" -gt 0 ] || fail "rows exist but sum(orders_count) is 0"
echo "ok: ${orders} orders aggregated"

"${COMPOSE[@]}" logs producer | grep -q 'delivered' || fail "producer never reported a delivered event"
echo "ok: producer got delivery confirmations"

published="$("${COMPOSE[@]}" port kafka 29092)"
case "${published}" in
  127.0.0.1:*) echo "ok: external listener published on ${published}" ;;
  *) fail "external listener is published on ${published}, expected 127.0.0.1" ;;
esac

# The checkpoint directory must exist on the volume, otherwise a restart replays everything.
"${COMPOSE[@]}" exec -T spark-job ls /checkpoints/orders | grep -q offsets \
  || fail "no Spark checkpoint found in /checkpoints/orders"
echo "ok: checkpoint is on the volume"

echo "SMOKE PASSED"
