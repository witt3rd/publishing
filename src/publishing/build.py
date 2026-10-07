"""Find sources, turn them into HTML, render, scan, and compare with the committed PDF.

A source is one of:
  <topic>-vN/slides.py     deck (TITLE and S, the page HTML); PDF is <topic>-vN.pdf beside the folder
  <topic>-vN/explainer.py  explainer deck (TITLE, S and NOTES from publishing.explainer): <topic>-vN.pdf and .pptx
  <topic>-vN/memo.md       memo (portrait, markdown)
  <topic>-vN/document.md   document (long form: cover, contents, running header)
  <topic>-vN/video.html    video (a HyperFrames composition); the MP4 is <topic>-vN.mp4 (see video.py)
  <topic>-vN/source.txt    the PDF is a copy of one built elsewhere (not rebuilt)
  a [[document]] in report.toml: a markdown file with a fixed PDF path
"""
import html as htmlmod
import importlib.util
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from pypdf import PdfReader

from . import markdown, pdf, scan, video
from .config import Config, Document
from .render import Renderer

MARKERS = {"slides.py": "deck", "explainer.py": "explainer", "memo.md": "memo", "document.md": "document", "video.html": "video",
           "source.txt": "copy"}
KINDS = ("deck", "explainer", "memo", "document", "video", "copy")
OUTPUTS = (".pdf", ".mp4")


class BuildError(Exception):
    pass


@dataclass
class Source:
    kind: str  # deck | explainer | memo | document | video | copy
    src: Path  # the folder, or the markdown file
    pdf: Path  # the output: a PDF, or for a video its MP4
    paper: str = "letter"
    days: bool = True
    words: bool = True

    @property
    def name(self) -> str:
        return self.pdf.name


def theme() -> Path:
    return Path(str(resources.files("publishing").joinpath("theme"))).resolve()


def _from_entry(d: Document, cfg: Config) -> Source:
    return Source(d.format, d.source, d.pdf, d.paper or cfg.paper, cfg.days if d.days is None else d.days, d.words)


def resolve(target: Path, cfg: Config, fmt: str | None = None, out: Path | None = None) -> Source:
    target = target.resolve()
    if target.is_dir():
        for marker, kind in MARKERS.items():
            if (target / marker).is_file():
                ext = ".mp4" if kind == "video" else ".pdf"
                s = Source(kind, target, target.parent / f"{target.name}{ext}", cfg.paper, cfg.days)
                break
        else:
            raise BuildError(f"{target}: no slides.py, explainer.py, memo.md, document.md, video.html or source.txt")
    elif target.suffix == ".md":
        entry = cfg.document_for(target) or (cfg.documents_pdf(out) if out else None)
        if entry:  # a listed document, or a copy of one (a pre-commit hook renders the staged file)
            s = _from_entry(entry, cfg)
            s.src = target
        else:
            meta, _ = markdown.front_matter(target.read_text())
            s = Source(fmt or meta.get("format", "memo"), target, target.with_suffix(".pdf"),
                       meta.get("paper", cfg.paper), cfg.days)
    elif target.suffix in OUTPUTS:
        entry = cfg.documents_pdf(target) if target.suffix == ".pdf" else None
        if entry:
            s = _from_entry(entry, cfg)
        elif target.with_suffix("").is_dir():
            return resolve(target.with_suffix(""), cfg, fmt, out)
        else:
            raise BuildError(f"{target.name}: no source folder {target.stem}/ and no [[document]] entry")
    else:
        raise BuildError(f"{target}: not a source folder, a markdown file, a PDF or an MP4")
    if fmt and fmt != s.kind and "video" in (fmt, s.kind):
        raise BuildError(f"{target}: a video is a folder with video.html; it does not convert to or from {fmt}")
    if fmt and s.kind != "copy":
        s.kind = fmt
    if out:
        s.pdf = out.resolve()
    if s.kind not in KINDS:
        raise BuildError(f"{target}: unknown format {s.kind!r} (deck, explainer, memo, document or video)")
    if s.paper not in ("letter", "a4"):
        raise BuildError(f"{target}: paper must be letter or a4, not {s.paper!r}")
    return s


def discover(where: Path, cfg: Config) -> tuple[list[Source], list[Path]]:
    """Every source under `where`, and every PDF there that has no source (an orphan)."""
    where = where.resolve()
    sources, folders = [], set()
    for marker in MARKERS:
        for m in where.rglob(marker):
            if m.parent not in folders and not any(p in folders for p in m.parent.parents):
                folders.add(m.parent)
    for f in sorted(folders):
        sources.append(resolve(f, cfg))
    for d in cfg.documents:
        if d.source.is_relative_to(where) or d.pdf.is_relative_to(where):
            sources.append(_from_entry(d, cfg))
    targets = {s.pdf for s in sources}
    orphans = [p for ext in OUTPUTS for p in sorted(where.rglob(f"*{ext}"))
               if p.resolve() not in targets and not any(p.resolve().is_relative_to(f) for f in folders)]
    return sources, orphans


# ---------------------------------------------------------------- HTML

def _css_string(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", htmlmod.unescape(s))
    return '"' + " ".join(s.split()).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _load_slides(s: Source):
    """The author's slides.py or explainer.py, run: its module."""
    name = "explainer.py" if s.kind == "explainer" else "slides.py"
    spec = importlib.util.spec_from_file_location(f"slides_{abs(hash(s.src))}", s.src / name)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(s.src))
    try:
        spec.loader.exec_module(mod)
    except Exception as e:  # the author's code: report it as a build problem
        raise BuildError(f"{s.src.name}/{name}: {type(e).__name__}: {e}") from e
    finally:
        sys.path.remove(str(s.src))
    if not getattr(mod, "S", None):
        raise BuildError(f"{s.src.name}/{name} defines no pages (S)")
    if s.kind == "explainer":
        notes = getattr(mod, "NOTES", None)
        if not notes or len(notes) != len(mod.S) or not all(str(n).strip() for n in notes):
            raise BuildError(f"{s.src.name}/{name}: every slide needs speaker notes (NOTES, one per slide)")
    return mod


def _deck_html(s: Source) -> str:
    mod = _load_slides(s)
    return deck_html(mod.S, s.src, str(getattr(mod, "TITLE", s.src.name)),
                     "explainer.css" if s.kind == "explainer" else "deck.css")


def deck_html(pages: list[str], base: Path, title: str, css: str = "deck.css") -> str:
    """The deck page: slides in order, relative paths resolved against `base`, totals filled in."""
    body = "\n".join(pages).replace("%%TOTAL%%", str(len(pages)))
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{htmlmod.escape(title)}</title>'
            f'<base href="{base.as_uri()}/"><link rel="stylesheet" href="{(theme() / css).as_uri()}">'
            f"</head><body>{body}</body></html>")


def _page_html(s: Source, cfg: Config, pages_by_id: dict | None = None, r=Renderer) -> str:
    md_path = s.src if s.src.suffix == ".md" else s.src / f"{s.kind}.md"
    meta = markdown.front_matter(md_path.read_text())[0]
    toc_depth = _toc_depth(meta, md_path)
    page = markdown.parse(md_path.read_text(), toc_levels=max(toc_depth, 1))
    kicker = htmlmod.escape(meta.get("kicker", cfg.project or ""))
    meta_line = htmlmod.escape(meta.get("meta", " · ".join(v for v in (meta.get("author", ""), meta.get("date", ""))
                                                           if v)))
    footer = meta.get("footer", meta.get("date", ""))
    title_txt = page.title or htmlmod.escape(md_path.stem)
    block = ""
    if not page.has_cover and (page.title or kicker):
        block = ('<header class="titleblock">' + (f'<p class="kicker">{kicker}</p>' if kicker else "")
                 + (f"<h1>{page.title}</h1>" if page.title else "")
                 + (f'<p class="subtitle">{page.subtitle}</p>' if page.subtitle else "")
                 + (f'<p class="meta">{meta_line}</p>' if meta_line else "") + "</header>")
    toc = ""
    if s.kind == "document" and page.headings and toc_depth:
        rows = []
        for level, ident, text in page.headings:
            n = (pages_by_id or {}).get(ident, "")
            rows.append(f'<li class="l{level}"><a href="#{ident}"><span class="t">{text}</span>'
                        f'<span class="dots"></span><span class="p">{n}</span></a></li>')
        toc = f'<nav class="toc"><h2>Contents</h2><ol>{"".join(rows)}</ol></nav>'
    size = "letter" if s.paper == "letter" else "A4"
    style = (f"@page {{ size: {size}; @top-left {{ content: {_css_string(title_txt)}; }}"
             f" @top-right {{ content: {_css_string(kicker)}; }} @bottom-left {{ content: {_css_string(footer)}; }} }}"
             " @page :first { @top-left { content: none; } @top-right { content: none; } }")
    body = _inline_svgs(page.body, md_path.parent, confine=r.untrusted)
    main_cls = ' class="h2top"' if page.top == 2 else ""
    numbered = _flag(meta, "numbered", md_path) and s.kind == "document"
    body_cls = " numbered" if numbered else ""
    front = f'<section class="front">{block}{toc}</section>' if s.kind == "document" else block
    return (f'<!doctype html><html lang="{htmlmod.escape(meta.get("lang", "en"))}"><head><meta charset="utf-8">'
            f"<title>{htmlmod.escape(re.sub(r'<[^>]+>', '', title_txt))}</title>"
            f'<base href="{r.url(md_path.parent).rstrip("/")}/">'
            f'<link rel="stylesheet" href="{r.url(theme() / "page.css")}"><style>{style}</style></head>'
            f'<body class="{s.kind}{body_cls}">{front}<main{main_cls}>{body}</main></body></html>')


def _flag(meta: dict, key: str, md_path: Path) -> bool:
    v = meta.get(key, "false").strip().lower()
    if v not in ("true", "false", "yes", "no"):
        raise BuildError(f"{md_path.name}: front matter `{key}` must be true or false, not {meta[key]!r}")
    return v in ("true", "yes")


def _toc_depth(meta: dict, md_path: Path) -> int:
    """Front matter `toc`: how many heading levels the contents list (1-3, default 2); false leaves it out."""
    v = meta.get("toc", "2").strip().lower()
    if v in ("false", "no", "none", "0"):
        return 0
    if v not in ("1", "2", "3"):
        raise BuildError(f"{md_path.name}: front matter `toc` must be 1, 2, 3 or false, not {meta['toc']!r}")
    return int(v)


def _inline_svgs(body: str, base: Path, confine: bool = False) -> str:
    """Inline local SVG images, so their text uses the vendored fonts (an <img> SVG cannot).
    `confine` (user content): only a file inside `base`, through no hidden or `..` part."""
    def sub(m):
        rel = htmlmod.unescape(m.group(1))
        f = base / rel
        if confine:
            if rel.startswith("/") or any(p.startswith(".") for p in Path(rel).parts):
                return m.group(0)
            f = f.resolve()
            if not f.is_relative_to(base.resolve()):
                return m.group(0)
        if not f.is_file():
            return m.group(0)
        svg = f.read_text()
        return svg[svg.index("<svg"):]
    return re.sub(r'<img src="([^":]+\.svg)"[^>]*>', sub, body)


def _furniture(s: Source, cfg: Config) -> list[str]:
    meta = markdown.front_matter((s.src if s.src.suffix == ".md" else s.src / f"{s.kind}.md").read_text())[0]
    return [meta.get("kicker", cfg.project or ""), meta.get("footer", meta.get("date", ""))]


def _named_pages(path: Path) -> dict:
    r = PdfReader(str(path))
    return {k.lstrip("/"): r.get_destination_page_number(v) + 1 for k, v in r.named_destinations.items()}


# ---------------------------------------------------------------- build / check

def render(s: Source, cfg: Config, out: Path, r: Renderer) -> list[str]:
    """Render `s` to `out` (a scratch path); return every problem (lint, scan). Empty is clean."""
    if cfg.format == "markdown":
        raise BuildError(f"{cfg.path}: format = \"markdown\": reports here are the markdown itself, not PDFs")
    if not s.src.exists():
        raise BuildError(f"{s.name}: its source {s.src} is missing")
    if s.kind == "video" and r.untrusted:
        raise BuildError(f"{s.name}: a video runs its HTML and script through HyperFrames outside the sandbox; "
                         "user-content mode builds memos and documents only")
    if s.kind == "video":
        return video.render(s.src, cfg, out, r, words=s.words, days=s.days)
    work = out.parent / f".{out.stem}.html"
    if s.kind in ("deck", "explainer") and r.untrusted:
        raise BuildError(f"{s.name}: a deck's slides.py is code; user-content mode builds memos and documents only")
    if s.kind in ("deck", "explainer"):
        work.write_text(_deck_html(s))
        problems, text = r.pdf(work, out, kind=s.kind)
    else:
        work.write_text(_page_html(s, cfg, r=r))
        problems, text = r.pdf(work, out, kind=s.kind, paper=s.paper)
        if s.kind == "document":
            seen = None
            for _ in range(4):  # fill the contents' page numbers until they stop moving
                found = _named_pages(out)
                if found == seen:
                    break
                seen = found
                work.write_text(_page_html(s, cfg, found, r=r))
                problems, text = r.pdf(work, out, kind=s.kind, paper=s.paper)
        text += "\n" + "\n".join(_furniture(s, cfg))  # the running header and footer are CSS strings
    hosts = sorted(f for f in pdf.fonts(out) if not f.startswith("Publishing"))
    if hosts:
        problems.append(f"host font used (not vendored, so other hosts render differently): {', '.join(hosts)}"
                        " - a generic family such as sans-serif (name one: Publishing Sans, Noto Sans, Arial...), or a glyph"
                        " outside the house fonts")
    problems = problems + scan.scan(text, words=cfg.words if s.words else (), allow=cfg.allow, days=s.days)
    work.unlink()
    return problems


def build(s: Source, cfg: Config, r: Renderer, *, force: bool = False, png: Path | None = None) -> str:
    """Build `s` into its PDF. Returns "built" or "current" (same words and pages: left untouched)."""
    if s.kind == "copy":
        if not s.pdf.is_file():
            raise BuildError(f"{s.name}: missing; it is a copy built elsewhere ({s.src.name}/source.txt says where)")
        return "copy"
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp) / s.pdf.name
        problems = render(s, cfg, fresh, r)
        if problems:
            raise BuildError(f"{s.name}: not written:\n  " + "\n  ".join(problems))
        if png:
            video.png(fresh, png) if s.kind == "video" else pdf.png(fresh, png)
        if not force and _same(s, fresh, cfg):
            return "current"
        s.pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fresh, s.pdf)
        return "built"


def _same(s: Source, fresh: Path, cfg: Config) -> bool:
    if s.kind == "video":
        return video.is_mp4(s.pdf) and video.compare(s.pdf, fresh, cfg.tolerance) is None
    return pdf.same(s.pdf, fresh)


def check(s: Source, cfg: Config, r: Renderer) -> str | None:
    """None when the committed PDF matches a fresh build; otherwise the problem."""
    if s.kind == "copy":
        return None if pdf.is_pdf(s.pdf) else f"{s.name}: missing (a copy; see {s.src.name}/source.txt)"
    if not s.pdf.is_file():
        return f"{s.name}: missing (build it: publishing build {s.src.name})"
    if not (video.is_mp4 if s.kind == "video" else pdf.is_pdf)(s.pdf):
        return f"{s.name}: not {'an MP4' if s.kind == 'video' else 'a PDF'} (an unfetched LFS pointer?)"
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp) / s.pdf.name
        problems = render(s, cfg, fresh, r)
        if problems:
            return f"{s.name}: source fails the build:\n  " + "\n  ".join(problems)
        if s.kind == "video":
            bad = video.compare(s.pdf, fresh, cfg.tolerance)
            return f"{s.name}: {bad}" if bad else None
        if pdf.pages(fresh) != pdf.pages(s.pdf):
            return f"{s.name}: stale ({pdf.pages(s.pdf)} pages committed, {pdf.pages(fresh)} from source)"
        if pdf.text(fresh) != pdf.text(s.pdf):
            return f"{s.name}: stale (its text differs from a fresh build of its source)"
    return None
