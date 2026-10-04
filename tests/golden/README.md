# Golden fixtures: media, pandoc, convert, extract, render

`tests/test_golden.py` converts or renders the committed files in `inputs/` and compares each output's sha256 and size
with `manifest.json`. **Tolerance: none, with three documented exceptions (below).** The profiles are reproducible (ffmpeg `+bitexact`, one thread;
pandoc/TeX with `SOURCE_DATE_EPOCH` and `FORCE_SOURCE_DATE`; office2pdf), so any changed byte is a real
change: a profile bump (ffmpeg, pandoc, TeX Live, office2pdf, base image digest) or a flag change.

The bytes belong to one toolchain, so each profile runs only in its own image, where the Dockerfile test
stage sets `GOLDEN_PROFILE` (`media`, `pandoc`, `convert`, `extract`, `render`); elsewhere the cases skip.
CI runs them in the `media`, `pandoc`, `convert`, `extract` and `render` jobs.

- **extract** (`Dockerfile.extract`): one input per format under `inputs/extract/`, each markdown output
  byte-identical (markitdown and pypdfium2 are pinned by `uv.lock`).
- **render** (`Dockerfile`, the toolbox image): trusted (the test stage has no seccomp profile).
  **Documented tolerance:** Chromium stamps a fresh date and id on every PDF, so PDF bytes are *not*
  compared. Instead each page image and thumbnail is byte-identical, and `*.out.pdf.txt` pins the PDF's
  page count and extracted text. The user-content (sandboxed) path is covered by `tests/test_renderhtml.py`.

When a bump intentionally changes output, review the change, then regenerate in the profile image and
commit the manifest with the bump (the manifest records the toolchain it came from):

    docker build -f Dockerfile.media --target test -t publishing-media-test .
    docker run --rm --network none --user "$(id -u):$(id -g)" -e GOLDEN_UPDATE=1 \
      -v "$PWD/tests:/opt/publishing/src/tests" publishing-media-test tests/test_golden.py

(likewise `Dockerfile.pandoc`, `Dockerfile.convert`, `Dockerfile.extract`; for render, `docker build --target test -t publishing-test .`
with `-e GOLDEN_PROFILE=render` already set by the stage). Regenerate one profile at a time: each run rewrites only its own
section of the manifest, and a bump of the shared base image digest or of `uv.lock` needs extract and render both. Inputs are made with the pinned tools inside the profile image (extract inputs from `FIXTURES` in `test_extract.py`), never by hand.

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
