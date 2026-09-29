#!/usr/bin/env bash
# End-to-end test for Vault Agent injection on a Kubernetes cluster in $KUBECONFIG
# (make test creates a throwaway kind cluster).
#
#   1. install dev-mode Vault + injector (pinned chart)
#   2. write a random secret, enable Kubernetes auth, create the role
#   3. TRAP: apply the broken policy (KV v1-style path) and deploy the app.
#      The injected init container must be denied and the app must not start.
#   4. FIX: apply the real policy and recreate the pod. The app must start and
#      report the SHA-256 of the random secret, which this script recomputes.
set -euo pipefail

cd "$(dirname "$0")/.."

set -a
# shellcheck source=/dev/null
. ./.env
set +a
: "${VAULT_DEV_ROOT_TOKEN:?set in .env}"
: "${VAULT_CHART_VERSION:?set in .env}"

vault_exec() {
  kubectl -n vault exec vault-0 -- env VAULT_TOKEN="$VAULT_DEV_ROOT_TOKEN" "$@"
}

# Same, but forwards stdin (used to feed a policy file to `vault policy write -`).
vault_exec_stdin() {
  kubectl -n vault exec -i vault-0 -- env VAULT_TOKEN="$VAULT_DEV_ROOT_TOKEN" "$@"
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$1" | sha256sum | cut -d' ' -f1
  else
    printf '%s' "$1" | shasum -a 256 | cut -d' ' -f1
  fi
}

app_ready() {
  [ "$(kubectl -n demo-app get pods -l app=demo-app \
    -o jsonpath='{.items[0].status.containerStatuses[?(@.name=="demo-app")].ready}' 2>/dev/null)" = true ]
}

echo ">> install Vault (dev mode) and the injector, chart $VAULT_CHART_VERSION"
helm upgrade --install vault vault --repo https://helm.releases.hashicorp.com \
  --version "$VAULT_CHART_VERSION" -n vault --create-namespace \
  -f manifests/vault-values.yaml --set server.dev.devRootToken="$VAULT_DEV_ROOT_TOKEN" \
  --wait --timeout 300s >/dev/null
# helm 4 can return from --wait before the StatefulSet pod is ready; wait explicitly.
kubectl -n vault wait --for=condition=Ready pod/vault-0 --timeout=300s >/dev/null
kubectl -n vault rollout status deploy/vault-agent-injector --timeout=300s >/dev/null
echo "images in use:"
kubectl -n vault get pods -o jsonpath='{range .items[*]}{range .spec.containers[*]}  {.image}{"\n"}{end}{end}' | sort -u

echo ">> write a random secret and configure Kubernetes auth"
db_password=$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')
api_key=$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')
vault_exec vault kv put secret/demo-app db_password="$db_password" api_key="$api_key" >/dev/null
if ! vault_exec vault auth list | grep -q '^kubernetes/'; then
  vault_exec vault auth enable kubernetes >/dev/null
fi
# The single quotes are intentional: $KUBERNETES_* must expand inside the Vault pod.
# shellcheck disable=SC2016
vault_exec sh -c 'vault write auth/kubernetes/config kubernetes_host="https://$KUBERNETES_SERVICE_HOST:$KUBERNETES_SERVICE_PORT"' >/dev/null
vault_exec vault write auth/kubernetes/role/demo-app \
  bound_service_account_names=demo-app bound_service_account_namespaces=demo-app \
  token_policies=demo-app token_ttl=1h >/dev/null

echo ">> TRAP: broken policy (secret/demo-app instead of secret/data/demo-app)"
vault_exec_stdin vault policy write demo-app - <traps/broken-policy.hcl >/dev/null
kubectl apply -f manifests/serviceaccount.yaml >/dev/null
kubectl apply -f manifests/app.yaml >/dev/null

denied=0
deadline=$((SECONDS + 150))
while [ "$SECONDS" -lt "$deadline" ]; do
  logs=$(kubectl -n demo-app logs deploy/demo-app -c vault-agent-init 2>&1 || true)
  if printf '%s' "$logs" | grep -Eqi 'permission denied|code: 403'; then
    denied=1
    break
  fi
  sleep 3
done
if [ "$denied" != 1 ]; then
  echo "FAIL: the injector init container was never denied; trap not reproduced" >&2
  kubectl -n demo-app describe pods >&2 || true
  exit 1
fi
if app_ready; then
  echo "FAIL: the app became ready with the broken policy" >&2
  exit 1
fi
echo "OK: trap reproduced. vault-agent-init got permission denied and the app is not running."

echo ">> FIX: policy on secret/data/demo-app, recreate the pod"
vault_exec_stdin vault policy write demo-app - <policies/demo-app-policy.hcl >/dev/null
kubectl -n demo-app delete pod -l app=demo-app --wait=true >/dev/null
kubectl -n demo-app rollout status deploy/demo-app --timeout=180s >/dev/null

echo ">> the app must report the hash of the secret it read from /vault/secrets"
response=$(kubectl -n demo-app exec deploy/demo-app -c demo-app -- \
  python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8080/").read().decode())')
expected=$(sha256_of "$db_password")
if ! printf '%s' "$response" | grep -q "\"db_password_sha256\": \"$expected\""; then
  echo "FAIL: the app did not report the expected hash of DB_PASSWORD" >&2
  echo "response: $response" >&2
  exit 1
fi
if printf '%s' "$response" | grep -qF "$db_password"; then
  echo "FAIL: the raw secret leaked in the response" >&2
  exit 1
fi
echo "OK: the app read the secret from /vault/secrets and reported its SHA-256."

echo ">> the Deployment spec itself must contain no secret value"
if kubectl -n demo-app get deploy demo-app -o yaml | grep -qF "$db_password"; then
  echo "FAIL: the secret value appears in the Deployment" >&2
  exit 1
fi
echo "OK: no secret value in the Deployment."
