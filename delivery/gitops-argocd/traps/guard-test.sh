#!/usr/bin/env bash
# Guard for the trap script itself: a failure that has nothing to do with the
# ConfigMap (here: helm exits 42) must NOT be scored as "broken chart is stale".
# Uses stub helm/kubectl on PATH, so it needs no cluster.
set -euo pipefail
cd "$(dirname "$0")/.."

stubs=$(mktemp -d)
trap 'rm -rf "$stubs"' EXIT

cat >"$stubs/helm" <<'STUB'
#!/bin/sh
exit 42
STUB
# kubectl answers exactly as a healthy cluster with a stale pod would.
cat >"$stubs/kubectl" <<'STUB'
#!/bin/sh
case "$*" in
  *"get configmap"*) printf v2 ;;
  *"get pods"*) echo pod-a ;;
  *printenv*) echo v1 ;;
esac
exit 0
STUB
chmod +x "$stubs/helm" "$stubs/kubectl"

rc=0
TRAP_SETTLE_SECONDS=0 PATH="$stubs:$PATH" ./traps/configmap-rollout.sh >"$stubs/out" 2>&1 || rc=$?
if [ "$rc" -eq 0 ]; then
  cat "$stubs/out"
  echo "GUARD FAILED: helm failed with 42 but the trap test still passed" >&2
  exit 1
fi
if grep -q "result was 'stale'" "$stubs/out"; then
  cat "$stubs/out"
  echo "GUARD FAILED: an unrelated helm failure was scored as 'stale'" >&2
  exit 1
fi
echo "OK: an unrelated helm failure fails the trap test and is not scored as 'stale'"
