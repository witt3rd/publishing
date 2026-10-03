"""Find sources, turn them into HTML, render, scan, and compare with the committed PDF.

A source is one of:
  <topic>-vN/slides.py     deck (TITLE and S, the page HTML); PDF is <topic>-vN.pdf beside the folder
  <topic>-vN/memo.md       memo (portrait, markdown)
  <topic>-vN/document.md   document (long form: cover, contents, running header)
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

from . import markdown, pdf, scan
from .config import Config, Document
from .render import Renderer

MARKERS = {"slides.py": "deck", "memo.md": "memo", "document.md": "document", "source.txt": "copy"}


class BuildError(Exception):
    pass


@dataclass
class Source:
    kind: str  # deck | memo | document | copy
    src: Path  # the folder, or the markdown file
    pdf: Path
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
                s = Source(kind, target, target.parent / f"{target.name}.pdf", cfg.paper, cfg.days)
                break
        else:
            raise BuildError(f"{target}: no slides.py, memo.md, document.md or source.txt")
    elif target.suffix == ".md":
        entry = cfg.document_for(target)
        if entry:
            s = _from_entry(entry, cfg)
        else:
            meta, _ = markdown.front_matter(target.read_text())
            s = Source(fmt or meta.get("format", "memo"), target, target.with_suffix(".pdf"),
                       meta.get("paper", cfg.paper), cfg.days)
    elif target.suffix == ".pdf":
        entry = cfg.documents_pdf(target)
        if entry:
            s = _from_entry(entry, cfg)
        elif target.with_suffix("").is_dir():
            return resolve(target.with_suffix(""), cfg, fmt, out)
        else:
            raise BuildError(f"{target.name}: no source folder {target.stem}/ and no [[document]] entry")
    else:
        raise BuildError(f"{target}: not a source folder, a markdown file or a PDF")
    if fmt and s.kind != "copy":
        s.kind = fmt
    if out:
        s.pdf = out.resolve()
    if s.kind not in ("deck", "memo", "document", "copy"):
        raise BuildError(f"{target}: unknown format {s.kind!r} (deck, memo or document)")
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
    orphans = [p for p in sorted(where.rglob("*.pdf"))
               if p.resolve() not in targets and not any(p.resolve().is_relative_to(f) for f in folders)]
    return sources, orphans


# ---------------------------------------------------------------- HTML

def _css_string(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", htmlmod.unescape(s))
    return '"' + " ".join(s.split()).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _deck_html(s: Source) -> str:
    spec = importlib.util.spec_from_file_location(f"slides_{abs(hash(s.src))}", s.src / "slides.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(s.src))
    try:
        spec.loader.exec_module(mod)
    except Exception as e:  # the author's code: report it as a build problem
        raise BuildError(f"{s.src.name}/slides.py: {type(e).__name__}: {e}") from e
    finally:
        sys.path.remove(str(s.src))
    pages = getattr(mod, "S", None)
    if not pages:
        raise BuildError(f"{s.src.name}/slides.py defines no pages (S)")
    return deck_html(pages, s.src, str(getattr(mod, "TITLE", s.src.name)))


def deck_html(pages: list[str], base: Path, title: str) -> str:
    """The deck page: slides in order, relative paths resolved against `base`, totals filled in."""
    body = "\n".join(pages).replace("%%TOTAL%%", str(len(pages)))
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{htmlmod.escape(title)}</title>'
            f'<base href="{base.as_uri()}/"><link rel="stylesheet" href="{(theme() / "deck.css").as_uri()}">'
            f"</head><body>{body}</body></html>")


def _page_html(s: Source, cfg: Config, pages_by_id: dict | None = None) -> str:
    md_path = s.src if s.src.is_file() else s.src / f"{s.kind}.md"
    page = markdown.parse(md_path.read_text())
    meta = page.meta
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
    if s.kind == "document" and page.headings:
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
    body = _inline_svgs(page.body, md_path.parent)
    main_cls = ' class="h2top"' if page.top == 2 else ""
    front = f'<section class="front">{block}{toc}</section>' if s.kind == "document" else block
    return (f'<!doctype html><html lang="{htmlmod.escape(meta.get("lang", "en"))}"><head><meta charset="utf-8">'
            f"<title>{htmlmod.escape(re.sub(r'<[^>]+>', '', title_txt))}</title>"
            f'<base href="{md_path.parent.as_uri()}/">'
            f'<link rel="stylesheet" href="{(theme() / "page.css").as_uri()}"><style>{style}</style></head>'
            f'<body class="{s.kind}">{front}<main{main_cls}>{body}</main></body></html>')


def _inline_svgs(body: str, base: Path) -> str:
    """Inline local SVG images, so their text uses the vendored fonts (an <img> SVG cannot)."""
    def sub(m):
        f = base / htmlmod.unescape(m.group(1))
        if not f.is_file():
            return m.group(0)
        svg = f.read_text()
        return svg[svg.index("<svg"):]
    return re.sub(r'<img src="([^":]+\.svg)"[^>]*>', sub, body)


def _furniture(s: Source, cfg: Config) -> list[str]:
    meta = markdown.front_matter((s.src if s.src.is_file() else s.src / f"{s.kind}.md").read_text())[0]
    return [meta.get("kicker", cfg.project or ""), meta.get("footer", meta.get("date", ""))]


def _named_pages(path: Path) -> dict:
    r = PdfReader(str(path))
    return {k.lstrip("/"): r.get_destination_page_number(v) + 1 for k, v in r.named_destinations.items()}


# ---------------------------------------------------------------- build / check

def render(s: Source, cfg: Config, out: Path, r: Renderer) -> list[str]:
    """Render `s` to `out` (a scratch path); return every problem (lint, scan). Empty is clean."""
    if cfg.format == "markdown":
        raise BuildError(f"{cfg.path}: format = \"markdown\": reports here are the markdown itself, not PDFs")
    work = out.parent / f".{out.stem}.html"
    if s.kind == "deck":
        work.write_text(_deck_html(s))
        problems, text = r.pdf(work, out, kind="deck")
    else:
        work.write_text(_page_html(s, cfg))
        problems, text = r.pdf(work, out, kind=s.kind, paper=s.paper)
        if s.kind == "document":
            seen = None
            for _ in range(4):  # fill the contents' page numbers until they stop moving
                found = _named_pages(out)
                if found == seen:
                    break
                seen = found
                work.write_text(_page_html(s, cfg, found))
                problems, text = r.pdf(work, out, kind=s.kind, paper=s.paper)
        text += "\n" + "\n".join(_furniture(s, cfg))  # the running header and footer are CSS strings
    hosts = sorted(f for f in pdf.fonts(out) if not f.startswith("Noto"))
    if hosts:
        problems.append(f"host font used (not vendored, so other hosts render differently): {', '.join(hosts)}"
                        " - an <img> SVG with text, or a glyph outside the house fonts")
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
            pdf.png(fresh, png)
        if not force and pdf.same(s.pdf, fresh):
            return "current"
        s.pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fresh, s.pdf)
        return "built"


def check(s: Source, cfg: Config, r: Renderer) -> str | None:
    """None when the committed PDF matches a fresh build; otherwise the problem."""
    if s.kind == "copy":
        return None if pdf.is_pdf(s.pdf) else f"{s.name}: missing (a copy; see {s.src.name}/source.txt)"
    if not s.pdf.is_file():
        return f"{s.name}: missing (build it: publishing build {s.src.name})"
    if not pdf.is_pdf(s.pdf):
        return f"{s.name}: not a PDF (an unfetched LFS pointer?)"
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp) / s.pdf.name
        problems = render(s, cfg, fresh, r)
        if problems:
            return f"{s.name}: source fails the build:\n  " + "\n  ".join(problems)
        if pdf.pages(fresh) != pdf.pages(s.pdf):
            return f"{s.name}: stale ({pdf.pages(s.pdf)} pages committed, {pdf.pages(fresh)} from source)"
        if pdf.text(fresh) != pdf.text(s.pdf):
            return f"{s.name}: stale (its text differs from a fresh build of its source)"
    return None
