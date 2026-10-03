"""HTML, markdown and PDF to a PDF, page images and a first-page thumbnail: the render entry for services.

    publishing render-html SRC.html [--pdf OUT.pdf] [--png OUTDIR] [--thumbnail W] [--json] ...
    publishing render-md   SRC.md   [--pdf OUT.pdf] [--png OUTDIR] [--thumbnail W] [--format memo|document]
    publishing pdf-pages   SRC.pdf  [--png OUTDIR] [--thumbnail W]

and `render(src, ...)` / `pdf_pages(src, ...)` for callers in Python (a RenderError's `exit_code` is the
command's). README "Render" is the contract; docs/user-content.md the safety model.

- Mode. User-content mode (usercontent.py) is the default and the only mode a service gets: Chromium's
  sandbox on and verified, no network, nothing outside the source's own folder, no script, and the
  byte, page, time and memory limits. `trusted=True` (`--trusted`) is the house build's renderer
  (sandbox off, file:// pages, no request filter, no limits on the render): for a repository's own
  sources, never for a person's content. With PUBLISHING_USER_CONTENT=1 in the environment (a
  service's image) trusted mode is refused.
- Markdown. render-md turns the markdown into the house memo or document page (markdown.py) in a
  supervised child (time and memory limits, no network, no secrets), then renders it like an HTML file
  whose folder is the markdown's. It runs no house scan (secrets, private words): that is a report
  rule, not a safety one.
- Images. raster.py draws pages with PDFium in a supervised child: `page-001.png`, ... at `width`
  pixels, and `thumbnail.png`, the first page at `thumbnail` pixels. pdf-pages does that alone, for a
  PDF from anywhere.
- Outputs. The PDF goes to `pdf`, or beside SRC with the suffix .pdf when neither `pdf` nor `png` is
  given (pdf-pages writes no PDF). Images go to `png`; the thumbnail goes to `png`/thumbnail.png, or
  without `png` beside the PDF (SRC for pdf-pages) as <stem>.thumbnail.png. Nothing is overwritten:
  an existing PDF or thumbnail, or a `png` folder already holding page-*.png or thumbnail.png, is a
  usage error before anything runs. On any failure nothing is written.
- Limits. `timeout` is the wall clock of the whole call: render and images. `max_pages` caps the PDF
  and the images, `max_bytes` the source and what it loads (pdf-pages: the PDF), `max_memory_mb`
  each child's private memory.
- Exit codes. 0 done; 1 the render failed (a limit, a hostile or broken source, a crash); 2 usage
  (no such source, wrong suffix, an output exists, a bad option, --trusted under
  PUBLISHING_USER_CONTENT=1); 3 the toolchain or the host cannot run it safely (no Chromium, no
  sandbox, no network namespace with require_netns).
"""
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from . import raster
from .usercontent import Limits, UserContentError, UserContentRenderer, _supervise, netns_available, render_html

HTML = (".html", ".htm")
MARKDOWN = (".md", ".markdown")
PAPERS = ("letter", "a4")
WIDTH = 1400  # default page-image width, pixels


class RenderError(Exception):
    """The render failed (exit 1). Subclasses carry their own exit code."""
    exit_code = 1


class UsageError(RenderError):
    exit_code = 2


class NotReady(RenderError):
    """The toolchain is missing, or this host or container cannot render safely (exit 3)."""
    exit_code = 3


@dataclass
class Rendered:
    mode: str  # "user-content" or "trusted"
    pages: int
    pdf: Path | None = None
    images: list = field(default_factory=list)
    thumbnail: Path | None = None
    blocked: list = field(default_factory=list)  # every request the user-content filter refused
    sandboxed: bool = False  # Chromium's sandbox, verified (pdf-pages runs no Chromium)
    netns: bool = False  # every child ran without a network
    problems: list = field(default_factory=list)  # the house layout lint (render-md); advice, not failure

    def written(self) -> list[Path]:
        return [p for p in (self.pdf, *self.images, self.thumbnail) if p]

    def as_json(self) -> dict:
        d = asdict(self)
        d.update(pdf=str(self.pdf) if self.pdf else None, images=[str(p) for p in self.images],
                 thumbnail=str(self.thumbnail) if self.thumbnail else None)
        return d


# ---------------------------------------------------------------- the entries

def render(src, *, pdf=None, png=None, thumbnail: int | None = None, width: int = WIDTH, paper: str | None = None,
           fmt: str | None = None, limits: Limits | None = None, trusted: bool = False) -> Rendered:
    """Render the HTML or markdown file `src` (by its suffix) to a PDF and/or page images and a thumbnail."""
    src = Path(src)
    limits = limits or Limits()
    kind = "html" if src.suffix.lower() in HTML else "md" if src.suffix.lower() in MARKDOWN else None
    if kind is None:
        raise UsageError(f"{src}: not an HTML ({', '.join(HTML)}) or markdown ({', '.join(MARKDOWN)}) file")
    if not src.is_file():
        raise UsageError(f"{src}: no such file")
    if trusted and os.environ.get("PUBLISHING_USER_CONTENT") == "1":
        raise UsageError("trusted mode is refused here: PUBLISHING_USER_CONTENT=1 (a service renders user content)")
    if paper is not None and paper not in PAPERS:
        raise UsageError(f"paper must be letter or a4, not {paper!r}")
    if fmt is not None and (kind != "md" or fmt not in ("memo", "document")):
        raise UsageError("a format (memo or document) is for markdown only")
    pdf_out = Path(pdf) if pdf else (src.with_suffix(".pdf") if png is None else None)
    png_dir, thumb_out = _plan(pdf_out or src, png, thumbnail, width)
    _check_free(pdf_out, png_dir, thumb_out)
    if not trusted and src.stat().st_size > limits.max_bytes:
        raise RenderError(f"{src.name} is {src.stat().st_size} bytes, over the input limit of {limits.max_bytes}")
    deadline = time.monotonic() + limits.timeout
    with tempfile.TemporaryDirectory(prefix="publishing-render-") as tmp:
        tmp = Path(tmp)
        staged = tmp / "out.pdf"
        try:
            if kind == "html" and trusted:
                result = _trusted_html(src, staged, paper or "letter")
            elif kind == "html":
                r = render_html(src, staged, paper=paper or "letter", limits=limits)
                result = Rendered("user-content", r.pages, blocked=r.blocked, sandboxed=r.sandboxed, netns=r.netns)
            else:
                result = _markdown(src, staged, tmp, fmt, paper, limits, deadline, trusted)
            images = _images(staged, tmp, png_dir, thumbnail, width, limits, deadline, src.name)
        except UserContentError as e:
            raise _classify(e) from None
        if images:
            result.netns = result.netns and images.netns
        _place(result, staged if pdf_out else None, pdf_out, images, png_dir, thumb_out)
    return result


def pdf_pages(src, *, png=None, thumbnail: int | None = None, width: int = WIDTH,
              limits: Limits | None = None) -> Rendered:
    """Draw the pages of the PDF `src` (from anywhere: it is treated as hostile) as images."""
    src = Path(src)
    limits = limits or Limits()
    if src.suffix.lower() != ".pdf":
        raise UsageError(f"{src}: not a PDF (.pdf)")
    if not src.is_file():
        raise UsageError(f"{src}: no such file")
    if png is None and not thumbnail:
        raise UsageError("nothing to write: give --png OUTDIR, --thumbnail W, or both")
    png_dir, thumb_out = _plan(src, png, thumbnail, width)
    _check_free(None, png_dir, thumb_out)
    deadline = time.monotonic() + limits.timeout
    with tempfile.TemporaryDirectory(prefix="publishing-pages-") as tmp:
        tmp = Path(tmp)
        try:
            images = _images(src, tmp, png_dir, thumbnail, width, limits, deadline, src.name)
        except UserContentError as e:
            raise _classify(e) from None
        result = Rendered("user-content", images.pages, netns=images.netns)
        _place(result, None, None, images, png_dir, thumb_out)
    return result


# ---------------------------------------------------------------- outputs

def _plan(base: Path, png, thumbnail, width) -> tuple[Path | None, Path | None]:
    for name, w in (("--width", width), ("--thumbnail", thumbnail)):
        if w is not None and not 1 <= w <= raster.MAX_WIDTH:
            raise UsageError(f"{name} {w}: a width in pixels from 1 to {raster.MAX_WIDTH}")
    png_dir = Path(png) if png is not None else None
    if not thumbnail:
        return png_dir, None
    return png_dir, (png_dir / "thumbnail.png" if png_dir else base.with_suffix(".thumbnail.png"))


def _check_free(pdf_out: Path | None, png_dir: Path | None, thumb_out: Path | None) -> None:
    for p in (pdf_out, thumb_out):
        if p is not None and p.exists():
            raise UsageError(f"{p} exists; never overwrite")
    if png_dir is not None:
        if png_dir.exists() and not png_dir.is_dir():
            raise UsageError(f"{png_dir}: not a folder")
        old = sorted(png_dir.glob("page-*.png")) if png_dir.is_dir() else []
        if old:
            raise UsageError(f"{png_dir} already holds page images ({old[0].name}); never overwrite")


def _images(pdf: Path, tmp: Path, png_dir, thumbnail, width, limits: Limits, deadline: float, name: str):
    if png_dir is None and not thumbnail:
        return None
    try:
        return raster.rasterize(pdf, tmp / "png", width=width if png_dir else None, thumbnail=thumbnail,
                                limits=replace(limits, timeout=_left(deadline, limits)), name=name)
    except UserContentError as e:
        if "time limit" in str(e):  # the child got what was left of the budget: name the whole budget
            raise UserContentError(f"{name}: over the time limit of {limits.timeout:g} s (render and images)") from None
        raise


def _place(result: Rendered, staged: Path | None, pdf_out: Path | None, images, png_dir, thumb_out) -> None:
    """Copy the staged outputs into place, none over an existing file; on failure remove what was written."""
    moves = []
    if staged is not None:
        moves.append((staged, pdf_out))
    if images is not None:
        moves += [(f, png_dir / f.name) for f in images.files]
        if images.thumbnail is not None:
            moves.append((images.thumbnail, thumb_out))
    written = []
    try:
        for a, b in moves:
            b.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(a, "rb") as f, open(b, "xb") as out:
                    written.append(b)
                    shutil.copyfileobj(f, out)
            except FileExistsError:  # it appeared since the check: refuse, and undo the rest
                raise UsageError(f"{b} exists; never overwrite") from None
    except BaseException:
        for p in written:
            p.unlink(missing_ok=True)
        raise
    result.pdf = pdf_out if staged is not None else None
    result.images = [png_dir / f.name for f in images.files] if images is not None else []
    result.thumbnail = thumb_out if images is not None and images.thumbnail is not None else None


def _classify(e: UserContentError) -> RenderError:
    """Exit 3 when the host or the toolchain is the problem, 1 when the source is."""
    msg = str(e)
    if any(s in msg for s in ("could not start its sandbox", "require_netns", "Executable doesn't exist",
                              "playwright install", "needs Linux")):
        return NotReady(msg)
    return RenderError(msg)


# ---------------------------------------------------------------- the renders

def _trusted_html(src: Path, out: Path, paper: str) -> Rendered:
    from playwright.sync_api import Error as PlaywrightError

    from .render import Renderer, ToolchainError

    try:
        with Renderer() as r:
            problems, _ = r.pdf(src, out, kind="html", paper=paper)
    except ToolchainError as e:
        raise NotReady(str(e)) from None
    except PlaywrightError as e:
        raise RenderError(f"{src.name}: render failed: {str(e).splitlines()[0][:400]}") from None
    from . import pdf

    return Rendered("trusted", pdf.pages(out), problems=problems)


def _markdown(src: Path, out: Path, tmp: Path, fmt, paper, limits: Limits, deadline: float, trusted: bool) -> Rendered:
    """Markdown to the house memo or document page, then to `out`; a document fills its contents'
    page numbers in up to four more passes, as a build does."""
    from . import markdown, pdf
    from .build import _named_pages

    meta, _ = markdown.front_matter(src.read_text(errors="replace"))
    fmt = fmt or meta.get("format", "memo")
    paper = paper or meta.get("paper", "letter")
    if fmt not in ("memo", "document"):
        raise UsageError(f"{src.name}: format must be memo or document, not {fmt!r}")
    if paper not in PAPERS:
        raise UsageError(f"{src.name}: paper must be letter or a4, not {paper!r}")
    work = tmp / f"{src.stem}.html"
    if trusted:
        from playwright.sync_api import Error as PlaywrightError

        from .render import Renderer, ToolchainError

        try:
            with Renderer() as r:
                problems, found = None, None
                for _ in range(5):
                    work.write_text(page_html(src, fmt, paper, found, untrusted=False))
                    problems, _ = r.pdf(work, out, kind=fmt, paper=paper)
                    if fmt == "memo" or _named_pages(out) == found:
                        break
                    found = _named_pages(out)
        except ToolchainError as e:
            raise NotReady(str(e)) from None
        except PlaywrightError as e:
            raise RenderError(f"{src.name}: render failed: {str(e).splitlines()[0][:400]}") from None
        return Rendered("trusted", pdf.pages(out), problems=problems)
    r = UserContentRenderer(limits)
    blocked, netns, found = [], True, None
    with r:
        for _ in range(5):
            r.limits = replace(limits, timeout=_left(deadline, limits))
            _page_html_child(src, fmt, paper, found, work, r.limits)
            r.url(src.parent.resolve())  # the page's folder: everything it may load
            r.limits = replace(limits, timeout=_left(deadline, limits))
            out.unlink(missing_ok=True)
            problems, _ = r.pdf(work, out, kind=fmt, paper=paper)
            res = r.results[-1]
            blocked += res.blocked
            netns = netns and res.netns
            if fmt == "memo" or _named_pages(out) == found:
                break
            found = _named_pages(out)
    return Rendered("user-content", res.pages, blocked=list(dict.fromkeys(blocked)), sandboxed=res.sandboxed,
                    netns=netns, problems=problems)


def _left(deadline: float, limits: Limits) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise UserContentError(f"over the time limit of {limits.timeout:g} s")
    return left


def page_html(src: Path, fmt: str, paper: str, pages_by_id: dict | None, *, untrusted: bool) -> str:
    """The house page for the markdown file `src`: the build's memo or document template, with no
    report.toml (a person's folder must not steer it). `untrusted` maps the theme and the folder onto
    user-content mode's virtual origin and inlines SVGs from inside the folder only."""
    from .build import Source, _page_html
    from .config import Config
    from .render import Renderer

    s = Source(fmt, src.resolve(), src.with_suffix(".pdf"), paper)
    return _page_html(s, Config(root=src.parent.resolve()), pages_by_id,
                      r=UserContentRenderer() if untrusted else Renderer)


def _page_html_child(src: Path, fmt: str, paper: str, pages_by_id, work: Path, limits: Limits) -> None:
    """page_html() in a supervised child: markdown and code highlighting of a person's text run under the
    time and memory limits, with no network and no secrets, like the render."""
    job = work.with_suffix(".job.json")
    job.write_text(json.dumps({"src": str(src.resolve()), "fmt": fmt, "paper": paper, "pages": pages_by_id,
                               "out": str(work)}))
    work.unlink(missing_ok=True)
    cmd = [sys.executable, "-m", "publishing.renderhtml", str(job)]
    if netns_available():
        cmd = ["unshare", "--user", "--net", "--map-current-user", "--", *cmd]
    with open(work.with_suffix(".stderr"), "w+b") as err:
        code, why = _supervise(cmd, work.parent, err, limits)
        err.seek(0)
        stderr = err.read().decode(errors="replace")
    if why:
        raise UserContentError(f"{src.name}: turning the markdown into a page went {why}")
    if code != 0 or not work.is_file():
        raise UserContentError(f"{src.name}: the markdown did not convert: {stderr.strip()[-400:]}")


def _child(job_path: str) -> int:
    job = json.loads(Path(job_path).read_text())
    Path(job["out"]).write_text(page_html(Path(job["src"]), job["fmt"], job["paper"], job["pages"], untrusted=True))
    return 0


# ---------------------------------------------------------------- the commands

def _positive(kind):
    def parse(text):
        try:
            value = kind(text)
        except ValueError:
            value = 0
        if value <= 0:
            import argparse

            raise argparse.ArgumentTypeError(f"{text!r} is not a positive number")
        return value
    return parse


def add_arguments(p, what: str) -> None:
    """The options of render-html (`what` "html"), render-md ("md") and pdf-pages ("pdf")."""
    d = Limits()
    p.add_argument("src", help={"html": "the HTML file; it may load files from its own folder only",
                                "md": "the markdown file; it may load files from its own folder only",
                                "pdf": "the PDF (treated as hostile)"}[what])
    if what != "pdf":
        p.add_argument("--pdf", metavar="OUT", help="the PDF path (default: beside SRC, suffix .pdf, unless --png)")
    p.add_argument("--png", metavar="OUTDIR", help="write one image per page: OUTDIR/page-001.png, ...")
    p.add_argument("--thumbnail", type=_positive(int), metavar="W",
                   help="write the first page W pixels wide: OUTDIR/thumbnail.png, or <stem>.thumbnail.png "
                        "beside the PDF")
    p.add_argument("--width", type=_positive(int), default=WIDTH, metavar="PX",
                   help=f"page image width (default {WIDTH})")
    if what != "pdf":
        p.add_argument("--paper", choices=PAPERS, help="unless the page sets @page size (default letter)")
        p.add_argument("--allow-js", action="store_true", help="run the page's script (still no network)")
        p.add_argument("--trusted", action="store_true",
                       help="the house build's renderer: sandbox off, no filter. NOT for user content")
    if what == "md":
        p.add_argument("--format", dest="fmt", choices=("memo", "document"),
                       help="the house format (default: front matter, else memo)")
    p.add_argument("--max-bytes", type=_positive(int), default=d.max_bytes, metavar="N",
                   help=f"cap on the source plus what it loads (default {d.max_bytes})")
    p.add_argument("--max-pages", type=_positive(int), default=d.max_pages, metavar="N",
                   help=f"page cap (default {d.max_pages})")
    p.add_argument("--timeout", type=_positive(float), default=d.timeout, metavar="SECONDS",
                   help=f"wall clock of the whole call (default {d.timeout:g})")
    p.add_argument("--max-memory", type=_positive(int), default=d.max_memory_mb, metavar="MB",
                   help=f"memory cap of each render child (default {d.max_memory_mb})")
    p.add_argument("--require-netns", action="store_true", help="fail (exit 3) unless every child gets no network")
    p.add_argument("--json", action="store_true", help="print the result as one JSON line")
    p.set_defaults(fn=run, what=what)


def run(a) -> int:
    limits = Limits(max_bytes=a.max_bytes, max_pages=a.max_pages, timeout=a.timeout, max_memory_mb=a.max_memory,
                    allow_js=getattr(a, "allow_js", False), require_netns=a.require_netns)
    try:
        if a.what == "pdf":
            r = pdf_pages(a.src, png=a.png, thumbnail=a.thumbnail, width=a.width, limits=limits)
        else:
            if a.what == "html" and Path(a.src).suffix.lower() not in HTML:
                raise UsageError(f"{a.src}: not an HTML file ({', '.join(HTML)}); markdown is render-md")
            if a.what == "md" and Path(a.src).suffix.lower() not in MARKDOWN:
                raise UsageError(f"{a.src}: not a markdown file ({', '.join(MARKDOWN)})")
            r = render(a.src, pdf=a.pdf, png=a.png, thumbnail=a.thumbnail, width=a.width, paper=a.paper,
                       fmt=getattr(a, "fmt", None), limits=limits, trusted=a.trusted)
    except RenderError as e:
        print(f"publishing: {e}", file=sys.stderr)
        return e.exit_code
    if a.json:
        print(json.dumps(r.as_json()))
    else:
        for p in r.written():
            print(p)
    return 0


if __name__ == "__main__":
    sys.exit(_child(sys.argv[1]))
