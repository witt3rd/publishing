# publishing

Shared house-style publishing toolchain: decks, memos and long documents from markdown/Python to PDF,
and short videos from HTML to MP4, with one look, one set of vendored fonts and one pinned Chromium
render; HTML and markdown from anyone to a PDF, page images and a thumbnail, in a locked-down render;
Office files to PDF through a pinned office2pdf and documents to markdown through a pinned markitdown,
neither with a browser. Every repo that produces
reports pins a version of this tool and proves in CI that each committed PDF and MP4 rebuilds from its
source.

The rules for captain-facing reports (what a report is, where copies go, naming, versions, the animus
exception) live in `~/Documents/AGENTS.md`. This tool implements them; it does not restate them.

## Install

The tool owns its environment through uv; nothing depends on host Python, Node or fonts. It installs
as a profile (an extra), or several:

```sh
# render: decks, memos and documents (Playwright and the pinned Chromium)
uv tool install 'publishing[render] @ git+https://github.com/witt3rd/publishing@v0.10.0'   # or run through uvx
publishing setup                    # the pinned Chromium, into the user cache

# video: the render profile plus the pinned Node; ffmpeg comes from the host, or use the image (below)
uv tool install 'publishing[video] @ git+https://github.com/witt3rd/publishing@v0.10.0'
publishing setup --video            # also the pinned HyperFrames

# convert: Office files to PDF (the standard library and office2pdf; no Playwright, no Chromium)
uv tool install 'publishing[convert] @ git+https://github.com/witt3rd/publishing@v0.10.0'
publishing setup --convert          # the pinned office2pdf, checksummed, into the user cache

# pandoc: markdown, html, docx and odt to pdf, docx and html (the standard library and pandoc; PDFs also need TeX)
uv tool install 'publishing[pandoc] @ git+https://github.com/witt3rd/publishing@v0.10.0'
publishing setup --pandoc           # the pinned pandoc, checksummed, into the user cache

# extract: documents to markdown (markitdown, exact pin; no Playwright, no Chromium; glibc, not Alpine)
uv tool install 'publishing[extract] @ git+https://github.com/witt3rd/publishing@v0.10.0'

# media: audio and video through ffmpeg (the standard library only; ffmpeg on the PATH, or use the media image)
uv tool install 'publishing[media] @ git+https://github.com/witt3rd/publishing@v0.10.0'

# images: resize, convert, thumbnails and metadata strip through Pillow (exact pin; no Playwright, no Chromium)
uv tool install 'publishing[images] @ git+https://github.com/witt3rd/publishing@v0.10.0'

# pdf: merge, select pages and strip PDFs through pypdf (exact pin; no Playwright, no Chromium)
uv tool install 'publishing[pdf] @ git+https://github.com/witt3rd/publishing@v0.10.0'
```

With no extra the install is the convert profile's code alone: a render command there exits 3 and
names the install that adds the render profile.

## Use

```sh
publishing new docs/notes/topic-v1 [--format deck|memo|document|video]   # scaffold a source folder
publishing build [SOURCE...] [--png DIR]   # build PDFs and MP4s beside their sources (default: all under docs/)
publishing check [PATH...]                 # fail unless every PDF and MP4 matches a fresh build of its source
publishing publish docs/notes/topic-v1     # copy the PDF or MP4 to ~/Documents/<folder>/, never overwriting
publishing compare OLD.pdf NEW.pdf -o OUT.pdf --pair 5:7:"A table" --notes notes.md   # before/after deck
publishing html PAGE.html -o OUT.pdf [--json]   # a person's HTML to PDF: always user-content mode
publishing render-html PAGE.html --pdf OUT.pdf --png OUTDIR --thumbnail 320   # PDF, page images, thumbnail (see Render)
publishing render-md NOTE.md --pdf OUT.pdf      # a person's markdown as a house memo, the same way
publishing pdf-pages FILE.pdf --png OUTDIR      # any PDF's pages as images
publishing build --user-content [SOURCE...]     # build untrusted memos/documents the same way
publishing convert report.docx [-o report.pdf]  # an Office file to a PDF (the convert profile; see Convert)
publishing convert notes.md -o notes.docx       # markdown, html, docx or odt to pdf, docx or html (the pandoc profile)
publishing extract report.pdf [-o report.md]    # a document to markdown (the extract profile; see Extract)
publishing media audio|video|thumbnail|concat ...   # ffmpeg transcodes, frames, joins (the media profile; see Media)
publishing images resize|convert|thumbnail|strip ...   # resize, re-encode, thumbnails, metadata strip (the images profile; see Images)
publishing pdf merge|pages|strip ...   # join PDFs, keep pages, drop metadata and active content (the pdf profile; see PDF tools)
```

**User content.** Anything made from a person's content renders in user-content mode: Chromium's
sandbox on, no network, nothing outside the document's own folder, no script, and caps on bytes, pages,
time and memory. `html`, `render-html`, `render-md` and `pdf-pages` use it by default (only an explicit
`--trusted`, for the house's own sources, leaves it); a build uses it with `--user-content`,
`[user_content] enabled = true` in report.toml, or `PUBLISHING_USER_CONTENT=1` (for a service's image,
where no flag turns it off). The container flags it needs (non-root, `ci/seccomp-chromium.json`, `--network none`) and its
residual risks: [docs/user-content.md](docs/user-content.md). The plain build is for trusted sources.

## Conventions

- **Formats.** `deck`: a folder with `slides.py` defining `TITLE` and `S` (page HTML at 1920×1080; the
  helpers in `publishing.page` give the title page, slides, cards and the numbered question card).
  `memo`: a folder with `memo.md`, portrait. `document`: a folder with `document.md`, long form, with a
  cover, contents with page numbers, a running header and page numbers. `video`: a folder with
  `video.html` (see Video). A folder with `source.txt` marks a PDF built elsewhere. Memos and documents
  are markdown with flat front matter (`title`, `subtitle`, `kicker`, `meta`, `footer`, `paper`), fenced
  divs (`::: summary`, `::: q`), heading attributes (`{#id .newpage}`), pipe tables with a `: caption`
  line, figures, footnotes and highlighted code. A document's front matter also takes `numbered: true`
  (sections numbered 1, 1.1, 1.1.1 in the headings and the contents) and `toc: 1|2|3|false` (how many
  heading levels the contents list; 2 by default, `false` for none).
- **Layout.** `docs/<kind>/<topic>-vN/` holds the sources; `docs/<kind>/<topic>-vN.pdf` (or `.mp4`) sits
  beside it, committed. The folder is the listing: no index files.
- **Config.** `docs/report.toml` holds the pinned version (`publishing = "0.10.0"`), the `project`, the
  repo's private scan words, the `[publish]` folder for each kind, the `[video] tolerance`, and
  `[[document]]` entries for markdown files with a fixed PDF path (for example a spec rendered to
  `docs/Spec.pdf`). Its full schema is the docstring of `src/publishing/config.py`. A command run with a
  different version than the pin re-runs itself through `uvx` at the pinned tag.
- **Every build** fails, and writes nothing, on a layout problem (content leaving its page or running into
  the footer, a table or figure wider than the column), a host font or a glyph outside the vendored fonts,
  a secret, a host detail (home path, e-mail), a stale day word (`[scan] days`), or a private word.
  A build that would change nothing but the bytes leaves the committed file untouched.
- **Check** compares words and page count for a PDF, not bytes (Chromium's PDF bytes differ run to run);
  for an MP4 see Video.
- **CI.** A repo proves its committed PDFs and MP4s rebuild from source with the GitHub Action in this
  repo. Put `docs/report.toml` (`publishing = "0.10.0"`, `project = "..."`) and this in
  `.github/workflows/reports.yml` (the same file is `ci/reports.yml`):

  ```yaml
  name: reports rebuild from source
  on: { pull_request: { paths: ['docs/**'] }, workflow_dispatch: {} }
  permissions: { contents: read }
  jobs:
    check:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v7
        - uses: witt3rd/publishing@v0.10.0   # with: { config: path/to/report.toml } if it is elsewhere
  ```

  The action installs uv, reads the `publishing` pin from report.toml, runs `publishing check` through `uvx`
  at that tag (the video extra, HyperFrames and ffmpeg when a `video.html` exists, else the render extra),
  and fails on a missing, stale or orphan file. The `@v0.10.0` on `uses:` only selects `ci/check.sh`; the
  version that builds is the pin, so bump the pin and commit the rebuilt files together. Add
  `with: { lfs: true }` to checkout if the files are in LFS. Run it by hand with `ci/check.sh [CONFIG]`
  (`PUBLISHING_DEPS=0` off Debian, `PUBLISHING_FROM=<path or git+url>` to test an unreleased tree);
  `tools/action-check.sh` proves it on a scratch repo, and this repo's CI runs that.
- **Versions.** Tags are immutable. A release that changes rendering (theme, fonts, Playwright,
  HyperFrames) is a minor bump; a repo adopts it by bumping its pin and running `publishing check`.

## Video

A folder `docs/<kind>/<topic>-vN/` with `video.html` builds `<topic>-vN.mp4` beside it. `video.html` is a
[HyperFrames](https://github.com/heygen-com/hyperframes) composition: a root element with
`data-composition-id`, `data-width`, `data-height`, `data-fps` and `data-duration` (seconds), holding
scenes. A scene is a deck slide (`<section class="slide clip">`, or `slide title` for the dark title)
with `data-start`, `data-duration` and `data-track-index`; the theme (`theme/video.css`, linked by the
build) gives every deck class its deck look. Motion is CSS animation, which HyperFrames seeks frame by
frame: the theme's `.rise`, `.fade`, `.grow` and `.pop`, delayed with `style="--at: .5s"` from the scene's
start, plus `.flow`, `.card` and `.arrow` for a diagram that builds up, and `.body.middle`. Other files in
the folder (images, CSS) are the composition's. `publishing new --format video` scaffolds one;
`docs/samples/house-style-video-v1/` is a worked example made from the house deck.

- **Gates.** Before it renders, a build runs the house scan on the composition's text, refuses text set
  in a face that is not vendored, anything loaded from the network, a missing image, and CSS animation on
  an SVG shape (HyperFrames seeks HTML elements only, so it would play in real time: animate the HTML that
  holds it). Then `hyperframes check` gates lint, runtime errors, layout and WCAG AA contrast.
- **Render.** HyperFrames (exact version in `src/publishing/hyperframes/package-lock.json`) runs on the
  `video` extra's Node, with the Playwright Chromium headless shell the PDFs use, one worker, software GPU,
  BeginFrame capture, a private `HOME`, no telemetry and no update check. The MP4 (H.264, no audio) is
  stamped with the sha256 of its source folder in its `comment` tag.
- **Determinism.** The same toolchain renders the same bytes (the tests and CI's image job prove it).
  Another ffmpeg build encodes the same frames differently, so `check` passes when the committed MP4
  carries the source's stamp (any edit to the folder is caught there), has the same size, rate and frame
  count, and its frames are identical or at least `[video] tolerance` dB PSNR (default 40) from a fresh
  render's, at the worst frame. Measured on the sample against the image's render (Debian ffmpeg 5.1):
  Arch's ffmpeg 9.0 is 48.9 dB, GitHub's Ubuntu 24.04 ffmpeg 6.1 is 43.0 dB; theme changes the tolerance
  must catch are lower: an h2 1 px larger is 29.0 dB, kicker letter-spacing +0.01 em is 38.7 dB. The
  image is the reference renderer: build committed MP4s there.
- **Credits.** HyperFrames is Apache-2.0, by HeyGen and its contributors; it is pinned, not vendored. See
  `NOTICE`.

## Convert

`publishing convert SRC [-o OUT] [--to pdf|docx|html] [--engine auto|office2pdf|pandoc] [--timeout SECONDS]
[--max-bytes N]`, or from Python `publishing.convert.convert(src, dest=None, *, timeout=120, max_bytes=256 MiB)
-> Path` (Office to PDF) and `publishing.pandoc.convert(src, dest=None, *, to=None, timeout=120,
max_bytes=256 MiB) -> Path` (it raises a `ConvertError` subclass whose `exit_code` is the command's). It is the
headless entry for services. Two engines, one command:

| Source | To | Engine (`auto`) |
|---|---|---|
| `.docx` `.xlsx` `.pptx` | pdf | office2pdf |
| `.md` `.markdown` `.html` `.htm` `.docx` `.odt` | pdf, docx, html | pandoc |

The output format is `--to`, else the suffix of `-o`, else pdf. An Office file with no `--to` and no
`-o` suffix pandoc can name stays an office2pdf PDF, as before pandoc joined. `--engine pandoc` sends a
`.docx` to pandoc even for a PDF; `--engine office2pdf` writes PDFs only. A source neither engine reads (a
spreadsheet to docx, `.txt`) is exit 2.

- **In.** The source's suffix, in any letter case, decides the reader. Nothing else reaches a converter
  (exit 2).
- **Out.** One file at `OUT`, by default beside `SRC` with the suffix of the format; its path is the only
  line on stdout. An existing file is never overwritten (exit 2). On any failure there is no `OUT`.
- **Same limits, both engines.** The converter is stopped after `--timeout` seconds (default 120) or as soon as
  its output passes `--max-bytes` (default 268435456); it runs in a fresh temporary folder under `TMPDIR`
  that is always removed. Neither changes a conversion that stays inside them.
- **Errors** (stderr, `publishing: ` and one message). A non-zero exit carries at most 400 characters of the
  converter's stderr, or `<converter> failed (<status>)` when it wrote none; a zero exit with no output is
  the same error; so is an output that is not the format asked for (`%PDF-`, a zip for docx), a time-out or
  an output over the cap.
- **Exit codes.** 0 converted; 1 the conversion failed; 2 usage (not a source the engine reads, no such
  source, the output exists, `--to` against the `-o` suffix, a bad option); 3 no converter
  (`office2pdf not found`, `pandoc not found`, or `pdflatex not found` for a PDF), or `setup` failed.
- **Environment.** `OFFICE2PDF_BIN`, `PANDOC_BIN` (each, when set, is authoritative, even when wrong or
  empty: no fallback); `PUBLISHING_CACHE` (default `$XDG_CACHE_HOME/publishing`, else
  `~/.cache/publishing`) for the pinned installs; `SOURCE_DATE_EPOCH` (pandoc's dates; default 0);
  `TMPDIR`; `OFFICE_PDF_TESTS=1` and `PANDOC_TESTS=1` make the real-conversion tests run, and fail without
  their converters.

### Office to PDF (office2pdf)

- **Converter.** [office2pdf](https://github.com/developer0hye/office2pdf) `v0.6.7` (pure Rust, no
  LibreOffice), Apache-2.0. `publishing setup --convert [--bin-dir DIR]` downloads the release build for
  this machine (`x86_64` musl and glibc, `aarch64` glibc, macOS), checks the archive's and the binary's
  sha256 against `src/publishing/convert.py`, and installs it into the user cache or as
  `DIR/office2pdf`; run again, it downloads nothing. There is no `aarch64` musl build upstream.
- **Which converter.** `OFFICE2PDF_BIN`, when set, is authoritative, even when it is wrong or empty: it
  never falls back. Otherwise `/usr/local/bin/office2pdf`, then the pinned install in the user cache,
  then a developer build at `~/src/ext/office2pdf/target/release/office2pdf`. Only an executable regular
  file is a converter.
- **The call.** `office2pdf SRC -o OUT` into the temporary folder, moved into place when it succeeds.
- **Containers.** The toolbox image (`Dockerfile`, Services) carries the glibc build at
  `/usr/local/bin/office2pdf`: `docker run … publishing:0.10.0 convert /in/report.docx -o /out/report.pdf`.
  `Dockerfile.convert` is the convert profile alone on Alpine (musl), entrypoint `publishing convert`;
  its `test` stage runs the convert tests and the real conversion, which CI runs with `--network none`.
  In an existing Alpine image (with `python3` from apk):
  `uv tool install 'publishing[convert] @ git+…@v0.10.0' && publishing setup --convert --bin-dir /usr/local/bin`.

### Any to any (pandoc)

- **Converter.** [pandoc](https://pandoc.org) `3.12` (GPL-2.0-or-later, run as a separate program).
  `publishing setup --pandoc [--bin-dir DIR]` downloads the Linux release (`amd64`, `arm64`), checks the
  archive's and the binary's sha256 against `src/publishing/pandoc.py`, and installs it into the user cache or
  as `DIR/pandoc`. `PANDOC_BIN`, then `/usr/local/bin/pandoc`, then the cache. PDFs go through pdfLaTeX
  (`texlive-latex-base`, `-recommended`, `texlive-fonts-recommended`, `lmodern`: the pandoc image has them);
  without `pdflatex` a PDF is exit 3 and docx and html still convert. pdfLaTeX reads UTF-8 text but not
  every script: a glyph the Latin Modern fonts lack is dropped.
- **The call.** `pandoc --sandbox -f READER -t WRITER` on a copy of the source in the temporary folder.
  Readers: markdown (raw TeX and raw attributes off), html, docx, odt. Writers: pdf, docx and html5
  (standalone). `--sandbox` means no file is read or written but that one, and nothing is fetched: images and
  includes in a document are not pulled in.
- **A person's content.** pdfLaTeX runs with shell escape off and TeX's file access in paranoid mode
  (`openin_any=p`, `openout_any=p`); the environment passed on is `PATH`, `TMPDIR` and the locale, so no
  secret reaches it. Run the image with `--network none` as well (below).
- **Deterministic.** `SOURCE_DATE_EPOCH` (the caller's, else 0) and `FORCE_SOURCE_DATE=1` fix every date, and
  `\pdftrailerid{}` drops the PDF's trailer id (pdfTeX hashes the temporary folder's path into it): the same source in the same image gives the same bytes, for pdf, docx and html.
- **Container.** `Dockerfile.pandoc`: Debian bookworm slim by digest, the tool from `uv.lock` (extra `pandoc`),
  the pinned pandoc, a slim TeX Live from the base release (versions printed at build). Entrypoint
  `publishing convert`; runs as any user, read-only root with `--tmpfs /tmp`:
  `docker run --rm --network none --user "$(id -u):$(id -g)" -v "$PWD:/work" publishing-pandoc notes.md -o notes.pdf`.
  Its `test` stage runs the pandoc tests and the real conversions; CI runs it with `--network none`.
- **Relation to the render profile.** Memos and documents still build through the render profile (the house
  style); pandoc is the any-to-any path, not a second house style. `markdown.py` only reads pandoc's markdown
  dialect; it never ran pandoc, so this profile replaces no code in the repo.

## Extract

`publishing extract SRC [-o OUT] [--timeout SECONDS] [--max-bytes N]`, or from Python
`publishing.extract.extract(src, dest=None, *, timeout=60, max_bytes=32 MiB) -> Path` (it raises an
`ExtractError` subclass whose `exit_code` is the command's). It is the headless entry for ingestion:

- **In.** A local file named `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.html`, `.htm`, `.csv`, `.json`, `.xml`,
  `.epub` or `.txt`, in any letter case. Nothing else is tried (exit 2). **Images and audio are not
  extracted:** markitdown reads them through exiftool, a speech service or an LLM, which this profile
  neither has nor may call. URLs are not accepted, only files.
- **Out.** One markdown file at `OUT`, by default beside `SRC` with the suffix `.md`; its path is the
  only line on stdout. An existing file is never overwritten (exit 2). On any failure there is no `OUT`.
- **Extractor.** [markitdown](https://github.com/microsoft/markitdown) `0.1.8` (MIT), pinned exactly in
  the `extract` extra with its PDF, DOCX, PPTX and XLSX parsers; everything under it is pinned by
  `uv.lock`. The extra needs neither Playwright nor Chromium. Run `uv tool install` / `uv sync` from the
  lock, or a bare `pip install 'publishing[extract]'` for the same top-level pins.
- **No network.** markitdown runs in a child interpreter through `convert_local`, with plugins off, no
  LLM client and no exiftool, after every socket connect and name lookup has been replaced by an error.
  A link or image URL in a document is text, never a request. The test suite proves it with a local
  server that must see no hit, and CI runs the image with `--network none`.
- **Limits.** The child is stopped after `--timeout` seconds (default 60) or as soon as its output passes
  `--max-bytes` (default 33554432). Neither changes an extraction that stays inside them.
- **Errors** (stderr, `publishing: ` and one message). A failing parser carries at most 400 characters
  (`Type: message`), or `markitdown failed (<status>)` when it wrote none; an empty or whitespace-only
  result is an error (`found no text`: a scanned PDF has no text layer, and there is no OCR); so is a
  time-out or an output over the cap.
- **Exit codes.** 0 extracted; 1 the extraction failed (a parser error, a time-out, the cap); 2 usage
  (unsupported type, no such source, the output exists, a bad option); 3 markitdown is not installed
  (`publishing[extract]`); 4 the document has no text (`found no text`, e.g. a scanned PDF: the file was
  read, there is nothing to extract). Python: `NoText`, an `ExtractError` with `exit_code` 4.
- **PDF structure.** PDFs are read with pdfminer.six (a markitdown dependency, same pin) rather than
  through markitdown's PDF converter, which switches pages it takes for forms to pdfplumber text with no
  form feed and no blank lines (Chromium and Office conversions hit it). The output ends each page with
  `\f` (so a callers' page count is the form feeds, or one less when the last is stripped) and separates
  paragraphs by a blank line. Ligatures (`ﬁ`) become letters and letter-spaced kickers (`D E S I G N`)
  are closed up. Other formats still go through markitdown. `.msg` and `.rtf` are **not supported**
  (markitdown has no RTF reader; Outlook needs another dependency): exit 2.
- **Environment.** `TMPDIR` for the temporary folder. Nothing else; no keys, no endpoints.
- **Containers.** The toolbox image carries the extract extra:
  `docker run … publishing:0.10.0 extract /in/report.pdf -o /out/report.md`. `Dockerfile.extract` is the
  extract profile alone, entrypoint `publishing extract`; its `test` stage runs the extract tests, which
  CI runs with `--network none`. **Not Alpine:** markitdown needs onnxruntime (through magika), which
  publishes no musl wheel, so `uv sync --extra extract` fails on `python:3.13-alpine`; the image is
  Debian slim (glibc). Spire's venue: [docs/spire-extract-migration.md](docs/spire-extract-migration.md).

## Media

`publishing media audio|video|thumbnail|concat`, or from Python `publishing.media.audio / video /
thumbnail / concat` (they raise a `MediaError` subclass whose `exit_code` is the command's). One CLI,
one subcommand per capability, each with its own tests (`tests/test_media.py`).

```sh
publishing media audio in.mp4 -o out.mp3 [--bitrate 128k]          # .mp3 .m4a .opus .ogg .flac .wav
publishing media video in.mov -o out.mp4 [--height 720] [--crf 23] # .mp4 .mkv .mov (H.264+AAC), .webm (VP9+Opus)
publishing media thumbnail in.mp4 -o out.png [--at 3.5] [--width 320]   # .png .jpg
publishing media concat a.mp4 b.mp4 -o ab.mp4                      # same type, codec, size and rate; no re-encode
```

Every subcommand takes `--timeout SECONDS` (default 300), `--max-bytes N` (default 512 MiB, of output)
and `--max-seconds SECONDS` (default 3600, of input, checked with ffprobe).

- **In.** Local files only, by path, with a media suffix. A URL, a device or a pipe is refused (exit 2),
  and ffmpeg runs with `-protocol_whitelist file`, so a playlist or concat list inside a file cannot
  reach anything but a local file. No network is used or needed.
- **Out.** One file, its suffix naming the format; its path is the only line on stdout. It is built in a
  temporary folder beside it and linked into place: an existing `OUT` is never overwritten (exit 2) and a
  failure or a limit leaves no `OUT`.
- **Deterministic.** Source metadata is dropped, muxing is bit-exact and the encoder uses one thread: the
  same ffmpeg build gives the same bytes for the same input (tested). A different ffmpeg build may
  encode differently; the image is the reference.
- **Limits.** The time cap kills ffmpeg's process group; the size cap is checked while the output grows
  and passed to ffmpeg as `-fs`; the input-length cap refuses before encoding (exit 1 for all three).
- **Image.** `Dockerfile.media`: the base images by digest, Debian bookworm's ffmpeg (the build fails
  unless it is 5.1.x; `ffmpeg -version` names it), the `media` extra, no Playwright, non-root.
  `docker run --rm --network none --user "$(id -u):$(id -g)" -v "$PWD:/work" publishing-media audio in.mp4 -o out.mp3`.
  CI runs the tests in its `test` stage with `--network none`.
- **Exit codes.** 0 done; 1 ffmpeg failed or a limit was hit; 2 usage (unsupported type, no such source,
  the output exists, `--at` past the end, mixed types in `concat`); 3 ffmpeg or ffprobe not found.

## Images

`publishing images resize|convert|thumbnail|strip`, or from Python `publishing.images.resize / convert /
thumbnail / strip` (they raise an `ImageError` subclass whose `exit_code` is the command's). One CLI, one
subcommand per capability, each with its own tests (`tests/test_images.py`).

```sh
publishing images resize in.jpg -o out.png [--width 800] [--height 600]   # fit within the box, aspect kept
publishing images convert in.png -o out.webp                              # .png .jpg .jpeg .webp
publishing images thumbnail in.jpg -o t.png [--size 256]                  # fit within a SIZE x SIZE square
publishing images strip in.jpg -o clean.jpg                               # no EXIF, GPS or other metadata
```

Inputs: `.png .jpg .jpeg .webp .gif .bmp .tif .tiff` (an animated image gives its first frame). Every
subcommand takes `--timeout SECONDS` (default 60), `--max-pixels N` (default 50 million, of input),
`--max-input-bytes N` (default 64 MiB) and `--max-bytes N` (default 64 MiB, of output).

- **In.** Local files only, by path. A URL, a device or a pipe is refused (exit 2). The decoder is picked
  from the file's content among PNG, JPEG, WebP, GIF, BMP and TIFF only (no EPS or Ghostscript, no SVG), and
  a suffix that disagrees with the content is refused. The pixel count is read from the header, so a small
  file that declares a huge canvas is refused before anything is decoded (exit 1). No network is used or needed.
- **Out.** One file, its suffix naming the format; its path is the only line on stdout. It is built in a
  temporary folder beside it and linked into place: an existing `OUT` is never overwritten (exit 2) and a
  failure or a limit leaves no `OUT`. A JPEG output flattens transparency onto white.
- **Metadata.** Every output is stripped: EXIF, GPS, XMP, ICC and text chunks are not copied. The EXIF
  orientation is applied to the pixels first, so a photo is not turned on its side. `strip` is the name for
  doing only that.
- **Deterministic.** The same Pillow build gives the same bytes for the same input (tested).
- **Limits.** The work runs in a child process that is killed at the time cap; the others refuse before or
  after the work and leave nothing behind (exit 1).
- **Image.** `Dockerfile.images`: the base images by digest, Pillow from the lockfile, the `images` extra,
  no Playwright and no ffmpeg, non-root.
  `docker run --rm --network none --user "$(id -u):$(id -g)" -v "$PWD:/work" publishing-images thumbnail in.jpg -o t.png`.
  CI runs the tests in its `test` stage with `--network none`.
- **Exit codes.** 0 done; 1 unreadable image or a limit was hit; 2 usage (unsupported type, no such
  source, the output exists, a side out of range); 3 Pillow is not installed.

## PDF tools

`publishing pdf merge|pages|strip`, or from Python `publishing.pdftools.merge / pages / strip` (they raise a
`PdfError` subclass whose `exit_code` is the command's). One subcommand per capability, each with its own
tests (`tests/test_pdftools.py`).

```sh
publishing pdf merge a.pdf b.pdf [c.pdf ...] -o all.pdf      # every page of each, in the order given
publishing pdf pages in.pdf --select 1-3,5,7- -o part.pdf    # 1-based ranges, kept in the order given
publishing pdf strip in.pdf -o clean.pdf                     # every page, no metadata or active content
```

Every subcommand takes `--timeout SECONDS` (default 60), `--max-input-bytes N` (default 128 MiB, per input),
`--max-pages N` (default 2000, of output) and `--max-bytes N` (default 256 MiB, of output).

- **In.** Local `.pdf` files only, by path; a URL, a device or a pipe is refused (exit 2). A file that is not
  a PDF, is damaged or is encrypted is refused (exit 1; nothing is decrypted). At most 100 inputs.
- **Out.** One `.pdf`, built in a temporary folder beside it and linked into place: an existing `OUT` is
  never overwritten (exit 2) and a failure or a limit leaves no `OUT`. Its path is the only line on stdout.
- **Clean.** An output holds the chosen pages and nothing else of its sources: no document info or XMP, no
  outline, named destinations, form, attached files, JavaScript or page-level metadata. Annotations that
  could run or fetch something (JavaScript, launch, form-submit and remote-go-to actions, widgets, file
  attachments, screens, movies, sound, 3D, rich media) are dropped; plain links stay. A form is therefore not
  kept (its fields are not flattened). The one `/Producer` is `publishing`.
- **Deterministic.** The same pypdf build gives the same bytes for the same input (tested).
- **Limits.** The work runs in a child process that is killed at the time cap.
- **Image.** `Dockerfile.pdf`: the base images by digest, pypdf from the lockfile, the `pdf` extra, no
  Playwright, no Chromium, no PDFium, non-root.
  `docker run --rm --network none --user "$(id -u):$(id -g)" -v "$PWD:/work" publishing-pdf merge a.pdf b.pdf -o all.pdf`.
  CI runs the tests in its `test` stage with `--network none`.
- **Exit codes.** 0 done; 1 unreadable PDF or a limit was hit; 2 usage (unsupported type, no such source, the
  output exists, a bad page range, fewer than two PDFs to merge); 3 pypdf is not installed.

## Render

`publishing render-html SRC [--pdf OUT] [--png OUTDIR] [--thumbnail W]`, its siblings
`publishing render-md SRC.md [...] [--format memo|document]` and `publishing pdf-pages SRC.pdf [--png OUTDIR]
[--thumbnail W]`, or from Python `publishing.renderhtml.render(src, pdf=, png=, thumbnail=, ...)` and
`pdf_pages(src, png=, thumbnail=, ...) -> Rendered` (they raise a `RenderError` subclass whose `exit_code` is
the command's). They are the headless render entry for services (the render profile; nothing new to pin):

- **Mode.** User-content mode by default, the one in [docs/user-content.md](docs/user-content.md): Chromium's
  sandbox on and verified, no network, nothing outside the source's own folder, no script (`--allow-js` runs
  it, still offline), and the limits. `--trusted` is the house build's renderer (sandbox off, `file://`
  pages, no request filter, no limits on the render): for a repository's own sources, **never for a
  person's content**; with `PUBLISHING_USER_CONTENT=1` (a service's image) it is refused.
- **In.** `render-html`: a `.html` or `.htm` file; it may load files from its own folder only. `render-md`: a
  `.md` file, made into the house memo (or `--format document`, or the front matter's `format`) with the
  build's template, and no `report.toml`; markdown and highlighting run in a supervised child too. It runs
  no house scan (secrets, private words): that is a report rule, not a safety one. `pdf-pages`: any `.pdf`,
  treated as hostile.
- **Out.** The PDF at `--pdf OUT`, or beside SRC with the suffix `.pdf` when neither `--pdf` nor `--png` is
  given. `--png OUTDIR`: one image per page, `OUTDIR/page-001.png`, `page-002.png`, ... (more digits past
  999 pages), `--width` pixels wide (default 1400). `--thumbnail W`: the first page `W` pixels wide, as
  `OUTDIR/thumbnail.png`, or without `--png` beside the PDF as `<stem>.thumbnail.png`. Stdout is each file
  written, one per line; `--json` prints one line instead: `mode`, `pages`, `pdf`, `images`, `thumbnail`,
  `blocked` (every refused request), `sandboxed`, `netns`, `problems` (render-md's layout lint: advice).
  The same source gives the same image bytes; the PDF's bytes differ run to run (its words and pages do
  not).
- **Never overwritten.** An existing PDF or thumbnail, or an `OUTDIR` already holding `page-*.png`, is a usage
  error before anything runs (other files in `OUTDIR` are left alone). On any failure nothing is written.
- **Images.** PDFium (pypdfium2's, Chromium's PDF engine) draws them in a supervised child: the time and
  memory limits, no network where the host allows a namespace, no secrets, no forms or PDF script, and it
  refuses a PDF over `--max-bytes`, past `--max-pages`, or a page whose image would pass 40 megapixels
  before it draws.
- **Limits.** `--timeout` (default 60 s) is the wall clock of the whole call, render and images;
  `--max-pages` (300) caps the PDF and the images; `--max-bytes` (50 MiB) the source and everything it loads
  (`pdf-pages`: the PDF); `--max-memory` (2048 MB) each child's private memory; `--require-netns` fails
  unless every child runs with no network. `--paper letter|a4` sizes a page that sets no `@page size`.
- **Exit codes.** 0 done; 1 the render failed (a limit, a hostile or broken source, a crash); 2 usage (no
  such source, a wrong suffix, an output exists, a bad option, `--trusted` under
  `PUBLISHING_USER_CONTENT=1`); 3 the toolchain or the host cannot render safely (no Chromium, no sandbox,
  no network namespace with `--require-netns`), or the install is the convert profile.
- **Environment.** `PUBLISHING_USER_CONTENT=1` (above), `PLAYWRIGHT_BROWSERS_PATH` (the Chromium), `TMPDIR`
  (the staging folders). Nothing else reaches the render: its children get no token.
- **Containers.** The toolbox image runs it under the flags in
  [docs/user-content.md](docs/user-content.md) "Containers"; CI's image job runs `render-html` with
  `--png` and `--thumbnail` under them.

`publishing html` stays as it was (PDF only); `render-html` is the same render with images.

## Services

Adopting this as a service from another repo (image, entry points, pinning, Alpine vs Debian, example kit):
[docs/service.md](docs/service.md).

The CLI is the one entry for people, agents, CI and services. A service calls it headless in the image:

```sh
docker build -t publishing:0.10.0 .        # from this repo, at the tag
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/work" publishing:0.10.0 build docs/videos/topic-v1
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/work" publishing:0.10.0 check
docker run --rm --user "$(id -u):$(id -g)" --network none -v /in:/in:ro -v /out:/out publishing:0.10.0 \
  build /in/topic-v1 -o /out/topic-v1.mp4
```

- **Inputs.** A source folder (or a repo's `docs/`); `report.toml` is optional (defaults apply without
  one). The image's working directory is `/work`; mount the sources there or anywhere and pass paths.
- **Outputs.** The built file beside its source folder, or at `-o PATH`. Stdout carries one line per
  source: `built|current|copy  PATH (12.0 s, 1920x1080, 2.7 MB)` or `(N pages)`; `check` prints
  `current  PATH` per source and a summary. Problems go to stderr as `publishing: ...` lines.
- **Exit codes.** `0` done; `1` a source failed its build (lint, scan, render) or `check` found a
  difference: the author's to fix; `2` usage or configuration (a bad argument, not a source, a bad
  `report.toml`); `3` the toolchain is missing or broken (or the repo pins another version): the
  operator's to fix.
- **Environment.** `PUBLISHING_CACHE` (where `setup --video` installs HyperFrames and `setup --convert`
  office2pdf; the image sets it), `OFFICE2PDF_BIN` (convert's converter; the image sets it),
  `PLAYWRIGHT_BROWSERS_PATH` (the Chromium; the image sets it), `HYPERFRAMES_FFMPEG_PATH` and
  `HYPERFRAMES_FFPROBE_PATH` (default: the `PATH`), `PUBLISHING_DOCUMENTS` (`publish`'s root, default
  `~/Documents`). No network is needed at build time.
- **The image** (`Dockerfile`): Debian bookworm slim by digest, uv, the tool from `uv.lock` with the
  `video`, `convert` and `extract` extras, Chromium and its OS libraries, HyperFrames and office2pdf from
  `publishing setup --with-deps --video --convert`, Debian's ffmpeg, fontconfig; the house fonts are vendored in the package. It runs as any user (`--user`) and
  writes only to the mounted outputs and `/tmp`. User-content mode (`html`, `--user-content`) runs in the
  same image under the locked-down flags in [docs/user-content.md](docs/user-content.md) "Containers";
  a video is never user content (it is refused there). `render-html`, `render-md` and `pdf-pages` (Render)
  run there under the same flags. Further converters join it as subcommands of the same CLI, each with its
  own tests, so a service keeps one image and one entry.

## Accessibility

`publishing a11y FILE.pdf [...] [--kind deck|memo|document]` checks that each PDF is tagged (`/MarkInfo`,
a structure tree), has a title and a language, asks the viewer to show the title, embeds its fonts, and,
for a memo or document, has bookmarks. It reads the PDF with pypdf (the render profile's pin; no Chromium,
no network). Exit 0 clean, 1 a problem (each is printed), 2 usage. Figures without `/Alt` are a `note:`,
not a failure: Chromium tags an inline SVG as a figure and writes no alternate text for it. The three
house samples pass (`tests/test_a11y.py`).

Not offered: **PDF/A output** (Chromium cannot write it; a conversion needs Ghostscript and a validator such
as veraPDF, both outside the pinned profiles) and **PDF/UA validation** (this is a check of what the house
renderer controls, not a conformance proof). Either would be its own profile.

## Develop

```sh
uv sync --all-extras && uv run publishing setup --video --convert && OFFICE_PDF_TESTS=1 uv run pytest -q && uv run publishing check
tools/usercontent-check.sh   # the user-content tests in a locked-down container (needs Docker)
```

The video tests need ffmpeg on the `PATH`. The fonts are Noto (SIL OFL 1.1,
`src/publishing/theme/fonts/OFL.txt`); `tools/vendor-fonts.py` re-vendors them. MIT licence for the code;
third-party credits in `NOTICE`.
