#!/usr/bin/env bash
# Run one `publishing` command the way a service should: from the pinned image, no network, non-root,
# read-only root, the current directory mounted at /work. Paths in ARGS are relative to it.
#
#   examples/service/run.sh convert notes.md -o notes.html
#   examples/service/run.sh extract report.pdf
#   examples/service/run.sh render-html page.html --pdf page.pdf --png pages --thumbnail 320 --json
#
# PUBLISHING_IMAGE   the toolbox image (default publishing:0.12.0; build it first, see docs/service.md)
# PUBLISHING_BIN     run this local `publishing` instead of Docker (development; same exit codes)
# SECCOMP            the Chromium seccomp profile for render commands (default: ci/seccomp-chromium.json
#                    in this repo; copy it next to your deployment)
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ $# -ge 1 ] || { echo "usage: run.sh COMMAND [ARGS...]" >&2; exit 2; }

if [ -n "${PUBLISHING_BIN:-}" ]; then
  exec "$PUBLISHING_BIN" "$@"
fi

image="${PUBLISHING_IMAGE:-publishing:0.12.0}"
flags=(--rm --network none --user "$(id -u):$(id -g)" --cap-drop ALL
       --security-opt no-new-privileges --read-only --tmpfs /tmp
       --memory 2g --pids-limit 512 -v "$PWD:/work")

case "$1" in
  # Chromium's sandbox needs unprivileged user namespaces: Docker's default seccomp profile
  # refuses them, so these commands take the one-rule profile (docs/user-content.md "Containers").
  # `build` and `check` (your own decks, memos, videos) are not here: user-content mode refuses decks and
  # videos, so they run trusted, in the same locked-down container.
  html|render-html|render-md|pdf-pages)
    flags+=(--security-opt "seccomp=${SECCOMP:-$here/../../ci/seccomp-chromium.json}"
            -e PUBLISHING_USER_CONTENT=1) ;;
esac
exec docker run "${flags[@]}" "$image" "$@"
