#!/usr/bin/env bash
# Fails if a PDF or MP4 is committed outside docs/ (where `publishing check` covers it)
# unless it sits under a declared test-input folder.
set -euo pipefail
cd "$(dirname "$0")/.."
allowed=(tests/fixtures/ tests/golden/inputs/)
bad=()
while IFS= read -r f; do
  case "$f" in docs/*) continue ;; esac
  ok=0
  for a in "${allowed[@]}"; do case "$f" in "$a"*) ok=1 ;; esac; done
  [ "$ok" = 1 ] || bad+=("$f")
done < <(git ls-files -z | tr '\0' '\n' | grep -Ei '\.(pdf|mp4)$' | grep -v '^Dockerfile\.' || true)
if [ "${#bad[@]}" -gt 0 ]; then
  echo "PDF/MP4 committed outside docs/ and the test-input folders (${allowed[*]}):" >&2
  printf '  %s\n' "${bad[@]}" >&2
  exit 1
fi
echo "ok: no PDF or MP4 outside docs/ or the test-input folders"
