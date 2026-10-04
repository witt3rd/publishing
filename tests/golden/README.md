# Golden fixtures: media, pandoc, convert

`tests/test_golden.py` converts the committed files in `inputs/` and compares each output's sha256 and size
with `manifest.json`. **Tolerance: none.** The profiles are reproducible (ffmpeg `+bitexact`, one thread;
pandoc/TeX with `SOURCE_DATE_EPOCH` and `FORCE_SOURCE_DATE`; office2pdf), so any changed byte is a real
change: a profile bump (ffmpeg, pandoc, TeX Live, office2pdf, base image digest) or a flag change.

The bytes belong to one toolchain, so each profile runs only in its own image, where the Dockerfile test
stage sets `GOLDEN_PROFILE` (`media`, `pandoc`, `convert`); elsewhere the cases skip. CI runs them in the
existing `media`, `pandoc` and `convert` jobs.

When a bump intentionally changes output, review the change, then regenerate in the profile image and
commit the manifest with the bump (the manifest records the toolchain it came from):

    docker build -f Dockerfile.media --target test -t publishing-media-test .
    docker run --rm --network none --user "$(id -u):$(id -g)" -e GOLDEN_UPDATE=1 \
      -v "$PWD/tests:/opt/publishing/src/tests" publishing-media-test tests/test_golden.py

(likewise `Dockerfile.pandoc`, `Dockerfile.convert`). The inputs were made with the pinned tools:
`clip-a.mp4`/`clip-b.mp4` by ffmpeg lavfi (testsrc/testsrc2, 64x48, 1 s), `note.docx`/`note.odt` by pandoc
from `note.md`, `minimal.docx` is the one in `test_convert_integration.py`.
