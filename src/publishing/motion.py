"""Motion audit for rendered MP4s: judge animation without watching it.

Inspired by `cinematic-deck-playbook/tools/motion.mjs`:
decodes an MP4 at 160x90 grayscale via ffmpeg and reports:
  1. One-frame brightness JUMPS (mean luma delta >= jump_thr)
  2. Brightness POPS (a jump that returns within pop_window seconds — stale buffer / snap)
  3. WCAG 2.3.1-style FLASHES (> 3 significant luminance reversals in any 1-second window)
  4. FROZEN HOLDS (stretches >= hold_seconds with mean frame-to-frame motion < still_thr)
  5. Optional film strip PNG at the moment of fastest motion (via video.stills + contact_sheet)

Pure Python + ffmpeg (already required by publishing.video).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from publishing import video

_W, _H = 160, 90
_N = _W * _H


def _decode_luma_frames(mp4: Path, fps: float) -> list[bytes]:
    """Decode `mp4` to 160x90 8-bit grayscale frames at `fps`."""
    p = subprocess.run(
        [video.ff("ffmpeg"), "-v", "error", "-i", str(mp4),
         "-vf", f"fps={fps:g},scale={_W}:{_H}:flags=area,format=gray",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True,
    )
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg decode failed (exit {p.returncode}): {p.stderr.decode(errors='replace').strip()[-400:]}")
    raw = p.stdout
    count = len(raw) // _N
    return [raw[i * _N : (i + 1) * _N] for i in range(count)]


def _mean_abs_diff(a: bytes, b: bytes) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / _N


def audit_motion(
    mp4: Path,
    *,
    fps: float = 15.0,
    jump_thr: float = 8.0,
    pop_thr: float = 10.0,
    pop_window: float = 0.25,
    flash_delta: float = 20.0,
    max_flashes_per_sec: int = 3,
    still_thr: float = 0.3,
    hold_seconds: float = 2.0,
    strip_out: Path | None = None,
) -> dict:
    """Audit motion in `mp4`. Returns metrics, findings lists, and `ok` (False on flash violations)."""
    mp4 = Path(mp4)
    frames = _decode_luma_frames(mp4, fps)
    n = len(frames)
    if n == 0:
        return {"frames": 0, "fps": fps, "jumps": [], "pops": [], "flashes": [],
                "frozen_holds": [], "peak_motion_t": 0.0, "ok": True, "strip": None}

    means = [sum(f) / _N for f in frames]
    diffs = [0.0] + [_mean_abs_diff(frames[i], frames[i - 1]) for i in range(1, n)]

    # 1. Brightness jumps
    jumps: list[dict] = []
    for i in range(1, n):
        delta = means[i] - means[i - 1]
        if abs(delta) >= jump_thr:
            jumps.append({"frame": i, "t": round(i / fps, 3), "delta": round(delta, 2)})

    # 2. Brightness pops (excursion >= pop_thr that returns near baseline within pop_window)
    pops: list[dict] = []
    win_f = max(2, round(pop_window * fps))
    for i in range(1, n):
        base = means[i - 1]
        delta = means[i] - base
        if abs(delta) < pop_thr:
            continue
        for j in range(i + 1, min(n, i + win_f + 1)):
            if abs(means[j] - base) <= abs(delta) * 0.35:
                pops.append({"frame": i, "t": round(i / fps, 3), "delta": round(delta, 2),
                             "return_t": round(j / fps, 3)})
                break

    # 3. WCAG 2.3.1-style flashes: count opposing brightness transitions >= flash_delta in any 1s window
    transitions: list[tuple[int, int]] = []  # (frame, sign +1/-1)
    for i in range(1, n):
        d = means[i] - means[i - 1]
        if abs(d) >= flash_delta:
            sign = 1 if d > 0 else -1
            if not transitions or transitions[-1][1] != sign:
                transitions.append((i, sign))
    # Each pair of opposing transitions is one flash; count flashes in any 1-second sliding window.
    flash_frames = [transitions[k][0] for k in range(1, len(transitions))]
    flashes: list[dict] = []
    sec_f = max(1, round(fps))
    left = 0
    for right, f_idx in enumerate(flash_frames):
        while f_idx - flash_frames[left] > sec_f:
            left += 1
        count = right - left + 1
        if count > max_flashes_per_sec:
            flashes.append({"t": round(f_idx / fps, 3), "count_1s": count})

    # 4. Frozen holds: contiguous runs of diffs < still_thr lasting >= hold_seconds
    frozen_holds: list[dict] = []
    min_run = max(2, round(hold_seconds * fps))
    i = 1
    while i < n:
        if diffs[i] >= still_thr:
            i += 1
            continue
        j = i
        while j < n and diffs[j] < still_thr:
            j += 1
        if j - i >= min_run:
            frozen_holds.append({
                "start": round((i - 1) / fps, 3),
                "end": round((j - 1) / fps, 3),
                "duration": round((j - i) / fps, 3),
            })
        i = j

    # Peak motion timestamp + optional 6-frame film strip around it
    peak_i = max(range(n), key=lambda k: diffs[k])
    peak_t = round(peak_i / fps, 3)
    strip_path: Path | None = None
    if strip_out is not None:
        import tempfile
        strip_out = Path(strip_out)
        dur = (n - 1) / fps
        times = [max(0.0, min(dur, peak_t + (k - 2.5) / min(fps, 30.0))) for k in range(6)]
        with tempfile.TemporaryDirectory(prefix="publishing-motion-") as tmp:
            frames_png = video.stills(mp4, Path(tmp), times, width=640)
            strip_path = video.contact_sheet(frames_png, strip_out, cols=6, tile_width=320, pad=4)

    return {
        "frames": n,
        "fps": fps,
        "jumps": jumps,
        "pops": pops,
        "flashes": flashes,
        "frozen_holds": frozen_holds,
        "peak_motion_t": peak_t,
        "ok": len(flashes) == 0,
        "strip": str(strip_path) if strip_path else None,
    }
