#!/bin/sh
# Prove user-content mode inside a locked-down container (docs/user-content.md, "Containers").
#   tools/usercontent-check.sh            # builds publishing-usercontent-check:local, then runs it
# 1. Under Docker's default seccomp profile the sandbox cannot start, and the render must refuse.
# 2. Under the documented flags (non-root, every capability dropped, no-new-privileges, no network,
#    read-only root, ci/seccomp-chromium.json) the hostile-fixture tests must pass, those of
#    `html` and the build (test_usercontent.py) and of `render-html`/`render-md`/`pdf-pages`
#    (test_renderhtml.py).
set -eu
cd "$(dirname "$0")/.."
TAG=${TAG:-publishing-usercontent-check:local}
git ls-files -co --exclude-standard | tar -cf - -T - |
  docker build -q --label org.opencontainers.image.title=publishing-usercontent-check \
    -f tools/usercontent-check.Dockerfile -t "$TAG" - >/dev/null
LOCKED="--network none --cap-drop ALL --security-opt no-new-privileges --read-only --tmpfs /tmp
  --memory 2g --pids-limit 512"

echo "1. default seccomp profile: the render must refuse"
# shellcheck disable=SC2086
if out=$(docker run --rm $LOCKED "$TAG" sh -c \
    'mkdir /tmp/d && echo "<p>x</p>" > /tmp/d/i.html && publishing html /tmp/d/i.html -o /tmp/o.pdf' 2>&1); then
  echo "FAIL: rendered without a sandbox-capable profile: $out"; exit 1
fi
echo "$out" | grep -q "could not start its sandbox" || { echo "FAIL: unexpected error: $out"; exit 1; }
echo "   refused: $out"

echo "2. documented flags: the hostile fixtures"
# shellcheck disable=SC2086
docker run --rm $LOCKED --security-opt seccomp="$PWD/ci/seccomp-chromium.json" "$TAG" \
  python -m pytest -q -p no:cacheprovider tests/test_usercontent.py tests/test_renderhtml.py
