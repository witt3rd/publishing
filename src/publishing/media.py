"""Audio and video through ffmpeg: `publishing media audio|video|thumbnail|concat`, and the functions
below for callers in Python.

The standard library only; ffmpeg and ffprobe come from the PATH (the `media` image pins them: README
"Media"). Every ffmpeg runs in its own process group, so the time limit and the output cap are enforced
on a process that can be killed.

- In: local files with a media suffix (SUFFIXES), by path. A name that is a URL, a device or a pipe is
  refused; ffmpeg is run with `-protocol_whitelist file`, so even a playlist or a concat list inside a
  file cannot name anything but a local file. Nothing is downloaded or uploaded.
- Out: one file whose format is its suffix, written beside nothing else: a temporary file in the same
  folder is moved into place, so an interrupted run leaves no partial OUT. An existing OUT is never
  overwritten (exit 2). The path is the only line on stdout.
- Deterministic: no metadata copied from the source, bit-exact muxing, one encoder thread. The same
  ffmpeg build turns the same input into the same bytes.
- Limits: TIMEOUT seconds of wall clock, MAX_BYTES of output (enforced while it grows and passed to
  ffmpeg as -fs), and MAX_SECONDS of input duration (checked with ffprobe before encoding).

Exit codes of the command: 0 done, 1 ffmpeg failed or a limit was hit, 2 usage (unsupported type, no
such source, the output exists), 3 ffmpeg or ffprobe not found.
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

AUDIO_SUFFIXES = (".mp3", ".m4a", ".opus", ".ogg", ".flac", ".wav")
VIDEO_SUFFIXES = (".mp4", ".webm", ".mkv", ".mov")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")
INPUT_SUFFIXES = AUDIO_SUFFIXES + VIDEO_SUFFIXES + (".aac", ".avi", ".m4v")
TIMEOUT = 300.0  # seconds of wall clock per ffmpeg
MAX_BYTES = 512 * 2**20
MAX_SECONDS = 3600.0  # input duration
STDERR_CHARS = 400
_POLL = 0.05

# Codec by output suffix: (video, audio). None: the output has no such stream.
_AUDIO = {".mp3": "libmp3lame", ".m4a": "aac", ".opus": "libopus", ".ogg": "libvorbis", ".flac": "flac",
          ".wav": "pcm_s16le"}
_VIDEO = {".mp4": ("libx264", "aac"), ".mkv": ("libx264", "aac"), ".mov": ("libx264", "aac"),
          ".webm": ("libvpx-vp9", "libopus")}
_DETERMINISTIC = ["-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                  "-flags:a", "+bitexact", "-threads", "1"]


class MediaError(Exception):
    """ffmpeg failed, or a limit was hit (exit 1). Subclasses carry their own exit code."""
    exit_code = 1


class UsageError(MediaError):
    exit_code = 2


class ToolNotFound(MediaError):
    exit_code = 3


def _tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise ToolNotFound(f"{name} not found (use the media image, or install ffmpeg)")
    return path


def _source(src, kinds=INPUT_SUFFIXES) -> Path:
    text = str(src)
    path = Path(text)
    if "://" in text or text.startswith(("-", "pipe:", "/dev/")) or path.suffix.lower() not in kinds:
        raise UsageError(f"{text}: not a supported local media file ({', '.join(kinds)})")
    if not path.is_file():
        raise UsageError(f"{text}: no such file")
    return path.resolve()


def _dest(out, kinds) -> Path:
    path = Path(out)
    if path.suffix.lower() not in kinds:
        raise UsageError(f"{path}: output must be one of {', '.join(kinds)}")
    if path.exists():
        raise UsageError(f"{path} exists; never overwrite")
    return path


def duration(src: Path) -> float:
    """The container's duration in seconds (ffprobe)."""
    proc = subprocess.run([_tool("ffprobe"), "-v", "error", "-protocol_whitelist", "file", "-show_entries",
                           "format=duration", "-of", "json", str(src)], stdin=subprocess.DEVNULL,
                          capture_output=True, timeout=60)
    try:
        return float(json.loads(proc.stdout)["format"]["duration"])
    except (ValueError, KeyError, TypeError):
        raise MediaError(f"{src.name}: not readable as media ({_clip(proc.stderr)})") from None


def _clip(raw: bytes) -> str:
    text = " ".join(raw[:16 * STDERR_CHARS].decode("utf-8", "replace").split())
    return text[-STDERR_CHARS:]


def _check_duration(sources, max_seconds: float) -> None:
    total = sum(duration(s) for s in sources)
    if total > max_seconds:
        raise MediaError(f"input is {total:g} s, over the {max_seconds:g} s cap")


def _encode(args: list[str], dest: Path, sources, *, timeout, max_bytes, max_seconds, pre=()) -> Path:
    """Run ffmpeg (`pre` options, then each source as -i, then `args`) to a temporary file, then move it
    to `dest` unless `dest` appeared meanwhile."""
    ffmpeg = _tool("ffmpeg")
    _check_duration(sources, max_seconds)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="publishing-media-", dir=dest.parent))
    try:
        out = temporary / ("out" + dest.suffix.lower())
        cmd = [ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "file", *pre]
        for s in sources:
            cmd += ["-i", str(s)]
        cmd += [*args, *_DETERMINISTIC, "-fs", str(max_bytes), str(out)]
        err = temporary / "stderr"
        _run(cmd, out, err, timeout, max_bytes)
        if not out.is_file() or out.stat().st_size == 0:
            raise MediaError("ffmpeg wrote nothing")
        try:
            os.link(out, dest)  # fails if dest exists: never overwrite
        except FileExistsError:
            raise UsageError(f"{dest} exists; never overwrite") from None
        return dest
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _run(cmd, out: Path, err_path: Path, timeout: float, max_bytes: int) -> None:
    with open(err_path, "wb") as err:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err,
                                start_new_session=True)
        try:
            deadline = time.monotonic() + timeout
            while proc.poll() is None:
                if time.monotonic() >= deadline:
                    raise MediaError(f"ffmpeg timed out after {timeout:g} s")
                if out.exists() and out.stat().st_size > max_bytes:
                    raise MediaError(f"output is over the {max_bytes}-byte cap")
                try:
                    proc.wait(timeout=_POLL)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
    if proc.returncode != 0:
        with open(err_path, "rb") as f:
            text = _clip(f.read())
        raise MediaError(text or f"ffmpeg failed ({proc.returncode})")
    if out.exists() and out.stat().st_size >= max_bytes:  # -fs stops at the cap and exits 0
        raise MediaError(f"output reached the {max_bytes}-byte cap")


def audio(src, dest, *, bitrate: str | None = None, timeout=TIMEOUT, max_bytes=MAX_BYTES,
          max_seconds=MAX_SECONDS) -> Path:
    """The audio of `src` (audio or video) transcoded to `dest`, the format its suffix names."""
    src, dest = _source(src), _dest(dest, AUDIO_SUFFIXES)
    args = ["-vn", "-c:a", _AUDIO[dest.suffix.lower()]]
    if bitrate and dest.suffix.lower() not in (".flac", ".wav"):
        args += ["-b:a", bitrate]
    return _encode(args, dest, [src], timeout=timeout, max_bytes=max_bytes, max_seconds=max_seconds)


def video(src, dest, *, height: int | None = None, crf: int = 23, timeout=TIMEOUT, max_bytes=MAX_BYTES,
          max_seconds=MAX_SECONDS) -> Path:
    """`src` transcoded to `dest` (.mp4 H.264+AAC, .webm VP9+Opus, ...), scaled to `height` if given."""
    src, dest = _source(src, VIDEO_SUFFIXES + (".avi", ".m4v")), _dest(dest, VIDEO_SUFFIXES)
    vcodec, acodec = _VIDEO[dest.suffix.lower()]
    args = ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", vcodec, "-c:a", acodec]
    if vcodec == "libx264":
        args += ["-crf", str(crf), "-preset", "medium", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    else:
        args += ["-crf", str(crf), "-b:v", "0", "-pix_fmt", "yuv420p"]
    if height:
        args += ["-vf", f"scale=-2:{height}"]
    return _encode(args, dest, [src], timeout=timeout, max_bytes=max_bytes, max_seconds=max_seconds)


def thumbnail(src, dest, *, at: float = 0.0, width: int | None = None, timeout=TIMEOUT,
              max_bytes=MAX_BYTES, max_seconds=MAX_SECONDS) -> Path:
    """One frame of the video `src`, `at` seconds in, as the image `dest` (.png, .jpg), `width` wide if given."""
    src, dest = _source(src, VIDEO_SUFFIXES + (".avi", ".m4v")), _dest(dest, IMAGE_SUFFIXES)
    if at < 0 or at > duration(src):
        raise UsageError(f"--at {at:g} is outside the video (0 to {duration(src):g} s)")
    args = ["-map", "0:v:0", "-frames:v", "1"]
    if width:
        args += ["-vf", f"scale={width}:-2"]
    if dest.suffix.lower() in (".jpg", ".jpeg"):
        args += ["-q:v", "3", "-pix_fmt", "yuvj420p"]
    return _encode(args, dest, [src], pre=["-ss", f"{at:.3f}"], timeout=timeout, max_bytes=max_bytes,
                   max_seconds=max_seconds)


def concat(sources, dest, *, timeout=TIMEOUT, max_bytes=MAX_BYTES, max_seconds=MAX_SECONDS) -> Path:
    """The files `sources`, in order, joined into `dest` without re-encoding. They must share a codec,
    size and rate (ffmpeg's concat demuxer); a mismatch is an error, not a silent re-encode."""
    sources = [_source(s) for s in sources]
    if len(sources) < 2:
        raise UsageError("concat needs at least two files")
    dest = _dest(dest, AUDIO_SUFFIXES + VIDEO_SUFFIXES)
    kinds = {s.suffix.lower() for s in sources}
    if len(kinds) != 1:
        raise UsageError(f"concat needs one file type, got {', '.join(sorted(kinds))}")
    _check_duration(sources, max_seconds)
    dest.parent.mkdir(parents=True, exist_ok=True)
    listing = Path(tempfile.mkdtemp(prefix="publishing-media-list-"))
    try:
        lst = listing / "list.txt"
        lst.write_text("".join("file '{}'\n".format(str(s).replace("'", "'\\''")) for s in sources))
        ffmpeg = _tool("ffmpeg")
        temporary = Path(tempfile.mkdtemp(prefix="publishing-media-", dir=dest.parent))
        try:
            out = temporary / ("out" + dest.suffix.lower())
            cmd = [ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "file", "-f", "concat",
                   "-safe", "0", "-i", str(lst), "-c", "copy", *_DETERMINISTIC, "-fs", str(max_bytes), str(out)]
            _run(cmd, out, temporary / "stderr", timeout, max_bytes)
            if not out.is_file() or out.stat().st_size == 0:
                raise MediaError("ffmpeg wrote nothing")
            try:
                os.link(out, dest)
            except FileExistsError:
                raise UsageError(f"{dest} exists; never overwrite") from None
            return dest
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
    finally:
        shutil.rmtree(listing, ignore_errors=True)


# --- the command ------------------------------------------------------------------------------

def _positive(kind):
    def parse(text):
        try:
            value = kind(text)
        except ValueError:
            value = 0
        if value <= 0:
            raise argparse.ArgumentTypeError(f"{text!r} is not a positive number")
        return value
    return parse


def _nonneg(text):
    try:
        value = float(text)
    except ValueError:
        value = -1
    if value < 0:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number of seconds, 0 or more")
    return value


def _limits(p) -> None:
    p.add_argument("--timeout", type=_positive(float), default=TIMEOUT, metavar="SECONDS",
                   help=f"stop ffmpeg after this long (default {TIMEOUT:g})")
    p.add_argument("--max-bytes", type=_positive(int), default=MAX_BYTES, metavar="N",
                   help=f"refuse an output larger than this (default {MAX_BYTES})")
    p.add_argument("--max-seconds", type=_positive(float), default=MAX_SECONDS, metavar="SECONDS",
                   help=f"refuse input longer than this (default {MAX_SECONDS:g})")
    p.set_defaults(fn=run, needs_render=False)


def add_arguments(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="media_cmd", required=True, metavar="{audio,video,thumbnail,concat}")
    a = sub.add_parser("audio", help="transcode the audio of a file: " + " ".join(AUDIO_SUFFIXES))
    a.add_argument("src")
    a.add_argument("-o", "--output", required=True, help="the audio path; its suffix picks the codec")
    a.add_argument("--bitrate", metavar="RATE", help="for lossy codecs, e.g. 128k")
    _limits(a)
    v = sub.add_parser("video", help="transcode a video: " + " ".join(VIDEO_SUFFIXES))
    v.add_argument("src")
    v.add_argument("-o", "--output", required=True, help="the video path; its suffix picks the codecs")
    v.add_argument("--height", type=_positive(int), help="scale to this height, keeping the aspect ratio")
    v.add_argument("--crf", type=int, choices=range(0, 52), metavar="0-51", default=23, help="quality (default 23)")
    _limits(v)
    t = sub.add_parser("thumbnail", help="one frame of a video as " + " ".join(IMAGE_SUFFIXES))
    t.add_argument("src")
    t.add_argument("-o", "--output", required=True, help="the image path")
    t.add_argument("--at", type=_nonneg, default=0.0, metavar="SECONDS", help="the frame's time (default 0)")
    t.add_argument("--width", type=_positive(int), help="scale to this width")
    _limits(t)
    c = sub.add_parser("concat", help="join files of one type, without re-encoding")
    c.add_argument("src", nargs="+", help="two or more files, in order")
    c.add_argument("-o", "--output", required=True, help="the joined file")
    _limits(c)


def run(a) -> int:
    kw = dict(timeout=a.timeout, max_bytes=a.max_bytes, max_seconds=a.max_seconds)
    try:
        if a.media_cmd == "audio":
            dest = audio(a.src, a.output, bitrate=a.bitrate, **kw)
        elif a.media_cmd == "video":
            dest = video(a.src, a.output, height=a.height, crf=a.crf, **kw)
        elif a.media_cmd == "thumbnail":
            dest = thumbnail(a.src, a.output, at=a.at, width=a.width, **kw)
        else:
            dest = concat(a.src, a.output, **kw)
    except MediaError as e:
        print(f"publishing: {e}", file=sys.stderr)
        return e.exit_code
    print(dest)
    return 0
