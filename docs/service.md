# Using publishing as a service

How any repo or service adopts `publishing` from this repo alone: the container image, one CLI entry per
capability, version pinning, and which image profile to run. A runnable kit is in
[`examples/service/`](../examples/service/). Per-command contracts (flags, limits, exit codes) are in the
README sections named below; this page does not restate them.

A service never imports the tool. It runs the CLI, headless, in a container, and reads three things:
**stdout** (the output path; with `--json` one JSON line), **stderr** (`publishing: <reason>`), and the
**exit code**.

## 1. Pin a version

- Tags are immutable (`vX.Y.Z`); the tool's version is the rendering contract. Pin one tag everywhere:
  the image tag, the `git+…@vX.Y.Z` install and `docs/report.toml`'s `publishing = "X.Y.Z"`.
- Bump all of them in one commit. A release that changes rendering is a minor bump.
- **Check the tag exists before you pin it** (`git ls-remote --tags https://github.com/witt3rd/publishing`).
  `pyproject.toml` on `main` says `0.8.0`, but at the time of writing the newest pushed tag is `v0.7.0`
  (tracked in [#12](https://github.com/witt3rd/publishing/issues/12)). Until `v0.8.0` is tagged, pin the
  commit instead (`@<sha>`, `docker build …git#<sha>`) and name the image for that sha.
- No registry image is published: **you build the image from this repo at your pinned ref**. The
  Dockerfiles pin every base image by digest, and the tool and its dependencies by `uv.lock`, so the same
  ref rebuilds the same toolchain.

```sh
REF=v0.7.0   # your pin
docker build -t publishing:$REF https://github.com/witt3rd/publishing.git#$REF
docker build -f Dockerfile.convert -t publishing-convert:$REF https://github.com/witt3rd/publishing.git#$REF
docker run --rm publishing:$REF --version
```

Rebuilding is only repeatable per ref, so record the ref in the image tag and never use `latest`.

## 2. Pick an image profile

| Image (Dockerfile) | Base | Entrypoint | Carries | Run it for |
|---|---|---|---|---|
| `publishing` (`Dockerfile`) | Debian bookworm slim (glibc) | `publishing` | `render`, `video`, `convert` (office2pdf), `extract`; Chromium, HyperFrames, Debian ffmpeg | everything except pandoc (any-to-any) and the media profile's ffmpeg-5.1 gate |
| `publishing-convert` (`Dockerfile.convert`) | **Alpine** (musl) | `publishing convert` | `convert` Office → PDF only; no Chromium, no fonts, ~smallest | a service that only converts `.docx/.xlsx/.pptx` |
| `publishing-pandoc` (`Dockerfile.pandoc`) | Debian slim | `publishing convert` | pandoc + slim TeX Live | markdown/html/docx/odt → pdf/docx/html |
| `publishing-extract` (`Dockerfile.extract`) | Debian slim | `publishing extract` | markitdown | documents → markdown only |
| `publishing-media` (`Dockerfile.media`) | Debian slim | `publishing media` | ffmpeg 5.1 | audio/video transcode, thumbnail, concat |

**Alpine vs Debian.** Alpine only for the convert profile: office2pdf ships a musl build for `x86_64`
only (no `aarch64` musl), and the profile needs no Python wheels. Everything else is Debian (glibc):
Chromium/Playwright and onnxruntime (behind markitdown, so `extract`) publish no musl build, so
`uv sync --extra extract` fails on Alpine. Do not try `render`, `video` or `extract` on Alpine. On an
`aarch64` host use a Debian image (`convert` included).

The toolbox's entrypoint is `publishing`, so its first argument is the subcommand. A profile image bakes
the subcommand in: give it arguments only.

```sh
docker run … publishing:$REF extract /in/a.pdf -o /out/a.md           # toolbox
docker run … publishing-extract:$REF /in/a.pdf -o /out/a.md           # profile image, same thing
```

Outside Docker, the same profiles are extras: `uv tool install 'publishing[convert] @ git+https://github.com/witt3rd/publishing@$REF'`
and the `publishing setup [--video|--convert|--pandoc]` that fetches the pinned binaries (README "Install").

## 3. Entry points per capability

One CLI, one subcommand per capability; `publishing --help` lists them and each README section holds the
flags and limits. Conventions that hold across them:

- A capability runs in the toolbox image unless a profile image carries it (section 2). Video and the
  house `build`/`check` run only there; pandoc (any-to-any) and media run only in their profile images.
- Stdout is the output path (or one JSON line with `--json`); render commands print each file written.
- A person's content goes through the user-content commands (section 4), never `build --trusted`.

Rules common to the file-in, file-out commands: an existing output is never overwritten (exit 2), a
failure leaves no output, inputs are local files only (no URLs), and each has `--timeout` and
`--max-bytes`. **Name the output with `-o`/`--pdf` on a mounted, writable folder**; the default is
"beside the source", which fails on a read-only input mount.

### Exit codes

| Code | Meaning | A service should |
|---|---|---|
| 0 | done | read the path from stdout |
| 1 | this document failed (broken, hostile, over a limit, a layout error) | tell the sender; do not retry |
| 2 | the call is wrong (usage, missing source, output exists, bad option) | treat as a bug in the service |
| 3 | the toolchain is missing or broken (no Chromium, no sandbox, no converter) | page the operator |
| 4 | `extract` only: the file has no text (a scanned PDF) | tell the sender; there is no OCR |

[`examples/service/client.py`](../examples/service/client.py) is this table as ten lines of Python.

## 4. User-content mode

Anything made from a person's content (`html`, `render-html`, `render-md`, `pdf-pages`, `build
--user-content`) renders with Chromium's sandbox on, no network, no script, and caps. In a service's
image set **`PUBLISHING_USER_CONTENT=1`**: it turns the mode on for every build and refuses `--trusted`,
so no flag can turn it off. A video and a deck are refused in that mode.

Chromium's sandbox needs unprivileged user namespaces, which Docker's default seccomp profile blocks, so
the render commands refuse (exit 3) under default flags. Run them with the repo's profile, never
`--privileged`, `--no-sandbox`, `seccomp=unconfined` or `CAP_SYS_ADMIN`:

```sh
docker run --rm --user 65532:65532 --cap-drop ALL --security-opt no-new-privileges \
  --security-opt seccomp=ci/seccomp-chromium.json --network none --read-only --tmpfs /tmp \
  --memory 2g --pids-limit 512 -e PUBLISHING_USER_CONTENT=1 -v "$DOC_DIR:/in:ro" -v "$OUT_DIR:/out" \
  publishing:$REF render-html /in/page.html --pdf /out/page.pdf --png /out/pages --thumbnail 320 --json
```

`ci/seccomp-chromium.json` is Docker's default profile plus one rule; take it from your pinned ref.
Why each flag, and the residual risks: [user-content.md](user-content.md) "Containers". `convert`,
`extract` and `media` need none of the seccomp profile; give them `--network none`, `--read-only`,
`--tmpfs /tmp`, non-root and the resource caps.

## 5. The example kit

[`examples/service/`](../examples/service/):

The kit shows the convention, not a catalogue: one wrapper runs a command in the locked-down container
(it adds the seccomp profile and `PUBLISHING_USER_CONTENT=1` for render commands; `PUBLISHING_BIN=` runs a
local CLI instead), a standard-library client maps exit codes to a verdict, a compose file carries the
same flags, and `sample/` holds inputs to try.

```sh
cd examples/service
mkdir -p out
./run.sh render-md sample/hello.md --pdf out/hello.pdf
python3 client.py extract sample/hello.html -o out/hello.md
```

## 6. Adopting in another repo

1. Pin a tag (section 1) and record it once (an `.env`, a Dockerfile `ARG`, `docs/report.toml`).
2. Build the image(s) for the profiles you use (section 2) in your CI or deploy step.
3. Copy `run.sh` (or the flags in it) and, for render commands, `ci/seccomp-chromium.json` from the same ref.
4. Call it; branch on the exit code (section 3).
5. To prove committed house-style PDFs and MP4s still rebuild from source, use the GitHub Action
   instead (README "Conventions", CI): it needs only `docs/report.toml` and the workflow.
