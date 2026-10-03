# The publishing toolbox image: one CLI (`publishing`, the entrypoint) and its pinned renderers,
# for services and CI that render headless. The contract is in README "Services".
#
#   docker build -t publishing:0.2.0 .
#   docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/work" publishing:0.2.0 build docs/samples/house-style-video-v1
#
# Pinned: the base images by digest, the Python tool and its Node by uv.lock, HyperFrames by
# src/publishing/hyperframes/package-lock.json, Chromium by Playwright (in uv.lock), the fonts
# vendored in the package. ffmpeg is Debian bookworm's, fixed by the base digest's release and
# recorded in the image (`ffmpeg -version`). Later converters join as further subcommands here.
FROM ghcr.io/astral-sh/uv:0.12.22@sha256:f513a91fc62fe7c17567eee97230dd198e43edb8a9fbecca843714a4358fe1bc AS uv

FROM python:3.13-slim-bookworm@sha256:5024f48ba9441d4b13a95d3945abc6365538e3a31109833367a1923523c6efed
LABEL org.opencontainers.image.title="publishing" \
      org.opencontainers.image.description="House-style decks, memos, documents (PDF) and videos (MP4), rendered headless" \
      org.opencontainers.image.source="https://github.com/witt3rd/publishing" \
      org.opencontainers.image.licenses="MIT"

COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/publishing/venv \
    PLAYWRIGHT_BROWSERS_PATH=/opt/publishing/browsers \
    PUBLISHING_CACHE=/opt/publishing/cache \
    PATH=/opt/publishing/venv/bin:$PATH \
    HOME=/tmp XDG_CACHE_HOME=/tmp/.cache

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fontconfig \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/publishing/src
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
COPY src ./src
RUN uv sync --locked --no-dev --extra video --no-editable \
    && publishing setup --with-deps --video \
    && rm -rf /var/lib/apt/lists/* /tmp/* /opt/publishing/cache/npm \
    && chmod -R a+rX /opt/publishing \
    && publishing --version && ffmpeg -version | head -1

WORKDIR /work
ENTRYPOINT ["publishing"]
CMD ["--help"]
