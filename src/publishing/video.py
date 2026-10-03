"""The video format: a folder with video.html (a HyperFrames composition) to a deterministic MP4.

  <topic>-vN/video.html   the composition: scenes are deck slides styled by theme/video.css,
                          motion is CSS animation that HyperFrames seeks frame by frame
  <topic>-vN.mp4          the video, beside the folder, committed

The renderer is pinned, like the PDF one:
  HyperFrames   hyperframes/package-lock.json (exact version and every dependency, by hash),
                installed by `publishing setup --video` and run on the Node of the `video` extra
  Chromium      the Playwright headless shell that `publishing setup` already installs
  ffmpeg        the host's, or HYPERFRAMES_FFMPEG_PATH / HYPERFRAMES_FFPROBE_PATH; the image pins one
  fonts         the vendored house fonts; nothing loads from the network

A build stages the folder with the theme (video.html becomes index.html, the theme sits in
_publishing/), gates it (the house scan and font check, then `hyperframes check`: lint, runtime
errors, layout, contrast), renders it and stamps the MP4 with the sha256 of its source folder.

Determinism: the same toolchain renders the same bytes. Another ffmpeg build encodes the same
frames slightly differently, so `check` accepts a fresh render whose frames match the committed
ones exactly, or within `[video] tolerance` dB PSNR (default 40), and only when the committed MP4
was built from the same source (its stamp).
"""
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from importlib import resources
from pathlib import Path

from . import __version__, scan
from .render import ToolchainError

STAGE_THEME = "_publishing"
STAMP = re.compile(r"source sha256:([0-9a-f]{64})")


# ---------------------------------------------------------------- toolchain

def _pkg() -> Path:
    return Path(str(resources.files("publishing").joinpath("hyperframes"))).resolve()


def hyperframes_version() -> str:
    return json.loads((_pkg() / "package.json").read_text())["dependencies"]["hyperframes"]


def cache_root() -> Path:
    if os.environ.get("PUBLISHING_CACHE"):
        return Path(os.environ["PUBLISHING_CACHE"])
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "publishing"


def install_dir() -> Path:
    """One directory per lockfile: a new pin installs beside the old one, never over it."""
    lock = hashlib.sha256((_pkg() / "package-lock.json").read_bytes()).hexdigest()[:12]
    return cache_root() / f"hyperframes-{hyperframes_version()}-{lock}"


def _node_root() -> Path:
    try:
        import nodejs_wheel
    except ImportError:
        raise ToolchainError("the video format needs the `video` extra (its pinned Node): install "
                             "'publishing[video] @ git+https://github.com/witt3rd/publishing@v"
                             f"{__version__}', or use the container image") from None
    return Path(nodejs_wheel.__file__).parent


def _node() -> str:
    root = _node_root()
    return str(root / "node.exe" if os.name == "nt" else root / "bin" / "node")


def _node_dir() -> Path:
    return Path(_node()).parent


def _npm_cli() -> Path:
    return _node_root() / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"


def setup() -> int:
    """Install the pinned HyperFrames (npm ci, no install scripts) into the cache."""
    target = install_dir()
    if (target / "node_modules" / "hyperframes" / "package.json").is_file():
        print(f"hyperframes {hyperframes_version()} already installed: {target}")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".install-", dir=target.parent))
    try:
        for f in ("package.json", "package-lock.json"):
            shutil.copyfile(_pkg() / f, work / f)
        env = {**os.environ, "PATH": f"{_node_dir()}{os.pathsep}{os.environ.get('PATH', '')}",
               "npm_config_cache": str(cache_root() / "npm"), "npm_config_update_notifier": "false"}
        code = subprocess.call([_node(), str(_npm_cli()), "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
                               cwd=work, env=env)
        if code:
            return code
        work.rename(target)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"installed hyperframes {hyperframes_version()}: {target}")
    return 0


def _cli() -> Path:
    cli = install_dir() / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
    if not cli.is_file():
        raise ToolchainError(f"hyperframes {hyperframes_version()} is not installed. Run `publishing setup --video` "
                             "once (it installs into the user cache; PUBLISHING_CACHE moves it).")
    return cli


def headless_shell() -> Path:
    """Playwright's Chromium headless shell for the pinned Playwright: the same build as the PDFs."""
    import playwright

    pkg = Path(playwright.__file__).parent
    browsers = json.loads((pkg / "driver" / "package" / "browsers.json").read_text())["browsers"]
    rev = next(b["revision"] for b in browsers if b["name"] == "chromium-headless-shell")
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    root = (pkg / "driver" / "package" / ".local-browsers" if base == "0" else Path(base) if base
            else Path.home() / "Library" / "Caches" / "ms-playwright" if sys.platform == "darwin"
            else Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright" if os.name == "nt"
            else Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "ms-playwright")
    folder = root / f"chromium_headless_shell-{rev}"
    found = sorted(p for name in ("chrome-headless-shell", "headless_shell", "chrome-headless-shell.exe")
                   for p in folder.glob(f"*/{name}") if p.is_file())
    if not found:
        raise ToolchainError(f"Chromium headless shell {rev} is not installed. Run `publishing setup` once.")
    return found[0]


def ff(name: str) -> str:
    """ffmpeg or ffprobe: HYPERFRAMES_FFMPEG_PATH / HYPERFRAMES_FFPROBE_PATH, else the PATH."""
    path = os.environ.get(f"HYPERFRAMES_{name.upper()}_PATH") or shutil.which(name)
    if not path or not Path(path).is_file():
        raise ToolchainError(f"{name} not found: install FFmpeg, or set HYPERFRAMES_{name.upper()}_PATH")
    return path


def _env(home: Path) -> dict:
    """HyperFrames runs with a private HOME (it writes its config and caches there), no telemetry,
    no update check, the pinned browser and ffmpeg, and deterministic capture."""
    browser = str(headless_shell())
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HYPERFRAMES_", "PRODUCER_"))}
    env.update({
        "HOME": str(home), "PATH": f"{_node_dir()}{os.pathsep}{os.environ.get('PATH', '')}",
        "HYPERFRAMES_BROWSER_PATH": browser, "PRODUCER_HEADLESS_SHELL_PATH": browser,
        "HYPERFRAMES_FFMPEG_PATH": ff("ffmpeg"), "HYPERFRAMES_FFPROBE_PATH": ff("ffprobe"),
        "HYPERFRAMES_NO_TELEMETRY": "1", "HYPERFRAMES_NO_UPDATE_CHECK": "1", "DO_NOT_TRACK": "1", "CI": "1",
        # BeginFrame capture even on the software GPU: HyperFrames falls back to screenshots there,
        # which race the compositor on animated transforms (frames then differ run to run).
        "PRODUCER_FORCE_SCREENSHOT": "false",
    })
    return env


def _hyperframes(args: list[str], home: Path) -> subprocess.CompletedProcess:
    return subprocess.run([_node(), str(_cli()), *args], env=_env(home), capture_output=True, text=True)


# ---------------------------------------------------------------- source

def digest(folder: Path) -> str:
    """sha256 over the source folder's files (relative paths and bytes)."""
    h = hashlib.sha256()
    for f in sorted(p for p in folder.rglob("*") if p.is_file()):
        rel = f.relative_to(folder).as_posix()
        if any(part.startswith(".") or part == "__pycache__" for part in rel.split("/")):
            continue  # what stage() leaves out
        h.update(rel.encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def stage(src: Path, dest: Path) -> Path:
    """Copy the source folder to `dest` as a HyperFrames project; return its index.html."""
    for reserved in ("index.html", STAGE_THEME):
        if (src / reserved).exists():
            raise ValueError(f"{src.name}/{reserved}: reserved in a video folder (the composition is video.html)")
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", ".*"))
    theme = Path(str(resources.files("publishing").joinpath("theme")))
    shutil.copytree(theme, dest / STAGE_THEME)
    html = (dest / "video.html").read_text()
    link = f'<link rel="stylesheet" href="{STAGE_THEME}/video.css">'
    m = re.search(r"<head[^>]*>", html, re.I)
    html = html[:m.end()] + link + html[m.end():] if m else link + html
    (dest / "video.html").unlink()
    index = dest / "index.html"
    index.write_text(html)
    return index


def families() -> list[str]:
    css = Path(str(resources.files("publishing").joinpath("theme", "house.css"))).read_text()
    return sorted(set(re.findall(r'font-family:\s*"([^"]+)";\s*src:', css)))


def _source_text(folder: Path) -> str:
    """Text of sub-compositions and other HTML (not in the page until HyperFrames mounts it)."""
    out = []
    for f in sorted(folder.rglob("*.html")):
        if f.name != "index.html" and STAGE_THEME not in f.parts:
            out.append(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", f.read_text())))
    return "\n".join(out)


def _check_findings(report: dict) -> list[str]:
    seen, out = set(), []
    for section in ("lint", "runtime", "layout", "motion", "contrast"):
        for f in (report.get(section) or {}).get("findings", []):
            if f.get("severity") != "error" or (f.get("code"), f.get("selector")) in seen:
                continue
            seen.add((f.get("code"), f.get("selector")))
            where = f" at {f['selector']}" if f.get("selector") else ""
            when = f", {f['time']:g}s" if isinstance(f.get("time"), (int, float)) and f["time"] else ""
            out.append(f"{f.get('code')}{where}{when}: {f.get('message', '').strip()}")
    return out


def render(src: Path, cfg, out: Path, r, *, words=True, days=True) -> list[str]:
    """Gate and render the folder `src` to `out` (a scratch path). Returns every problem; empty is clean."""
    with tempfile.TemporaryDirectory(prefix="publishing-video-") as tmp:
        tmp = Path(tmp)
        try:
            index = stage(src, tmp / "project")
        except ValueError as e:
            return [str(e)]
        result, remote = r.inspect(index, families())
        problems = list(result["problems"]) + [f"loads from the network (a render must be offline): {u}" for u in remote]
        text = result["text"] + "\n" + _source_text(tmp / "project")
        problems += scan.scan(text, words=cfg.words if words else (), allow=cfg.allow, days=days)
        if problems:
            return problems
        home = tmp / "home"
        home.mkdir()
        p = _hyperframes(["check", str(index.parent), "--json", "--no-browser-gpu"], home)
        try:
            report = json.loads(p.stdout)
        except json.JSONDecodeError:
            return [f"hyperframes check failed (exit {p.returncode}): {(p.stderr or p.stdout).strip()[-800:]}"]
        if not report.get("ok"):
            return _check_findings(report) or [f"hyperframes check failed: {p.stdout.strip()[-800:]}"]
        raw = tmp / "render.mp4"
        p = _hyperframes(["render", str(index.parent), "-o", str(raw), "--workers", "1", "--no-browser-gpu",
                          "--quality", "looks", "--no-best-effort", "--strict", "--frames-cache-dir", "off",
                          "--quiet"], home)
        if p.returncode or not raw.is_file():
            return [f"hyperframes render failed (exit {p.returncode}): {(p.stderr or p.stdout).strip()[-800:]}"]
        _stamp(raw, out, digest(src))
    return []


def _run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise ToolchainError(f"{Path(cmd[0]).name} failed: {p.stderr.strip()[-500:]}")
    return p.stdout


def _stamp(raw: Path, out: Path, source: str) -> None:
    """Remux (no re-encode) with the source digest in the comment tag, keeping HyperFrames'
    provenance tags; bit-exact muxing, so the same frames give the same bytes."""
    tags = json.loads(_run([ff("ffprobe"), "-v", "error", "-show_entries", "format_tags", "-of", "json", str(raw)]))
    keep = {k: v for k, v in (tags.get("format", {}).get("tags") or {}).items() if k.startswith("hyperframes_")}
    keep["comment"] = f"publishing {__version__} source sha256:{source}"
    meta = [x for k, v in sorted(keep.items()) for x in ("-metadata", f"{k}={v}")]
    _run([ff("ffmpeg"), "-v", "error", "-y", "-i", str(raw), "-map", "0", "-c", "copy", "-map_metadata", "-1",
          *meta, "-movflags", "+faststart+use_metadata_tags", "-fflags", "+bitexact", str(out)])


# ---------------------------------------------------------------- reading an MP4 back

def is_mp4(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(12)[4:8] == b"ftyp"
    except OSError:
        return False


def probe(mp4: Path) -> dict:
    """width, height, fps, frames, seconds, bytes and the source digest it was built from."""
    d = json.loads(_run([ff("ffprobe"), "-v", "error", "-select_streams", "v:0", "-count_packets",
                         "-show_entries", "stream=width,height,r_frame_rate,nb_read_packets:format=duration:format_tags",
                         "-of", "json", str(mp4)]))
    st, fmt = d["streams"][0], d["format"]
    m = STAMP.search(" ".join(str(v) for v in (fmt.get("tags") or {}).values()))
    return {"width": st["width"], "height": st["height"], "fps": st["r_frame_rate"],
            "frames": int(st["nb_read_packets"]), "seconds": float(fmt["duration"]), "bytes": mp4.stat().st_size,
            "source": m.group(1) if m else None}


def describe(mp4: Path) -> str:
    i = probe(mp4)
    return f"{i['seconds']:.1f} s, {i['width']}x{i['height']}, {i['bytes'] / 1e6:.1f} MB"


def png(mp4: Path, out_dir: Path, *, width: int = 1400) -> list[Path]:
    """One PNG per second of video, for review by eye."""
    out_dir.mkdir(parents=True, exist_ok=True)
    _run([ff("ffmpeg"), "-v", "error", "-y", "-i", str(mp4), "-vf", f"fps=1,scale={width}:-2",
          str(out_dir / "s%03d.png")])
    return sorted(out_dir.glob("s*.png"))


def frame_hashes(mp4: Path) -> list[str]:
    out = _run([ff("ffmpeg"), "-v", "error", "-i", str(mp4), "-map", "0:v:0", "-f", "framemd5", "-"])
    return [line.rsplit(",", 1)[1].strip() for line in out.splitlines() if line and not line.startswith("#")]


def min_psnr(a: Path, b: Path) -> tuple[float, int]:
    """The lowest per-frame PSNR (dB) between two videos of the same geometry, and its frame."""
    with tempfile.TemporaryDirectory() as tmp:
        stats = Path(tmp) / "psnr.log"
        _run([ff("ffmpeg"), "-v", "error", "-i", str(a), "-i", str(b), "-lavfi",
              f"[0:v][1:v]psnr=stats_file='{_ffescape(stats)}'", "-f", "null", "-"])
        worst = (math.inf, 0)
        for line in stats.read_text().splitlines():
            f = dict(kv.split(":", 1) for kv in line.split() if ":" in kv)
            v = math.inf if f.get("psnr_avg") == "inf" else float(f["psnr_avg"])
            if v < worst[0]:
                worst = (v, int(f["n"]))
        return worst


def _ffescape(p: Path) -> str:
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def compare(committed: Path, fresh: Path, tolerance: float) -> str | None:
    """None when `fresh` reproduces `committed`; otherwise how it differs."""
    a, b = probe(committed), probe(fresh)
    if a["source"] != b["source"]:
        return "stale (its source changed since it was built)" if a["source"] else "not stamped with its source (rebuild it)"
    for k in ("width", "height", "fps", "frames"):
        if a[k] != b[k]:
            return f"stale ({k} {a[k]} committed, {b[k]} from source)"
    if frame_hashes(committed) == frame_hashes(fresh):
        return None
    worst, n = min_psnr(committed, fresh)
    if worst < tolerance:
        return f"stale (frame {n} differs: {worst:.1f} dB PSNR, tolerance {tolerance:g} dB)"
    return None
