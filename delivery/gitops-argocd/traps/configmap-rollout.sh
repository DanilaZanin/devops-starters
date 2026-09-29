#!/usr/bin/env bash
# Trap test: does changing a ConfigMap restart the pods that consume it?
#
#   broken chart = the fixed chart with the checksum/config annotation removed
#   fixed chart  = charts/demo-app as shipped
#
# Both are installed with APP_ENV=v1, upgraded to APP_ENV=v2, then inspected.
#   broken must end "stale":      same pod, old env value, ConfigMap already v2
#   fixed  must end "recreated":  new pod with the new env value
# Exit 0 only if both behave as described.
#
# Needs a reachable cluster in $KUBECONFIG (make test creates a kind cluster).
set -euo pipefail

cd "$(dirname "$0")/.."

readonly CHART=charts/demo-app
WORK=$(mktemp -d)
readonly WORK
readonly NAMESPACES=(trap-broken trap-fixed)

# shellcheck disable=SC2329  # invoked through the EXIT trap below
cleanup() {
  local ns
  for ns in "${NAMESPACES[@]}"; do
    helm uninstall "${ns#trap-}" -n "$ns" >/dev/null 2>&1 || true
    kubectl delete namespace "$ns" --wait=false >/dev/null 2>&1 || true
  done
  rm -rf "$WORK"
}
trap cleanup EXIT

# Build the broken chart from the fixed one so the two can never drift apart.
cp -r "$CHART" "$WORK/broken-chart"
sed -i.bak '/checksum\/config/d' "$WORK/broken-chart/templates/deployment.yaml"
rm -f "$WORK/broken-chart/templates/deployment.yaml.bak"
if grep -q 'checksum/config' "$WORK/broken-chart/templates/deployment.yaml"; then
  echo "cannot build the broken chart: checksum/config is still present" >&2
  exit 2
fi
if diff -q "$CHART/templates/deployment.yaml" "$WORK/broken-chart/templates/deployment.yaml" >/dev/null; then
  echo "cannot build the broken chart: the fixed chart has no checksum/config annotation" >&2
  exit 2
fi

# Names of pods that are not terminating, one per line.
live_pods() {
  local ns=$1 release=$2
  kubectl -n "$ns" get pods -l "app.kubernetes.io/instance=$release" \
    -o go-template='{{range .items}}{{if not .metadata.deletionTimestamp}}{{.metadata.name}}{{"\n"}}{{end}}{{end}}'
}

# Prints "recreated", "stale" or "unexpected: ..." for one chart.
run_case() {
  local release=$1 chart=$2
  local ns="trap-$release" deploy="$release-demo-app"
  local pod_before pod_after env_before env_after cm_value

  helm upgrade --install "$release" "$chart" -n "$ns" --create-namespace \
    --set env.APP_ENV=v1 --wait --timeout 180s >/dev/null
  pod_before=$(live_pods "$ns" "$release")
  env_before=$(kubectl -n "$ns" exec "$pod_before" -- printenv APP_ENV)

  helm upgrade "$release" "$chart" -n "$ns" \
    --set env.APP_ENV=v2 --wait --timeout 180s >/dev/null
  # Give a (wrongly) triggered rollout time to start, then wait for it to finish.
  sleep 10
  kubectl -n "$ns" rollout status "deploy/$deploy" --timeout=180s >/dev/null

  cm_value=$(kubectl -n "$ns" get configmap "$deploy-env" -o jsonpath='{.data.APP_ENV}')
  pod_after=$(live_pods "$ns" "$release")
  if [ "$(printf '%s\n' "$pod_after" | wc -l | tr -d ' ')" != 1 ]; then
    echo "unexpected: expected exactly one live pod, got: $pod_after"
    return
  fi
  env_after=$(kubectl -n "$ns" exec "$pod_after" -- printenv APP_ENV)

  if [ "$env_before" != v1 ] || [ "$cm_value" != v2 ]; then
    echo "unexpected: env_before=$env_before configmap_after=$cm_value"
  elif [ "$pod_after" != "$pod_before" ]; then
    if [ "$env_after" = v2 ]; then echo recreated; else echo "unexpected: new pod has env $env_after"; fi
  elif [ "$env_after" = v1 ]; then
    echo stale
  else
    echo "unexpected: same pod but env changed to $env_after"
  fi
}

status=0

echo ">> broken chart (no checksum/config): pods must NOT pick up the new ConfigMap value"
result=$(run_case broken "$WORK/broken-chart")
if [ "$result" = stale ]; then
  echo "OK: trap reproduced. ConfigMap is v2, the pod is unchanged and still has v1."
else
  echo "FAIL: broken chart result was '$result', expected 'stale'" >&2
  status=1
fi

echo ">> fixed chart (checksum/config): the pod must be recreated with the new value"
result=$(run_case fixed "$CHART")
if [ "$result" = recreated ]; then
  echo "OK: fixed chart recreated the pod with APP_ENV=v2."
else
  echo "FAIL: fixed chart result was '$result', expected 'recreated'" >&2
  status=1
fi

exit "$status"
