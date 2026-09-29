#!/usr/bin/env bash
# One-shot bootstrap, runs inside the Elasticsearch image (it has bash and curl).
# Every call is idempotent (PUT/POST of the same content), so re-running is safe.
set -euo pipefail

ES="http://elasticsearch:9200"
AUTH=(-u "elastic:${ELASTIC_PASSWORD}")

call() {
  local method="$1" path="$2" body="$3"
  echo "-> ${method} ${path}"
  curl -sS --fail-with-body "${AUTH[@]}" -X "${method}" "${ES}${path}" \
    -H 'Content-Type: application/json' -d "${body}"
  echo
}

until curl -sf "${AUTH[@]}" "${ES}/_cluster/health?wait_for_status=yellow&timeout=5s" >/dev/null; do
  echo "waiting for Elasticsearch ..."
  sleep 2
done

# Retention: delete an index 7 days after it was created. Filebeat writes one index
# per day (app-logs-YYYY.MM.dd), so this keeps about a week of logs.
call PUT /_ilm/policy/app-logs-7d \
  '{"policy":{"phases":{"hot":{"actions":{}},"delete":{"min_age":"7d","actions":{"delete":{}}}}}}'

# Attach the policy to every app-logs-* index. One node, so no replicas (they would
# stay unassigned and keep the cluster yellow).
call PUT /_index_template/app-logs \
  '{"index_patterns":["app-logs-*"],"priority":200,"template":{"settings":{"index.lifecycle.name":"app-logs-7d","index.number_of_replicas":0}}}'

# Kibana connects as the built-in kibana_system user, which has no password until set.
call POST /_security/user/kibana_system/_password \
  "{\"password\":\"${KIBANA_PASSWORD}\"}"

# Filebeat gets its own user that can create indices and write documents into
# app-logs-*, and nothing else.
call PUT /_security/role/filebeat_writer \
  '{"cluster":["monitor","read_ilm"],"indices":[{"names":["app-logs-*"],"privileges":["create_index","create_doc","index","auto_configure","view_index_metadata"]}]}'
call PUT /_security/user/filebeat_writer \
  "{\"password\":\"${FILEBEAT_PASSWORD}\",\"roles\":[\"filebeat_writer\"]}"

echo "setup complete"
