#!/usr/bin/env bash
# The smoke test's teardown must not swallow errors: with a `docker` that fails on
# every call, the script (stopped right after the trap is set) has to exit non-zero
# and say which cleanup step failed.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
bin="$(mktemp -d)"
trap 'rm -rf "$bin"' EXIT
printf '#!/bin/sh\nexit 1\n' >"$bin/docker"
chmod +x "$bin/docker"
out="$(PATH="$bin:$PATH" SMOKE_CLEANUP_SELFTEST=1 bash tests/smoke.sh 2>&1)"
status=$?
[ "$status" -ne 0 ] || { echo "cleanup selftest FAILED: exit 0 although every docker cleanup command failed"; exit 1; }
for step in "rm -f" "compose down" "compose build"; do
  grep -q "SMOKE CLEANUP FAILED: docker ${step}" <<<"$out" || { echo "cleanup selftest FAILED: no report for '${step}'"; echo "$out"; exit 1; }
done
echo "ok: a failing teardown makes the smoke test exit ${status} and names every failed step"
