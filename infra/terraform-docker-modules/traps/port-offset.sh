#!/usr/bin/env bash
# Trap test: replicas of the compute module must not publish the same host port.
#
#   broken module = modules/compute with the per-replica port offset removed
#   fixed module  = modules/compute as shipped (covered by `make unit`)
#
# The broken copy is built by editing the shipped source, so the two cannot
# drift apart. The shipped module's own tests (modules/compute/tests) are run
# against the broken copy and must FAIL on the "distinct host ports" assertion.
set -euo pipefail

cd "$(dirname "$0")/.."

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

broken="$work/compute-broken"
cp -r modules/compute "$broken"
rm -rf "$broken/.terraform" "$broken/.terraform.lock.hcl"

sed -i.bak 's/external = r\.external + i$/external = r.external/' "$broken/main.tf"
rm -f "$broken/main.tf.bak"
if diff -q modules/compute/main.tf "$broken/main.tf" >/dev/null; then
  echo "cannot build the broken module: the offset line was not found in modules/compute/main.tf" >&2
  exit 2
fi

terraform -chdir="$broken" init -backend=false -input=false >/dev/null

if terraform -chdir="$broken" test >"$work/out.txt" 2>&1; then
  cat "$work/out.txt"
  echo "TRAP NOT REPRODUCED: the module without the port offset passed its tests" >&2
  exit 1
fi

if ! grep -q 'replicas must publish distinct host ports' "$work/out.txt"; then
  cat "$work/out.txt"
  echo "the broken module failed, but not on the distinct-host-ports assertion" >&2
  exit 1
fi

echo "OK: without the offset, terraform test fails on 'replicas must publish distinct host ports'."
