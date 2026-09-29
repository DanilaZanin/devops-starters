#!/usr/bin/env bash
# End-to-end smoke test: producer -> Kafka -> Spark -> Postgres.
#
# Starts from clean volumes (this module's containers and data are deleted first), so
# rows and logs left by an earlier run cannot satisfy any check. It also injects three
# malformed events followed by one marked good event and requires that the marked event
# still arrives (the stream survived) and the bad ones land in dead_letter_events.
set -euo pipefail

cd "$(dirname "$0")/.."
TIMEOUT="${SMOKE_TIMEOUT:-420}"
COMPOSE=(docker compose)
RUN_ID="smoke$(date +%s)$$"

# shellcheck source=/dev/null
set -a && . ./.env && set +a

query() {
  "${COMPOSE[@]}" exec -T postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -tAc "$1"
}

fail() {
  echo "SMOKE FAILED: $*" >&2
  "${COMPOSE[@]}" ps >&2 || true
  "${COMPOSE[@]}" logs --tail 60 producer spark-job >&2 || true
  exit 1
}

# wait_for DESCRIPTION COMMAND...: poll until COMMAND succeeds or the deadline passes.
wait_for() {
  local what="$1"; shift
  local deadline=$((SECONDS + TIMEOUT))
  echo "waiting up to ${TIMEOUT}s for ${what} ..."
  while [ "$SECONDS" -lt "$deadline" ]; do
    if "$@" 2>/dev/null; then echo "ok: ${what}"; return 0; fi
    sleep 5
  done
  fail "${what} (not seen within ${TIMEOUT}s)"
}

producer_acked() { "${COMPOSE[@]}" logs producer | grep -q 'first delivery confirmed'; }
count_at_least() { [ "$(query "$1")" -ge "$2" ]; }

"${COMPOSE[@]}" down -v --remove-orphans
"${COMPOSE[@]}" up -d --build

wait_for "the producer's first delivery confirmation" producer_acked
wait_for "aggregated rows in Postgres" count_at_least 'SELECT count(*) FROM product_revenue_by_window' 1

orders="$(query 'SELECT coalesce(sum(orders_count), 0) FROM product_revenue_by_window')"
[ "${orders}" -gt 0 ] || fail "rows exist but sum(orders_count) is 0"
echo "ok: ${orders} orders aggregated"

# Malformed events: not JSON, no product, no event time. Then one good event carrying a
# marker product, sent after them.
now="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"
{
  echo "this is not json ${RUN_ID}"
  echo "{\"order_id\": \"${RUN_ID}-no-product\", \"price\": 10.0, \"quantity\": 1, \"ts\": \"${now}\"}"
  echo "{\"order_id\": \"${RUN_ID}-no-ts\", \"product\": \"${RUN_ID}-bad\", \"price\": 10.0, \"quantity\": 1}"
  echo "{\"order_id\": \"${RUN_ID}-good\", \"product\": \"${RUN_ID}-good\", \"price\": 10.0, \"quantity\": 2, \"ts\": \"${now}\"}"
} | "${COMPOSE[@]}" exec -T kafka /opt/kafka/bin/kafka-console-producer.sh \
      --bootstrap-server kafka:9092 --topic orders >/dev/null
echo "injected 3 malformed events and 1 marked good event (${RUN_ID})"

wait_for "the marked good event aggregated after the bad ones" \
  count_at_least "SELECT count(*) FROM product_revenue_by_window WHERE product = '${RUN_ID}-good'" 1
wait_for "the 3 malformed events in dead_letter_events" \
  count_at_least "SELECT count(*) FROM dead_letter_events WHERE raw_value LIKE '%${RUN_ID}%' AND raw_value NOT LIKE '%-good%'" 3

restarts="$(docker inspect -f '{{.RestartCount}}' "$("${COMPOSE[@]}" ps -q spark-job)")"
[ "${restarts}" = "0" ] || fail "spark-job restarted ${restarts} times"
echo "ok: the Spark job never restarted"

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
