#!/usr/bin/env bash
# Fail when any version ever set in pyproject.toml has no vX.Y.Z tag, or the tag's pyproject says otherwise.
# Needs full history and tags (actions/checkout with fetch-depth: 0). TAG_CHECK_REPO overrides the repo (tests).
set -euo pipefail
cd "${TAG_CHECK_REPO:-$(dirname "$0")/..}"
bad=0
py=$(sed -n 's/^version *= *"\(.*\)"/\1/p' pyproject.toml | head -1)
pkg=$(sed -n 's/^__version__ *= *"\(.*\)"/\1/p' src/publishing/__init__.py | head -1)
if [ "$py" != "$pkg" ]; then
  echo "VERSION MISMATCH: pyproject.toml says '$py', src/publishing/__init__.py says '$pkg'. Fix: make both the same version." >&2; bad=1
fi
for c in $(git log --format=%H --reverse -G'^version *=' -- pyproject.toml); do
  v=$(git show "$c:pyproject.toml" | sed -n 's/^version *= *"\(.*\)"/\1/p' | head -1)
  [ -n "$v" ] || continue
  if ! git rev-parse -q --verify "refs/tags/v$v^{commit}" >/dev/null; then
    echo "MISSING TAG: v$v (pyproject version bump in $(git rev-parse --short "$c") has no tag). Fix: run the release workflow (tools/release.sh; DRY_RUN=1 previews) or tag that commit v$v and push the tag" >&2; bad=1; continue
  fi
  tv=$(git show "v$v:pyproject.toml" | sed -n 's/^version *= *"\(.*\)"/\1/p' | head -1)
  [ "$tv" = "$v" ] || { echo "WRONG TAG: v$v has pyproject version '$tv'. Fix: retag v$v at the commit that bumped pyproject to $v" >&2; bad=1; }
done
[ "$bad" = 0 ] && echo "every pyproject version has its tag"
exit "$bad"
