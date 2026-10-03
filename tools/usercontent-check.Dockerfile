# A throwaway image for tools/usercontent-check.sh: the tool, its pinned Chromium headless shell
# and the tests, run as a non-root user (uid 65532, as Spire's specialist containers run).
FROM python:3.11-slim-bookworm
COPY . /src
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN pip install --no-cache-dir --no-compile /src pytest==9.1.1 \
 && playwright install --with-deps --only-shell chromium \
 && rm -rf /var/lib/apt/lists/* && useradd -u 65532 -m render
USER 65532
WORKDIR /src
