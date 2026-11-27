"""Tests for motion audit (publishing.motion): jumps, pops, flashes, frozen holds, and film strip."""
from __future__ import annotations

import subprocess
from pathlib import Path

from publishing import motion, video


def _encode(path: Path, vf: str, dur: float = 3.0, fps: int = 15) -> Path:
    sep = ":" if "=" in vf else "="
    subprocess.run(
        [video.ff("ffmpeg"), "-v", "error", "-y",
         "-f", "lavfi", "-i", f"{vf}{sep}size=320x180:rate={fps}:duration={dur}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )
    return path


def test_frozen_hold_detected(tmp_path):
    mp4 = _encode(tmp_path / "still.mp4", "color=c=black", dur=3.0)
    r = motion.audit_motion(mp4, fps=15.0, hold_seconds=1.5)
    assert r["ok"] is True
    assert len(r["frozen_holds"]) == 1
    assert r["frozen_holds"][0]["duration"] >= 2.5
    assert r["jumps"] == []
    assert r["flashes"] == []


def test_smooth_motion_has_no_frozen_holds_or_flashes(tmp_path):
    # testsrc2 moves continuously every frame
    mp4 = _encode(tmp_path / "moving.mp4", "testsrc2", dur=2.5)
    strip = tmp_path / "strip.png"
    r = motion.audit_motion(mp4, fps=15.0, hold_seconds=1.0, strip_out=strip)
    assert r["ok"] is True
    assert r["frozen_holds"] == []
    assert r["flashes"] == []
    assert strip.is_file()


def test_rapid_flashing_fails_wcag_flash_gate(tmp_path):
    # Alternate black and white every 2 frames at 15 fps (~7.5 transitions/s -> >3 flashes/s)
    mp4 = tmp_path / "flash.mp4"
    subprocess.run(
        [video.ff("ffmpeg"), "-v", "error", "-y",
         "-f", "lavfi", "-i", "color=c=black:size=320x180:rate=15:duration=2",
         "-vf", "geq=lum='if(mod(floor(N/2),2),240,16)':cb=128:cr=128",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(mp4)],
        check=True,
    )
    r = motion.audit_motion(mp4, fps=15.0)
    assert r["ok"] is False
    assert len(r["flashes"]) >= 1
    assert len(r["jumps"]) >= 4
    assert len(r["pops"]) >= 1
