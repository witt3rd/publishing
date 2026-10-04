# Golden fixtures: media, pandoc, convert, extract, render

`tests/test_golden.py` converts or renders the committed files in `inputs/` and compares each output's sha256 and size
with `manifest.json`. **Tolerance: none.** The profiles are reproducible (ffmpeg `+bitexact`, one thread;
pandoc/TeX with `SOURCE_DATE_EPOCH` and `FORCE_SOURCE_DATE`; office2pdf), so any changed byte is a real
change: a profile bump (ffmpeg, pandoc, TeX Live, office2pdf, base image digest) or a flag change.

The bytes belong to one toolchain, so each profile runs only in its own image, where the Dockerfile test
stage sets `GOLDEN_PROFILE` (`media`, `pandoc`, `convert`, `extract`, `render`); elsewhere the cases skip.
CI runs them in the `media`, `pandoc`, `convert`, `extract` and `render` jobs.

- **extract** (`Dockerfile.extract`): one input per format in `inputs/extract/` (`a.pdf` .. `a.xml`, made
  by `FIXTURES` in `test_extract.py`); each markdown output is byte-identical (markitdown and pypdfium2 are
  pinned by `uv.lock`).
- **render** (`Dockerfile`, the toolbox image): `render-html` of `inputs/render/pages.html` (3 pages) and
  `render-md` of `memo.md`, both trusted (the test stage has no seccomp profile). **Documented tolerance:**
  Chromium stamps a fresh date and id on every PDF, so PDF bytes are *not* compared. Instead each page image
  and thumbnail is byte-identical, and `*.out.pdf.txt` pins the PDF's page count and extracted text.
  The user-content (sandboxed) path is covered by `tests/test_renderhtml.py`, not here.

When a bump intentionally changes output, review the change, then regenerate in the profile image and
commit the manifest with the bump (the manifest records the toolchain it came from):

    docker build -f Dockerfile.media --target test -t publishing-media-test .
    docker run --rm --network none --user "$(id -u):$(id -g)" -e GOLDEN_UPDATE=1 \
      -v "$PWD/tests:/opt/publishing/src/tests" publishing-media-test tests/test_golden.py

(likewise `Dockerfile.pandoc`, `Dockerfile.convert`, `Dockerfile.extract`; for render, `docker build --target test -t publishing-test .`
with `-e GOLDEN_PROFILE=render` already set by the stage). Regenerate one profile at a time: each run rewrites only its own
section of the manifest, and a bump of the shared base image digest or of `uv.lock` needs extract and render both. The inputs were made with the pinned tools:
`clip-a.mp4`/`clip-b.mp4` by ffmpeg lavfi (testsrc/testsrc2, 64x48, 1 s), `note.docx`/`note.odt` by pandoc
from `note.md`, `minimal.docx` is the one in `test_convert_integration.py`.
`inputs/extract/` was generated from `FIXTURES` in `test_extract.py` inside the extract test image.
