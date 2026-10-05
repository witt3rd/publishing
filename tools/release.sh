#!/usr/bin/env bash
# Release the version at HEAD: require pyproject.toml and src/publishing/__init__.py to agree, then (when
# origin has no vX.Y.Z tag yet) tag the commit that bumped the version and create the GitHub release.
# Fails loudly on disagreement. Tag existence is read from origin (not the local clone); tools/tag-check.sh
# stays the audit of every past version, this script is the producer. Idempotent: a tagged version is a no-op.
#   DRY_RUN=1       print what would be tagged and released, change nothing
#   RELEASE_REPO    repo to run in (tests); RELEASE_REMOTE  remote name (default origin)
set -euo pipefail
cd "${RELEASE_REPO:-$(dirname "$0")/..}"
remote="${RELEASE_REMOTE:-origin}"
py=$(sed -n 's/^version *= *"\(.*\)"/\1/p' pyproject.toml | head -1)
pkg=$(sed -n 's/^__version__ *= *"\(.*\)"/\1/p' src/publishing/__init__.py | head -1)
if [ -z "$py" ] || [ "$py" != "$pkg" ]; then
  echo "::error::VERSION MISMATCH: pyproject.toml says '$py', src/publishing/__init__.py says '$pkg'" >&2
  exit 1
fi
tag="v$py"
if git ls-remote --exit-code --tags "$remote" "refs/tags/$tag" >/dev/null 2>&1; then
  echo "$tag already on $remote: nothing to release"; exit 0
fi
bump=$(git log -1 --format=%H -G'^version *=' -- pyproject.toml)
[ -n "$bump" ] || { echo "::error::no commit sets version in pyproject.toml" >&2; exit 1; }
bv=$(git show "$bump:pyproject.toml" | sed -n 's/^version *= *"\(.*\)"/\1/p' | head -1)
bp=$(git show "$bump:src/publishing/__init__.py" | sed -n 's/^__version__ *= *"\(.*\)"/\1/p' | head -1)
if [ "$bv" != "$py" ] || [ "$bp" != "$py" ]; then
  echo "::error::bump commit ${bump:0:7} has pyproject '$bv' and __version__ '$bp', wanted '$py'" >&2; exit 1
fi
if [ "${DRY_RUN:-}" = 1 ]; then
  echo "DRY RUN: would tag $tag at ${bump:0:7}, push to $remote, and create the GitHub release"; exit 0
fi
# An annotated tag needs a committer; the runner has none. Per-command, so no git config is written anywhere.
git -c user.name="github-actions[bot]" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
  tag -a "$tag" -m "publishing $py" "$bump"
git push "$remote" "refs/tags/$tag"
gh release create "$tag" --verify-tag --title "$tag" --generate-notes
echo "released $tag at ${bump:0:7}"
