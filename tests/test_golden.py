"""Golden fixtures for the media, pandoc and convert profiles (docs: tests/golden/README.md).

Each case converts a committed input (tests/golden/inputs) and compares the output's sha256 with
tests/golden/manifest.json: a profile bump (ffmpeg, pandoc, TeX Live, office2pdf, a base image or this
package's flags) that changes any output byte fails here. The tolerance is none: outputs are
reproducible (see media._DETERMINISTIC, pandoc's SOURCE_DATE_EPOCH), so a changed hash is a real change.
Review it, then regenerate with GOLDEN_UPDATE=1 and commit the manifest with the bump.

The bytes belong to one toolchain, so a profile runs only in its own image (GOLDEN_PROFILE=media|pandoc|
convert, set by the Dockerfile test stages) and skips elsewhere; a missing tool there fails.
"""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

GOLDEN = Path(__file__).parent / "golden"
INPUTS = GOLDEN / "inputs"
MANIFEST = GOLDEN / "manifest.json"
PROFILE = os.environ.get("GOLDEN_PROFILE")
UPDATE = os.environ.get("GOLDEN_UPDATE") == "1"


def _toolchain(profile):
    def first(*cmd):
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.splitlines()[0]
    if profile == "media":
        return first("ffmpeg", "-version")
    if profile == "pandoc":
        return first("pandoc", "--version") + "; " + first("pdflatex", "--version")
    return first("office2pdf", "--version")


def _cases():
    from publishing import convert as cv, media, pandoc
    md, html, docx, odt = (INPUTS / n for n in ("note.md", "page.html", "note.docx", "note.odt"))
    a, b = INPUTS / "clip-a.mp4", INPUTS / "clip-b.mp4"
    return {
        "media": {
            "audio.mp3": lambda o: media.audio(a, o),
            "audio.m4a": lambda o: media.audio(a, o),
            "audio.opus": lambda o: media.audio(a, o),
            "audio.ogg": lambda o: media.audio(a, o),
            "audio.flac": lambda o: media.audio(a, o),
            "audio.wav": lambda o: media.audio(a, o),
            "audio-64k.mp3": lambda o: media.audio(a, o, bitrate="64k"),
            "video.mp4": lambda o: media.video(a, o),
            "video-h32.mp4": lambda o: media.video(a, o, height=32, crf=30),
            "video.webm": lambda o: media.video(a, o),
            "video.mkv": lambda o: media.video(a, o),
            "thumbnail.png": lambda o: media.thumbnail(a, o, at=0.5),
            "thumbnail-w32.jpg": lambda o: media.thumbnail(a, o, at=0.5, width=32),
            "concat.mp4": lambda o: media.concat([a, b], o),
        },
        "pandoc": {
            "md.html": lambda o: pandoc.convert(md, o),
            "md.docx": lambda o: pandoc.convert(md, o),
            "md.pdf": lambda o: pandoc.convert(md, o),
            "html.docx": lambda o: pandoc.convert(html, o),
            "html.pdf": lambda o: pandoc.convert(html, o),
            "docx.html": lambda o: pandoc.convert(docx, o),
            "docx.pdf": lambda o: pandoc.convert(docx, o),
            "odt.html": lambda o: pandoc.convert(odt, o),
        },
        "convert": {
            "minimal.pdf": lambda o: cv.convert(INPUTS / "minimal.docx", o),
        },
    }


def _load():
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check(profile, name, tmp_path):
    if PROFILE != profile:
        pytest.skip(f"golden {profile} cases run in the {profile} image (GOLDEN_PROFILE={profile})")
    out = tmp_path / name
    _cases()[profile][name](out)
    got = {"sha256": _sha(out), "bytes": out.stat().st_size}
    manifest = _load()
    section = manifest.setdefault(profile, {"toolchain": "", "outputs": {}})
    if UPDATE:
        section["toolchain"] = _toolchain(profile)
        section["outputs"][name] = got
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        return
    want = section["outputs"].get(name)
    assert want, f"{profile}/{name} has no golden entry; GOLDEN_UPDATE=1 writes it"
    assert got == want, (
        f"{profile}/{name} changed: sha256 {got['sha256']} ({got['bytes']} B), golden {want['sha256']} "
        f"({want['bytes']} B). Toolchain now: {_toolchain(profile)}; golden: {section['toolchain']}. "
        "If the bump is intended, regenerate with GOLDEN_UPDATE=1 and commit tests/golden/manifest.json.")


def _names(profile):
    return sorted(_cases()[profile])


@pytest.mark.parametrize("name", _names("media"))
def test_golden_media(name, tmp_path):
    _check("media", name, tmp_path)


@pytest.mark.parametrize("name", _names("pandoc"))
def test_golden_pandoc(name, tmp_path):
    _check("pandoc", name, tmp_path)


@pytest.mark.parametrize("name", _names("convert"))
def test_golden_convert(name, tmp_path):
    _check("convert", name, tmp_path)


@pytest.mark.skipif(PROFILE is None or UPDATE, reason="runs in a profile image, not while regenerating")
def test_manifest_lists_exactly_the_cases():
    assert sorted(_load().get(PROFILE, {}).get("outputs", {})) == _names(PROFILE)
