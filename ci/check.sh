#!/usr/bin/env bash
# Rebuild-check every PDF and MP4 under docs/ with the version docs/report.toml pins. The GitHub Action
# (action.yml) runs this; it also runs by hand in any repo checkout:  ci/check.sh [CONFIG]
#   PUBLISHING_DEPS  set to 0 where Chromium's OS libraries are already there or apt is not (a non-Debian box);
#                    the default installs them, which needs sudo and apt.
#   PUBLISHING_FROM  the pip/uv requirement to run instead of the pinned tag (tests, forks, a branch):
#                    a path, or git+https://... ; the pin in report.toml is then only read, not used.
# Needs uv on the PATH. With a video source it also installs ffmpeg (apt), as the runner image has none pinned.
set -euo pipefail
CONFIG=${1:-docs/report.toml}
[ -f "$CONFIG" ] || { echo "publishing check: $CONFIG not found" >&2; exit 2; }
DOCS=$(dirname "$CONFIG")
V=$(sed -n 's/^publishing *= *"\([^"]*\)".*/\1/p' "$CONFIG" | head -n1)
[ -n "$V" ] || [ -n "${PUBLISHING_FROM:-}" ] || { echo "publishing check: no publishing = \"X.Y.Z\" pin in $CONFIG" >&2; exit 2; }
if find "$DOCS" -name video.html | grep -q .; then EXTRA=video; else EXTRA=render; fi
DEPS=(); [ "${PUBLISHING_DEPS:-1}" = 0 ] || DEPS=(--with-deps)
SRC=${PUBLISHING_FROM:-git+https://github.com/witt3rd/publishing@v$V}
P=(uvx --from "publishing[$EXTRA] @ $SRC" publishing)
if [ "$EXTRA" = video ]; then
  command -v ffmpeg >/dev/null || { sudo apt-get update && sudo apt-get install -y --no-install-recommends ffmpeg; }
  "${P[@]}" setup "${DEPS[@]}" --video
else
  "${P[@]}" setup "${DEPS[@]}"
fi
exec "${P[@]}" check
