#!/usr/bin/env bash
# Smoke test for the opt-in log pipeline, with one trap in it:
#   fixed config : the labeled container's logs arrive, the unlabeled container's do not;
#   broken config: (traps/filebeat.collect-all.yml) the unlabeled logs DO arrive,
#                  which proves the check above can actually fail.
# Starts from a clean slate: it deletes this module's containers and volumes first.
set -euo pipefail

cd "$(dirname "$0")/.."
TIMEOUT="${SMOKE_TIMEOUT:-420}"
COMPOSE=(docker compose)
ES_URL="http://127.0.0.1:9200"

# shellcheck source=/dev/null
set -a && . ./.env && set +a

fail() {
  echo "SMOKE FAILED: $*" >&2
  "${COMPOSE[@]}" ps >&2 || true
  "${COMPOSE[@]}" logs --tail 30 setup filebeat elasticsearch >&2 || true
  exit 1
}

es() {
  curl -sS -u "elastic:${ELASTIC_PASSWORD}" "$@"
}

# Number of indexed documents whose message contains the phrase (0 if the index is not there yet).
count_messages() {
  es -X POST "${ES_URL}/app-logs-*/_count?ignore_unavailable=true" \
    -H 'Content-Type: application/json' \
    -d "{\"query\":{\"match_phrase\":{\"message\":\"$1\"}}}" 2>/dev/null \
    | python3 -c 'import json, sys
try:
    print(json.load(sys.stdin).get("count", 0))
except ValueError:
    print(0)'
}

wait_for() {
  local description="$1" limit="$2"
  shift 2
  local deadline=$((SECONDS + limit))
  until "$@"; do
    [ "$SECONDS" -lt "$deadline" ] || return 1
    sleep 5
  done
  echo "ok: ${description}"
}

has_documents() { [ "$(count_messages "$1")" -gt 0 ]; }
es_is_up() { es -f -o /dev/null "${ES_URL}/_cluster/health" 2>/dev/null; }
ilm_policy_exists() { es -f -o /dev/null "${ES_URL}/_ilm/policy/app-logs-7d" 2>/dev/null; }

"${COMPOSE[@]}" down -v --remove-orphans
"${COMPOSE[@]}" up -d --build

wait_for "Elasticsearch answers with credentials" "$TIMEOUT" es_is_up || fail "Elasticsearch never came up"

anonymous="$(curl -s -o /dev/null -w '%{http_code}' "${ES_URL}/")"
[ "$anonymous" = "401" ] || fail "anonymous request returned ${anonymous}, expected 401 (security is off?)"
echo "ok: anonymous access is rejected (401)"

wait_for "setup service created the ILM policy" "$TIMEOUT" ilm_policy_exists || fail "ILM policy was never created"
es "${ES_URL}/_ilm/policy/app-logs-7d" \
  | python3 -c 'import json, sys
policy = json.load(sys.stdin)["app-logs-7d"]["policy"]["phases"]
assert policy["delete"]["min_age"] == "7d", policy' \
  || fail "ILM policy does not delete after 7d"
echo "ok: retention is 7d"

# --- fixed config: labeled logs arrive, unlabeled logs do not
wait_for "logs of the labeled container reach Elasticsearch" "$TIMEOUT" has_documents "demo log line" \
  || fail "no 'demo log line' documents: Filebeat is not shipping the labeled container"
sleep 15  # give a leaking config time to show itself
[ "$(count_messages 'quiet log line')" = "0" ] \
  || fail "logs of the UNLABELED container were collected: opt-in is broken"
echo "ok: the unlabeled container's logs were not collected"

# --- broken config: the same check must now fail
echo "switching Filebeat to the collect-all config ..."
FILEBEAT_CONFIG=traps/filebeat.collect-all.yml "${COMPOSE[@]}" up -d --build --force-recreate filebeat
wait_for "trap reproduced: the collect-all config ships the unlabeled logs" 180 has_documents "quiet log line" \
  || fail "trap not reproduced: the broken config did not collect the unlabeled container"

echo "restoring the real config ..."
"${COMPOSE[@]}" up -d --build --force-recreate filebeat

wait_for "Kibana is up" "$TIMEOUT" "${COMPOSE[@]}" exec -T kibana sh -c "curl -s -I http://localhost:5601 | grep -q 'HTTP/1.1 302 Found'" \
  || fail "Kibana did not come up"

echo "SMOKE PASSED"
