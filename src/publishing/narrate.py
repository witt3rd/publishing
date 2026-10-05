"""Narration: `publishing narrate SCRIPT [-o DIR]` turns a script into speech timed to scenes.

Two kinds of voice, one script, one output:
- Kokoro (the default; 82M parameters, Apache-2.0) run locally through kokoro-onnx, pinned exactly in the
  `narrate` extra. Free, no account, no key, no network once the model is cached. The free fallback.
- An OpenRouter speech model, chosen with `--model` (OPENROUTER_API_KEY in the environment, never a file or an
  argument; e.g. `doppler run -- publishing narrate ... --model fish-audio/s2.1-pro`). The text goes to
  OpenRouter; the answer is decoded to the same 24 kHz wav with ffmpeg. MODELS lists the ones this tool knows,
  any other OpenRouter speech model id is passed through (with --voice if it needs one).

Kokoro details: The two model files (about 350 MB) are downloaded once, from the
kokoro-onnx GitHub release, checked against the sha256 below and kept in the user cache
(`$PUBLISHING_CACHE/kokoro` or `~/.cache/publishing/kokoro`); `--model-dir` uses a directory you filled yourself,
and then nothing touches the network. Synthesis itself never does.

The script is plain text. A line `## scene-id` opens a scene; the lines under it, up to the next heading, are
what is said (blank lines are ignored). Lines starting `#` or `<!--` are comments. Without any heading each
paragraph is a scene named scene-1, scene-2, ... The ids are the ids of the video's `<section id="scene-...">`.

Out, in DIR (default: beside the script), never overwritten:
  NAME.wav    every scene's speech in order, each followed by --gap seconds of silence (24 kHz, mono, 16-bit)
  NAME.json   {"voice", "sample_rate", "duration", "scenes": [{"id", "text", "start", "speech", "duration"}]}
              start and duration are in seconds and tile the wav; `speech` is the spoken part of the duration.
              Give each video scene data-start=start and data-duration=duration (README "Narration").
Its stdout is the two paths. Exit codes: 0 done; 1 synthesis failed or the model download did not verify;
2 usage (no script, no scenes, an output exists, no OPENROUTER_API_KEY for --model); 3 the `narrate` extra
(Kokoro) or ffmpeg (--model) is not installed.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
MODEL_FILES = {  # name -> sha256
    "kokoro-v1.0.onnx": "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}
VOICE = "af_heart"
ENDPOINT = "https://openrouter.ai/api/v1/audio/speech"
MODELS = {  # OpenRouter speech model -> the voice it needs ("" when it takes none)
    "fish-audio/s2.1-pro": "",
    "fish-audio/s2.1-pro-free:free": "",   # free; the provider often answers 418 under load, then try later
    "microsoft/mai-voice-2.1-flash": "en-US-Sage:MAI-Voice-2.1-Flash",
    "bytedance-seed/seed-audio-1-0": "",   # the text is a prompt; see _seed_prompt
    "deepgram/flux-tts": "flux-sharon-en",
}
GAP = 0.6  # seconds of silence after each scene
SAMPLE_RATE = 24000


class NarrateError(Exception):
    exit_code = 1


class Usage(NarrateError):
    exit_code = 2


class NotInstalled(NarrateError):
    exit_code = 3


def parse_script(text: str) -> list[tuple[str, str]]:
    """The script as [(scene id, spoken text)]. Raises Usage when it has no words."""
    scenes: list[tuple[str, list[str]]] = []
    paragraphs: list[list[str]] = [[]]
    for raw in text.splitlines():
        line = raw.strip()
        head = re.fullmatch(r"##\s+(\S+)", line)
        if head:
            scenes.append((head.group(1), []))
        elif not line:
            if not scenes:
                paragraphs.append([])
        elif line.startswith("#") or line.startswith("<!--"):
            continue
        elif scenes:
            scenes[-1][1].append(line)
        else:
            paragraphs[-1].append(line)
    if not scenes:
        scenes = [(f"scene-{i}", p) for i, p in enumerate([p for p in paragraphs if p], 1)]
    out = [(sid, " ".join(lines)) for sid, lines in scenes]
    ids = [sid for sid, _ in out]
    if len(set(ids)) != len(ids):
        raise Usage("duplicate scene ids in the script")
    empty = [sid for sid, words in out if not words]
    if empty:
        raise Usage(f"scene(s) with no text: {', '.join(empty)}")
    if not out:
        raise Usage("the script has no scenes")
    return out


def model_dir() -> Path:
    root = os.environ.get("PUBLISHING_CACHE") or Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "publishing"
    return Path(root) / "kokoro"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ensure_models(directory: Path | None = None) -> Path:
    """The model directory with both files present and verified, fetching what is missing (only into the cache)."""
    custom = directory is not None
    directory = Path(directory) if custom else model_dir()
    for name, digest in MODEL_FILES.items():
        path = directory / name
        if not path.exists():
            if custom:
                raise Usage(f"{path}: missing (expected {', '.join(MODEL_FILES)} in --model-dir)")
            directory.mkdir(parents=True, exist_ok=True)
            print(f"publishing: fetching {name} once into {directory}", file=sys.stderr)
            part = path.with_suffix(path.suffix + ".part")
            try:
                with urllib.request.urlopen(RELEASE + name, timeout=60) as r, open(part, "wb") as f:
                    while block := r.read(1 << 20):
                        f.write(block)
                if _sha256(part) != digest:
                    raise NarrateError(f"{name}: sha256 does not match the pin; not used")
                part.replace(path)
            except OSError as e:
                raise NarrateError(f"{name}: download failed ({e})") from None
            finally:
                part.unlink(missing_ok=True)
        elif _sha256(path) != digest:
            raise NarrateError(f"{path}: sha256 does not match the pin")
    return directory


def _kokoro(models: Path):
    try:
        from kokoro_onnx import Kokoro
    except ModuleNotFoundError:
        raise NotInstalled("kokoro-onnx not found (install `publishing[narrate]`)") from None
    return Kokoro(str(models / "kokoro-v1.0.onnx"), str(models / "voices-v1.0.bin"))


def _seed_prompt(text: str) -> str:
    # Seed Audio takes a prompt, not a transcript: say how to read, and that the words are not to change.
    return f"A calm, clear, steady narrator reads this aloud exactly as written, adding and changing nothing: {text}"


def speak_openrouter(text: str, model: str, voice: str, speed: float = 1.0, key: str | None = None,
                     tries: int = 3) -> tuple[bytes, str]:
    """One request to OpenRouter's speech endpoint -> (mp3 bytes, generation id). The key stays in memory."""
    body = {"model": model, "input": _seed_prompt(text) if model.startswith("bytedance-seed/") else text,
            "response_format": "mp3"}
    if voice:
        body["voice"] = voice
    if speed != 1.0:
        body["speed"] = speed
    req = urllib.request.Request(ENDPOINT, json.dumps(body).encode(), {
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    attempt = 0
    while True:  # each pass returns, raises, or sleeps and tries again
        attempt += 1
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read(), r.headers.get("X-Generation-Id", "")
        except urllib.error.HTTPError as e:
            detail = e.read(400).decode("utf-8", "replace")
            if e.code in (418, 429, 500, 502, 503, 504) and attempt < tries:
                time.sleep(2 * attempt)
                continue
            raise NarrateError(f"{model}: HTTP {e.code} {' '.join(detail.split())}") from None
        except OSError as e:
            raise NarrateError(f"{model}: request failed ({e})") from None


def _decode(mp3: bytes):
    """mp3 -> int16 mono samples at SAMPLE_RATE through ffmpeg."""
    import numpy as np
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise NotInstalled("ffmpeg not found (needed to decode a --model voice)")
    try:
        r = subprocess.run([ffmpeg, "-nostdin", "-loglevel", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1",
                            "-ar", str(SAMPLE_RATE), "pipe:1"], input=mp3, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise NarrateError("ffmpeg timed out decoding the speech") from None
    if r.returncode or not r.stdout:
        raise NarrateError("ffmpeg could not decode the speech: " + " ".join(r.stderr.decode(errors="replace").split())[:200])
    return np.frombuffer(r.stdout, dtype="<i2")


def synthesize_openrouter(scenes, *, model: str, voice: str | None = None, speed: float = 1.0, **_):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise Usage("--model needs OPENROUTER_API_KEY in the environment (e.g. `doppler run -- publishing narrate ...`)")
    voice = MODELS.get(model, "") if voice is None else voice
    out = []
    for sid, text in scenes:
        mp3, _gen = speak_openrouter(text, model, voice, speed, key)
        out.append((sid, text, _decode(mp3)))
    return out


def synthesize(scenes, *, voice: str = VOICE, speed: float = 1.0, models: Path | None = None):
    """[(id, text)] -> [(id, text, int16 samples)] with Kokoro."""
    import numpy as np
    kokoro = _kokoro(ensure_models(models))
    out = []
    for sid, text in scenes:
        try:
            samples, rate = kokoro.create(text, voice=voice, speed=speed, lang="en-us")
        except Exception as e:  # an unknown voice, a phonemizer failure: the call's failure, one line
            raise NarrateError(f"{sid}: {type(e).__name__}: {' '.join(str(e).split())[:300]}") from None
        if rate != SAMPLE_RATE:
            raise NarrateError(f"{sid}: Kokoro returned {rate} Hz, expected {SAMPLE_RATE}")
        out.append((sid, text, (np.clip(samples, -1, 1) * 32767).astype("<i2")))
    return out


def lay_out(spoken, gap: float, voice: str = VOICE) -> tuple[bytes, dict]:
    """Join scenes in order, each followed by `gap` seconds of silence: the wav's frames and the timing table."""
    pad = round(gap * SAMPLE_RATE)
    frames, scenes, at = [], [], 0
    for sid, text, samples in spoken:
        n = len(samples)
        frames.append(bytes(samples.tobytes() if hasattr(samples, "tobytes") else samples) + b"\0\0" * pad)
        scenes.append({"id": sid, "text": text, "start": round(at / SAMPLE_RATE, 3),
                       "speech": round(n / SAMPLE_RATE, 3), "duration": round((n + pad) / SAMPLE_RATE, 3)})
        at += n + pad
    return b"".join(frames), {"voice": voice, "sample_rate": SAMPLE_RATE, "duration": round(at / SAMPLE_RATE, 3),
                              "scenes": scenes}


def narrate(script, out_dir=None, *, voice: str | None = None, speed: float = 1.0, gap: float = GAP,
            models: Path | None = None, model: str | None = None, synth=None) -> tuple[Path, Path]:
    """Script file -> (wav, json). `synth` is injectable for tests. Raises a NarrateError subclass."""
    script = Path(script)
    if not script.is_file():
        raise Usage(f"{script}: no such file")
    scenes = parse_script(script.read_text(encoding="utf-8"))
    out_dir = Path(out_dir) if out_dir else script.parent
    wav_path, json_path = out_dir / (script.stem + ".wav"), out_dir / (script.stem + ".json")
    for p in (wav_path, json_path):
        if p.exists():
            raise Usage(f"{p} exists; never overwrite")
    if synth is None:
        synth = (lambda sc, **kw: synthesize_openrouter(sc, model=model, **kw)) if model else synthesize
    if model:
        label = model
        kw = {"voice": voice, "speed": speed}
    else:
        label = voice or VOICE
        kw = {"voice": label, "speed": speed, "models": models}
    frames, table = lay_out(synth(scenes, **kw), gap, label)
    out_dir.mkdir(parents=True, exist_ok=True)
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(frames)
    json_path.write_text(json.dumps(table, indent=2) + "\n", encoding="utf-8")
    return wav_path, json_path


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("script", help="the narration script: `## scene-id` headings, the spoken text under each")
    p.add_argument("-o", "--output-dir", help="where NAME.wav and NAME.json go (default: beside the script; never overwritten)")
    p.add_argument("--model", help="an OpenRouter speech model instead of local Kokoro (needs OPENROUTER_API_KEY and ffmpeg): "
                   + ", ".join(MODELS))
    p.add_argument("--voice", help=f"a Kokoro voice (default {VOICE}), or the model's voice id (default: the one MODELS names)")
    p.add_argument("--speed", type=float, default=1.0, help="speaking speed, 0.5 to 2 (default 1)")
    p.add_argument("--gap", type=float, default=GAP, metavar="SECONDS", help=f"silence after each scene (default {GAP:g})")
    p.add_argument("--model-dir", help="a directory holding kokoro-v1.0.onnx and voices-v1.0.bin (default: the user cache, fetched once)")
    p.set_defaults(fn=run, needs_render=False)


def run(a) -> int:
    try:
        if not 0.5 <= a.speed <= 2 or a.gap < 0:
            raise Usage("--speed is 0.5 to 2 and --gap is not negative")
        wav, meta = narrate(a.script, a.output_dir, voice=a.voice, speed=a.speed, gap=a.gap, models=a.model_dir,
                              model=a.model)
    except NarrateError as e:
        print(f"publishing: {e}", file=sys.stderr)
        return e.exit_code
    print(wav)
    print(meta)
    return 0
