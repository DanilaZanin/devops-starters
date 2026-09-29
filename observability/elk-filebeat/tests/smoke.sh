#!/usr/bin/env bash
# Smoke test for the opt-in log pipeline, with one trap in it:
#   fixed config : the labeled container's logs arrive, the unlabeled container's do not;
#   broken config: (traps/filebeat.collect-all.yml) the unlabeled logs DO arrive,
#                  which proves the check above can actually fail.
#
# Isolation: it starts from a clean slate (this module's containers and volumes are
# deleted first) and, when it exits for any reason, deletes them again, so no test
# document stays in the index. The broken config ships only containers of this compose
# project (see the drop_event processor in it), never other containers on the host; a
# stranger container that logs a marker line proves that.
set -euo pipefail

cd "$(dirname "$0")/.."
TIMEOUT="${SMOKE_TIMEOUT:-420}"
COMPOSE=(docker compose)
ES_URL="http://127.0.0.1:9200"
RUN_ID="smoke$(date +%s)$$"
FOREIGN="elk-filebeat-foreign-${RUN_ID}"

# shellcheck source=/dev/null
set -a && . ./.env && set +a

fail() {
  echo "SMOKE FAILED: $*" >&2
  "${COMPOSE[@]}" ps >&2 || true
  "${COMPOSE[@]}" logs --tail 30 setup filebeat elasticsearch docker-proxy >&2 || true
  exit 1
}

cleanup() {
  local status=$?
  trap - EXIT
  docker rm -f "$FOREIGN" >/dev/null 2>&1 || true
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  # The filebeat image tag holds the broken config after the trap phase; put the real one back.
  "${COMPOSE[@]}" build filebeat >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT

# Any HTTP error (4xx/5xx) or connection failure makes curl, and so the caller, fail.
es() {
  curl -sS --fail -u "elastic:${ELASTIC_PASSWORD}" "$@"
}

# Prints the number of indexed documents whose message contains the phrase. Fails (exit
# status 1) when Elasticsearch answers with an error, is unreachable, or the reply has
# no integer "count": "no answer" must never be read as "zero documents".
count_messages() {
  es -X POST "${ES_URL}/app-logs-*/_count?ignore_unavailable=true" \
    -H 'Content-Type: application/json' \
    -d "{\"query\":{\"match_phrase\":{\"message\":\"$1\"}}}" \
    | python3 -c 'import json, sys
count = json.load(sys.stdin)["count"]
assert isinstance(count, int), count
print(count)'
}

# Like count_messages, but says why the test stops. Call it as `n="$(strict_count ...)"`
# so that its failure ends the script (set -e).
strict_count() {
  count_messages "$1" || { echo "SMOKE FAILED: could not count documents for '$1' (Elasticsearch error or malformed reply)" >&2; exit 1; }
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

has_documents() { [ "$(count_messages "$1" 2>/dev/null)" -gt 0 ] 2>/dev/null; }
es_is_up() { es -o /dev/null "${ES_URL}/_cluster/health" 2>/dev/null; }
ilm_policy_exists() { es -o /dev/null "${ES_URL}/_ilm/policy/app-logs-7d" 2>/dev/null; }

# --- the helpers must fail loudly: nothing is listening yet, so a count must be an error, not 0
if (ES_URL="http://127.0.0.1:1" count_messages "anything") >/dev/null 2>&1; then
  fail "count_messages returned success although Elasticsearch is unreachable"
fi
echo "ok: count_messages fails when Elasticsearch cannot be reached"

"${COMPOSE[@]}" down -v --remove-orphans
"${COMPOSE[@]}" up -d --build

wait_for "Elasticsearch answers with credentials" "$TIMEOUT" es_is_up || fail "Elasticsearch never came up"

anonymous="$(curl -s -o /dev/null -w '%{http_code}' "${ES_URL}/")"
[ "$anonymous" = "401" ] || fail "anonymous request returned ${anonymous}, expected 401 (security is off?)"
echo "ok: anonymous access is rejected (401)"

if (ELASTIC_PASSWORD="wrong-${RUN_ID}" count_messages "anything") >/dev/null 2>&1; then
  fail "count_messages returned success on a 401 reply"
fi
echo "ok: count_messages fails on an HTTP 401"

wait_for "setup service created the ILM policy" "$TIMEOUT" ilm_policy_exists || fail "ILM policy was never created"
es "${ES_URL}/_ilm/policy/app-logs-7d" \
  | python3 -c 'import json, sys
policy = json.load(sys.stdin)["app-logs-7d"]["policy"]["phases"]
assert policy["delete"]["min_age"] == "7d", policy' \
  || fail "ILM policy does not delete after 7d"
echo "ok: retention is 7d"

# --- Filebeat has no Docker socket, only the read-only proxy
mounts="$(docker inspect -f '{{range .Mounts}}{{.Source}} {{end}}' "$("${COMPOSE[@]}" ps -q filebeat)")"
case "$mounts" in
  *docker.sock*) fail "the filebeat container mounts the Docker socket: ${mounts}" ;;
esac
echo "ok: the filebeat container has no Docker socket"

proxy_healthy() { [ "$(docker inspect -f '{{.State.Health.Status}}' "$("${COMPOSE[@]}" ps -q docker-proxy)")" = healthy ]; }
wait_for "docker-proxy is healthy" "$TIMEOUT" proxy_healthy || fail "docker-proxy never became healthy"
proxy_status() {  # METHOD PATH -> HTTP status, asked from the proxy's own internal network
  docker run --rm --network "elk-filebeat_docker-api" --entrypoint curl \
    docker.elastic.co/elasticsearch/elasticsearch:9.5.4 \
    -s -o /dev/null -w '%{http_code}' -X "$1" "http://docker-proxy:2375$2"
}
[ "$(proxy_status GET /containers/json)" = "200" ] || fail "docker-proxy does not answer GET /containers/json"
for denied in "POST /containers/create" "POST /containers/x/kill" "GET /images/json" "GET /volumes"; do
  # shellcheck disable=SC2086
  [ "$(proxy_status $denied)" = "403" ] || fail "docker-proxy allowed: ${denied}"
done
echo "ok: docker-proxy allows read-only container/event queries and refuses writes and other APIs"

# A container outside this compose project that logs a marker: it must never reach Elasticsearch.
docker run -d --name "$FOREIGN" --network none busybox:1.37.0 \
  sh -c "while true; do echo 'foreign log line ${RUN_ID}'; sleep 1; done" >/dev/null

# --- fixed config: labeled logs arrive, unlabeled logs do not
wait_for "logs of the labeled container reach Elasticsearch" "$TIMEOUT" has_documents "demo log line" \
  || fail "no 'demo log line' documents: Filebeat is not shipping the labeled container"
sleep 15  # give a leaking config time to show itself
quiet="$(strict_count 'quiet log line')"
[ "$quiet" = "0" ] || fail "logs of the UNLABELED container were collected: opt-in is broken"
foreign="$(strict_count "foreign log line ${RUN_ID}")"
[ "$foreign" = "0" ] || fail "logs of a container outside this compose project were collected"
echo "ok: the unlabeled container's logs were not collected"

# --- broken config: the same check must now fail
echo "switching Filebeat to the collect-all config ..."
FILEBEAT_CONFIG=traps/filebeat.collect-all.yml "${COMPOSE[@]}" up -d --build --force-recreate filebeat
wait_for "trap reproduced: the collect-all config ships the unlabeled logs" 180 has_documents "quiet log line" \
  || fail "trap not reproduced: the broken config did not collect the unlabeled container"
sleep 10
foreign="$(strict_count "foreign log line ${RUN_ID}")"
[ "$foreign" = "0" ] || fail "the broken config shipped a container outside this compose project: the test is not isolated"
echo "ok: even the broken config never shipped the foreign container's logs"

echo "restoring the real config ..."
"${COMPOSE[@]}" up -d --build --force-recreate filebeat

wait_for "Kibana is up" "$TIMEOUT" "${COMPOSE[@]}" exec -T kibana sh -c "curl -s -I http://localhost:5601 | grep -q 'HTTP/1.1 302 Found'" \
  || fail "Kibana did not come up"

echo "SMOKE PASSED"
