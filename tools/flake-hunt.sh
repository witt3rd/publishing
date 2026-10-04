#!/usr/bin/env bash
# Flake hunt: run the host test suite N times (default 5) in random-free but varied conditions and report any
# test that does not give the same result every time. usage: tools/flake-hunt.sh [N] [pytest args...]
# Profile-image goldens skip on the host; run this in each Dockerfile test stage for those.
set -uo pipefail
cd "$(dirname "$0")/.."
n=${1:-5}; shift || true
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
for i in $(seq "$n"); do
  uv run pytest -q -p no:cacheprovider -rA "$@" 2>&1 | grep -E '^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)' | sed -E 's/ - .*//' | sort > "$tmp/$i"
done
cat "$tmp"/* | sort | uniq -c | awk -v n="$n" '$1 != n' > "$tmp/unstable"
if [ -s "$tmp/unstable" ]; then
  echo "UNSTABLE (count of $n runs, outcome test):"; cat "$tmp/unstable"; exit 1
fi
echo "stable: $(wc -l < "$tmp/1") test outcomes identical across $n runs"
