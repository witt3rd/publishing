# Golden fixtures: media, pandoc, convert, extract, images, pdf, render

`tests/test_golden.py` converts or renders the committed files in `inputs/` and compares each output's sha256 and size
with `manifest.json`. **Tolerance: none, with three documented exceptions (below).** The profiles are reproducible (ffmpeg `+bitexact`, one thread;
pandoc/TeX with `SOURCE_DATE_EPOCH` and `FORCE_SOURCE_DATE`; office2pdf), so any changed byte is a real
change: a profile bump (ffmpeg, pandoc, TeX Live, office2pdf, base image digest) or a flag change.

The bytes belong to one toolchain, so each profile runs only in its own image, where the Dockerfile test
stage sets `GOLDEN_PROFILE` (`media`, `pandoc`, `convert`, `extract`, `images`, `pdf`, `render`); elsewhere the cases skip.
CI runs them in the `media`, `pandoc`, `convert`, `extract`, `images`, `pdf` and `render` jobs.

- **extract** (`Dockerfile.extract`): one input per format under `inputs/extract/`, each markdown output
  byte-identical (markitdown and pypdfium2 are pinned by `uv.lock`).
- **images** (`Dockerfile.images`): resize (width, height), convert (png to webp and jpg, webp to png), thumbnail and an
  EXIF-rotated JPEG through strip, from inputs in `inputs/images/`; byte-identical (Pillow and its wheels are pinned by `uv.lock`).
- **pdf** (`Dockerfile.pdf`): merge, pages (a selection, and a reordering) and strip from `inputs/pdf/`; byte-identical (pypdf is pinned).
- **render** (`Dockerfile`, the toolbox image): trusted (the test stage has no seccomp profile).
  **Documented tolerance:** Chromium stamps a fresh date and id on every PDF, so PDF bytes are *not*
  compared. Instead each page image and thumbnail is byte-identical, and `*.out.pdf.txt` pins the PDF's
  page count and extracted text. The user-content (sandboxed) path is covered by `tests/test_renderhtml.py`.

When a bump intentionally changes output, review the change, then regenerate in the profile image and
commit the manifest with the bump (the manifest records the toolchain it came from):

    docker build -f Dockerfile.media --target test -t publishing-media-test .
    docker run --rm --network none --user "$(id -u):$(id -g)" -e GOLDEN_UPDATE=1 \
      -v "$PWD/tests:/opt/publishing/src/tests" publishing-media-test tests/test_golden.py

(likewise `Dockerfile.pandoc`, `Dockerfile.convert`, `Dockerfile.extract`, `Dockerfile.images`, `Dockerfile.pdf`; for render, `docker build --target test -t publishing-test .`
with `-e GOLDEN_PROFILE=render` already set by the stage). Regenerate one profile at a time: each run rewrites only its own
section of the manifest, and a bump of the shared base image digest or of `uv.lock` needs extract and render both. Inputs are made with the pinned tools inside the profile image (extract inputs from `FIXTURES` in `test_extract.py`), never by hand.

## Coverage matrix (capability by fixture)

| Capability | Golden | Where |
| --- | --- | --- |
| media audio, video, thumbnail, concat | 14 cases (2 by ffprobe summary) | `media` |
| pandoc md/html/docx/odt to html/docx/pdf | 8 cases | `pandoc` |
| convert Office to PDF | `minimal.pdf` | `convert` |
| extract (10 formats) | one per format | `extract` |
| images resize, convert, thumbnail, strip | 7 cases | `images` |
| pdf merge, pages, strip | 4 cases | `pdf` |
| render-html (page images, thumbnail, PDF text) | `pages`, `memo` | `render` |
| build from a template (the house PDF) | the CI `container reproduces its own bytes` job, plus `tests/fixtures/house-style-*-v1.pdf` | `ci.yml`, `test_build.py` |
| a11y, compare, publish, check, user-content (untrusted html) | none by bytes: rule checks, not outputs | `test_a11y.py`, `test_publish.py`, `test_renderhtml.py`, `test_usercontent*.py` |
| video (HyperFrames) | none: Chromium frames and encoder are not byte-stable across machines | `test_video.py` |

A new capability that writes a file gets a golden case in its own profile (or a documented reason in this table) with
the PR that adds it; `test_manifest_lists_exactly_the_cases` keeps the manifest and the cases in step.

## Tolerance

- **Media `audio.opus` and `video.webm`**: libopus and libvpx select CPU-specific (SIMD) code paths, so the
  encoded bytes differ between machines (stable on one machine, different on the CI runner; the other
  media outputs matched everywhere). These two cases compare an ffprobe summary (codec, sample rate,
  channels, size, pixel format, decoded frame count), stored in the manifest as the hash of that text. Their
  manifest `bytes` is the summary's length, not the media file's.
- **Render PDFs**: see above (page images exact; PDF checked by page count and text).
- Everything else is byte-identical. Do not widen the list without evidence of cross-machine drift.

## Maintenance

- **Update procedure is tested**: `tests/test_golden_update.py` drives the same check on a synthetic profile: a
  deliberate bump fails with the regenerate instruction, passes after `GOLDEN_UPDATE=1`, and regenerating leaves other
  profiles' manifest sections alone. It also checks, on any host, that the manifest lists exactly the cases.
- **CI time budget**: `ci/budget.txt` holds a per-job budget; `tools/ci-budget.sh [run-id]` reports a run against it
  (the nightly `budget` job prints it to the summary, non-blocking). Raise a budget with the change that earns it.
- **Flake hunt**: `tools/flake-hunt.sh [N]` runs the host suite N times and lists any test whose outcome varies. Three
  runs (419 outcomes) found none. The in-image golden suites are the ones that can drift by machine (see Tolerance); run
  the hunt inside a profile image for those.
