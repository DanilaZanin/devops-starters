#!/usr/bin/env bash
# Point every ArgoCD manifest at your own git repo in one step.
#   scripts/set-repo-url.sh https://github.com/you/your-repo.git
# Replaces the placeholder (or the previous URL) in bootstrap/ and apps/.
set -euo pipefail

if [ $# -ne 1 ] || [ -z "$1" ]; then
  echo "usage: $0 <git-repo-url>" >&2
  exit 2
fi

cd "$(dirname "$0")/.."
new_url=$1

# Current URL: the single distinct repoURL value across the manifests.
current=$(grep -rhE '^[[:space:]]*repoURL:' apps bootstrap | sed -E 's/^[[:space:]]*repoURL:[[:space:]]*//' | sort -u)
count=$(printf '%s\n' "$current" | grep -c . || true)
if [ "$count" -ne 1 ]; then
  echo "expected exactly one distinct repoURL, found $count:" >&2
  printf '%s\n' "$current" >&2
  exit 1
fi
old_url=$current

# AppProject sourceRepos entries are list items ("- <url>"), so replace by value.
files=$(grep -rlF "$old_url" apps bootstrap)
for f in $files; do
  OLD="$old_url" NEW="$new_url" perl -0pi -e 's/\Q$ENV{OLD}\E/$ENV{NEW}/g' "$f"
done
echo "repo URL: $old_url -> $new_url"
echo "files updated:"
printf '%s\n' "$files" | sed 's/^/  /'
