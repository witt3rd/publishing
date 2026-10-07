"""docs/report.toml: a repo's pin, project, scan words, publish folders and fixed documents.

  publishing = "0.14.0"          # the tool version this repo builds with
  project = "Spire"             # default folder under ~/Documents for `publish`
  format = "pdf"                # "markdown": reports are the markdown itself; build refuses PDFs
  paper = "letter"              # memo/document default: "letter" or "a4"

  [scan]
  words = ["janus-?infra"]      # the repo's own private words (regexes, case-insensitive)
  allow = []                    # exact strings exempt from every check
  days = true                   # flag today/tomorrow/... (stale in a report)

  [publish]
  notes = "Spire/Design and evidence"   # docs/<kind>/ -> folder under ~/Documents

  [video]
  tolerance = 40                # dB PSNR: the least similarity a fresh render's frames may have to the
                                # committed MP4's (another ffmpeg build encodes them differently);
                                # identical frames always pass. See README "Video".

  [narrate]                     # `publishing narrate` defaults when no flag is given (flags win)
  tts_model = "microsoft/mai-voice-2.1-flash"   # an OpenRouter speech model; absent: local Kokoro
  voice = "en-US-Sage:MAI-Voice-2.1-Flash"      # that model's voice id (or a Kokoro voice)

  [user_content]                # build every source here as untrusted (docs/user-content.md)
  enabled = true                # off unless true; `build --user-content` turns it on per run
  max_pages = 300               # optional limits: max_bytes, max_pages, timeout (s),
  allow_js = false              #   max_memory_mb, allow_js, require_netns

  [[document]]                  # a markdown file with a fixed PDF path
  source = "docs/spire.md"
  pdf = "docs/Spire.pdf"
  format = "document"           # memo | document
  paper = "a4"
  days = false                  # per-document scan overrides
  words = false

The file is found at <dir>/report.toml or <dir>/docs/report.toml for the target or any parent;
paths in it are relative to <dir>. With no file the defaults apply.
"""
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .usercontent import Limits, limits_from

FORMATS = ("deck", "memo", "document", "video")
PAPERS = ("letter", "a4")


class ConfigError(Exception):
    pass


@dataclass
class Document:
    source: Path
    pdf: Path
    format: str = "document"
    paper: str | None = None
    days: bool | None = None
    words: bool = True


@dataclass
class Config:
    root: Path
    path: Path | None = None
    pin: str | None = None
    project: str | None = None
    format: str = "pdf"
    paper: str = "letter"
    words: list = field(default_factory=list)
    allow: list = field(default_factory=list)
    days: bool = True
    publish: dict = field(default_factory=dict)
    tolerance: float = 40.0
    documents: list = field(default_factory=list)
    user_content: Limits | None = None  # set: every build here renders in user-content mode

    def document_for(self, source: Path) -> Document | None:
        source = source.resolve()
        return next((d for d in self.documents if d.source == source), None)

    def documents_pdf(self, pdf: Path) -> Document | None:
        pdf = pdf.resolve()
        return next((d for d in self.documents if d.pdf == pdf), None)


def find(start: Path) -> Path | None:
    start = start.resolve()
    for d in [start, *start.parents] if start.is_dir() else start.parents:
        for cand in (d / "report.toml", d / "docs" / "report.toml"):
            if cand.is_file():
                return cand
    return None


def load(start: Path) -> Config:
    path = find(start)
    if path is None:
        return Config(root=(start if start.is_dir() else start.parent).resolve())
    root = path.parent.parent if path.parent.name == "docs" else path.parent
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    scan = data.get("scan", {})
    cfg = Config(root=root, path=path, pin=data.get("publishing"), project=data.get("project"),
                 format=data.get("format", "pdf"), paper=data.get("paper", "letter"),
                 words=list(scan.get("words", [])), allow=list(scan.get("allow", [])),
                 days=bool(scan.get("days", True)), publish=dict(data.get("publish", {})))
    try:
        cfg.tolerance = float(data.get("video", {}).get("tolerance", cfg.tolerance))
    except (TypeError, ValueError):
        raise ConfigError(f"{path}: [video] tolerance is a number of dB (PSNR), such as 40") from None
    if cfg.format not in ("pdf", "markdown"):
        raise ConfigError(f"{path}: format must be \"pdf\" or \"markdown\", not {cfg.format!r}")
    if cfg.paper not in PAPERS:
        raise ConfigError(f"{path}: paper must be one of {PAPERS}, not {cfg.paper!r}")
    try:
        cfg.user_content = limits_from(data.get("user_content", {}))
    except ValueError as e:
        raise ConfigError(f"{path}: {e}") from e
    for i, d in enumerate(data.get("document", [])):
        try:
            doc = Document(source=(root / d["source"]).resolve(), pdf=(root / d["pdf"]).resolve(),
                           format=d.get("format", "document"), paper=d.get("paper"),
                           days=d.get("days"), words=d.get("words", True))
        except KeyError as e:
            raise ConfigError(f"{path}: [[document]] #{i + 1} needs {e.args[0]!r}") from e
        if doc.format not in ("memo", "document"):
            raise ConfigError(f"{path}: [[document]] {d['source']}: format must be memo or document")
        if doc.paper not in (None, *PAPERS):
            raise ConfigError(f"{path}: [[document]] {d['source']}: paper must be one of {PAPERS}")
        cfg.documents.append(doc)
    return cfg
