#!/usr/bin/env bash
# Prove ci/check.sh (what action.yml runs) on a scratch repo, never a real one:
#   PUBLISHING_FROM=$PWD tools/action-check.sh      # PUBLISHING_DEPS=0 where Chromium's libraries are present
# 1. a document with no committed PDF fails; 2. after `publishing build` it passes; 3. after the source
# changes without a rebuild it fails as stale.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
export PUBLISHING_FROM=${PUBLISHING_FROM:-$ROOT}
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -n1)
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
cd "$W"; git init -q
mkdir -p docs/memos/doc-v1
cp "$ROOT/docs/samples/house-style-document-v1/document.md" docs/memos/doc-v1/
printf 'publishing = "%s"\nproject = "Scratch"\n' "$VERSION" > docs/report.toml
run() { "$ROOT/ci/check.sh" "$@" 2>&1; }

echo "1. no PDF: must fail"
if out=$(run); then echo "FAIL: passed with no PDF"; exit 1; fi
echo "$out" | grep -q "missing" || { echo "FAIL: $out"; exit 1; }
echo "2. built: must pass"
uvx --from "publishing[render] @ $PUBLISHING_FROM" publishing build >/dev/null
run | tail -n1
echo "3. source changed, PDF not rebuilt: must fail"
sed -i 's/## Purpose/## Aim/' docs/memos/doc-v1/document.md
if out=$(run); then echo "FAIL: passed with a stale PDF"; exit 1; fi
echo "$out" | grep -q "stale" || { echo "FAIL: $out"; exit 1; }
echo "4. no pin: must fail with exit 2"
unset PUBLISHING_FROM
printf 'project = "Scratch"\n' > docs/report.toml
rc=0; "$ROOT/ci/check.sh" >/dev/null 2>&1 || rc=$?
[ "$rc" = 2 ] || { echo "FAIL: exit $rc"; exit 1; }
echo ok
