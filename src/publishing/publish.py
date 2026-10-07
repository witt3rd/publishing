"""Copy a built report to ~/Documents for review. The repo copy stays the source of record.

The folder is report.toml [publish] for the doc's kind (the folder under docs/), else `project`.
The name is the PDF's own: lowercase kebab-case, topic first, versioned (-vN). An existing file
with the same bytes is a no-op; one with different bytes is refused (bump the version).
"""
import filecmp
import os
import re
from pathlib import Path

from .build import Source
from .config import Config

NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-v[0-9]+$")


class PublishError(Exception):
    pass


def documents_root() -> Path:
    return Path(os.environ.get("PUBLISHING_DOCUMENTS", Path.home() / "Documents"))


def folder_for(s: Source, cfg: Config) -> str:
    kind = s.src.parent.name  # docs/<kind>/<topic>-vN or docs/<kind>/<file>.md
    folder = cfg.publish.get(kind) or cfg.project
    if not folder:
        raise PublishError(f"{cfg.path or 'no report.toml'}: set project, or [publish] {kind} = \"<folder>\"")
    return folder


def publish(s: Source, cfg: Config, *, name: str | None = None) -> tuple[str, Path]:
    """Return ("published" | "already published", target path). An explainer deck's PPTX goes with its PDF."""
    state, target = _publish(s, cfg, s.pdf, name)
    if s.kind == "explainer" and cfg.format != "markdown":
        _publish(s, cfg, s.pptx, name)
    return state, target


def _publish(s: Source, cfg: Config, built: Path, name: str | None) -> tuple[str, Path]:
    if cfg.format == "markdown":
        if s.src.suffix != ".md":
            raise PublishError("format = \"markdown\": publish copies the markdown report, not a PDF")
        src = s.src
    else:
        src = built
        if not src.is_file():
            raise PublishError(f"{src.name}: not built yet (publishing build {s.src.name})")
    stem = name or src.stem
    if not NAME.match(stem):
        raise PublishError(f"{stem!r}: name must be lowercase kebab-case, topic first, ending -vN (or pass --name)")
    folder = folder_for(s, cfg)
    if Path(folder).is_absolute() or ".." in Path(folder).parts:
        raise PublishError(f"{folder!r}: the publish folder is relative to ~/Documents")
    target = documents_root() / folder / f"{stem}{src.suffix}"
    if target.exists():
        if filecmp.cmp(src, target, shallow=False):
            return "already published", target
        raise PublishError(f"{target}: exists with different bytes; never overwrite a copy the captain may have "
                           f"seen. Bump the version (-v{_next(stem)}).")
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "xb") as f:  # exclusive create: never clobber a file that appeared meanwhile
        f.write(src.read_bytes())
    return "published", target


def _next(stem: str) -> int:
    return int(stem.rsplit("-v", 1)[1]) + 1
