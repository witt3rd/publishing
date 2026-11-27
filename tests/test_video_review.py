"""Tests for key stills, contact-sheet tiling, and -16 LUFS loudness normalization."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image

from publishing import video


def _make_demo_mp4(path: Path) -> Path:
    # 3-second synthetic video (colorbars + quiet 440 Hz tone at -30 dB) via ffmpeg.
    subprocess.run(
        [video.ff("ffmpeg"), "-v", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=10:duration=3",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3,volume=-30dB",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", str(path)],
        check=True,
    )
    return path


def test_stills_and_contact_sheet(tmp_path):
    mp4 = _make_demo_mp4(tmp_path / "demo.mp4")
    frames = video.stills(mp4, tmp_path / "stills", [0.2, 1.5, 2.7], width=320)
    assert len(frames) == 3
    for f in frames:
        assert f.is_file()
        with Image.open(f) as im:
            assert im.width == 320

    sheet = video.contact_sheet(frames, tmp_path / "sheet.png", cols=2, tile_width=200, pad=10)
    assert sheet.is_file()
    with Image.open(sheet) as im:
        # 2 cols * 200 + 3 * 10 = 430 wide; 2 rows tall
        assert im.width == 430
        assert im.height > 200


def test_loudness_measure_and_normalize(tmp_path):
    mp4 = _make_demo_mp4(tmp_path / "quiet.mp4")
    before = video.loudness(mp4)
    assert before["lufs"] < -22.0  # synthetic -30 dB sine is well below -16 LUFS

    norm_mp4 = video.normalize_loudness(mp4, tmp_path / "norm.mp4", i=-16.0, tp=-1.5)
    assert norm_mp4.is_file()
    after = video.loudness(norm_mp4)
    assert -18.0 <= after["lufs"] <= -14.0
    assert after["true_peak"] <= -1.0
