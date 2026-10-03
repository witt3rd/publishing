"""publishing new | build | check | publish | setup | compare | html | render-html | render-md | pdf-pages
| convert | extract

Exit codes (the service contract, README "Services"): 0 done; 1 a source failed its build or a
check found a difference; 2 usage or configuration error; 3 the toolchain is not installed or broken.

Install profiles: `render` (everything but convert: Playwright and Chromium; `video` adds to it) and
`convert` (Office to PDF: the standard library and office2pdf). This module imports in either; a render
command run in the convert profile says how to install the render profile (exit 3)."""
import argparse
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
from importlib import resources
from pathlib import Path

from . import __version__, convert, extract, renderhtml
from .config import ConfigError, load

# The top-level modules the render extra (pyproject.toml) installs.
RENDER_MODULES = {"playwright", "greenlet", "pyee", "markdown_it", "mdit_py_plugins", "mdurl", "pygments",
                  "pypdf", "pypdfium2", "PIL"}
try:
    from . import pdf, video
    from .build import MARKERS, BuildError, build, check, deck_html, discover, resolve
    from .publish import PublishError, publish
    from .render import Renderer, ToolchainError
    from .usercontent import Limits, UserContentError, UserContentRenderer, render_html
    NO_RENDER = None
except ModuleNotFoundError as e:  # the convert profile: the render extra is not installed
    if (e.name or "").split(".")[0] not in RENDER_MODULES:
        raise
    NO_RENDER = e

    class BuildError(Exception):
        """Stands in for build.BuildError, which the convert profile cannot import."""

    class ToolchainError(Exception):
        """Stands in for render.ToolchainError, which the convert profile cannot import."""

REPO = "https://github.com/witt3rd/publishing"
FORMATS = ("deck", "memo", "document", "video")


def usage(msg: str):
    print(f"publishing: {msg}", file=sys.stderr)
    sys.exit(2)


def _pinned(cfg, argv) -> None:
    """Run the version the repo pins (report.toml `publishing`), re-executing through uvx if needed."""
    if not cfg.pin or cfg.pin == __version__:
        return
    docs = cfg.root / "docs"
    videos = cfg.path is not None and docs.is_dir() and any(docs.rglob("video.html"))
    spec = f"publishing[{'render,video' if videos else 'render'}] @ git+{REPO}@v{cfg.pin}"
    cmd = ["uvx", "--from", spec, "publishing", *argv]
    if os.environ.get("PUBLISHING_PINNED") or not shutil.which("uvx"):
        print(f"publishing: {cfg.path} pins {cfg.pin}, this is {__version__}. Run: {' '.join(cmd)}", file=sys.stderr)
        sys.exit(3)
    print(f"publishing: {cfg.path.name} pins {cfg.pin}; running it through uvx", file=sys.stderr)
    os.execvpe("uvx", cmd, {**os.environ, "PUBLISHING_PINNED": "1"})


def cmd_new(a) -> int:
    folder = Path(a.folder)
    if folder.exists():
        usage(f"{folder} exists; never overwrite (bump the version)")
    cfg = load(folder.parent if folder.parent.exists() else Path.cwd())
    tpl = resources.files("publishing").joinpath("templates", a.format)
    folder.mkdir(parents=True)
    for f in tpl.iterdir():
        if not f.is_file():  # an installer's bytecode cache (__pycache__ beside slides.py)
            continue
        text = f.read_text().replace("{name}", folder.name).replace("{rel}", str(folder))
        text = text.replace("{kicker}", cfg.project or "Report")
        (folder / f.name).write_text(text)
    print(f"created {folder}/ ({a.format}); write it, then: publishing build {folder}")
    return 0


def _sources(a, cfg):
    if a.targets:
        return [resolve(Path(t), cfg, a.format, Path(a.output) if a.output else None) for t in a.targets], []
    where = cfg.root / "docs"
    sources, orphans = discover(where if where.is_dir() else cfg.root, cfg)
    return sources, orphans


def _renderer(a, cfg):
    """The trusted renderer, or user-content mode when `--user-content`, report.toml or the
    environment (PUBLISHING_USER_CONTENT=1, for a service's image: no flag can turn it off) asks."""
    if a.user_content or cfg.user_content or os.environ.get("PUBLISHING_USER_CONTENT") == "1":
        return UserContentRenderer(cfg.user_content or Limits())
    return Renderer()


def cmd_build(a) -> int:
    if a.output and len(a.targets) != 1:
        usage("--output takes exactly one source")
    cfg = load(Path(a.targets[0]) if a.targets else Path.cwd())
    if cfg.path is None and a.output:  # a source outside the repo (a staged copy): the output's repo config
        cfg = load(Path(a.output).resolve().parent)
    _pinned(cfg, sys.argv[1:])
    sources, _ = _sources(a, cfg)
    if not sources:
        usage("nothing to build (no source folders under docs/)")
    failed = 0
    with _renderer(a, cfg) as r:
        for s in sources:
            try:
                state = build(s, cfg, r, force=a.force, png=Path(a.png) / s.pdf.stem if a.png else None)
            except (BuildError, UserContentError) as e:
                print(f"publishing: {e}", file=sys.stderr)
                failed += 1
                continue
            print(f"{state:8} {_rel(s.pdf)} ({_size(s.pdf)})", flush=True)
    return 1 if failed else 0


def cmd_check(a) -> int:
    targets = a.targets or []
    cfg = load(Path(targets[0]) if targets else Path.cwd())
    _pinned(cfg, sys.argv[1:])
    sources, orphans = [], []
    for t in targets or [None]:
        p = Path(t) if t else (cfg.root / "docs" if (cfg.root / "docs").is_dir() else cfg.root)
        if p.is_dir() and not any((p / m).is_file() for m in MARKERS):
            s, o = discover(p, cfg)
            sources += s
            orphans += o
        else:
            sources.append(resolve(p, cfg))
    problems = [f"{_rel(o)}: no source (a folder {o.stem}/ or a [[document]] entry)" for o in orphans]
    with _renderer(a, cfg) as r:
        for s in sources:
            try:
                bad = check(s, cfg, r)
            except (BuildError, UserContentError) as e:
                bad = str(e)
            if bad:
                problems.append(bad)
            else:
                print(f"current  {_rel(s.pdf)}", flush=True)
    print(f"publishing {__version__}: {len(sources)} checked, {len(problems)} problem(s)", flush=True)
    for p in problems:
        print(f"publishing: {p}", file=sys.stderr)
    return 1 if problems else 0


def cmd_publish(a) -> int:
    cfg = load(Path(a.target))
    try:
        s = resolve(Path(a.target), cfg)
        state, target = publish(s, cfg, name=a.name)
    except (PublishError, BuildError) as e:
        sys.exit(f"publishing: {e}")
    size = f" ({_size(target)})" if target.suffix in (".pdf", ".mp4") else ""
    print(f"{state}: {target}{size}")
    return 0


def _no_render(what: str):
    """Exit 3: `what` needs the render profile and this install is the convert profile."""
    print(f"publishing: {what} needs the render profile (Playwright and Chromium), which is not installed "
          f"({NO_RENDER}).\n  Install it: uv tool install 'publishing[render] @ git+{REPO}@v{__version__}'",
          file=sys.stderr)
    sys.exit(3)


def cmd_setup(a) -> int:
    if a.convert:
        code = convert.setup(a.bin_dir)
        if code or not a.render:
            return code
    if NO_RENDER:
        _no_render("setup --render")
    cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
    if a.with_deps:
        cmd.insert(4, "--with-deps")
    code = subprocess.call(cmd)
    if code or not a.video:
        return code
    return video.setup()


def cmd_compare(a) -> int:
    """A house-style deck that puts pages of two PDFs side by side."""
    from .page import Deck

    old, new, out = Path(a.old).resolve(), Path(a.new).resolve(), Path(a.output)
    if out.exists():
        usage(f"{out} exists; never overwrite (bump the version)")
    try:
        pairs = [(int(p.split(":")[0]), int(p.split(":")[1]), p.split(":", 2)[2] if p.count(":") >= 2 else "")
                 for p in a.pair] or [(i, i, "") for i in range(1, min(pdf.pages(old), pdf.pages(new), 6) + 1)]
    except (ValueError, IndexError):
        usage("--pair is OLD:NEW or OLD:NEW:caption (page numbers from 1)")
    notes = Path(a.notes).read_text().splitlines() if a.notes else []
    points = [n[2:].strip() for n in notes if n.startswith(("- ", "* "))]
    cfg = load(Path.cwd())
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        imgs = {"old": pdf.png(old, tmp / "img" / "old", width=1600), "new": pdf.png(new, tmp / "img" / "new", width=1600)}
        n_old, n_new = len(imgs["old"]), len(imgs["new"])
        d = Deck(tmp, out.stem)
        lab_old, lab_new = html.escape(a.old_label), html.escape(a.new_label)
        d.title(html.escape(a.kicker), html.escape(a.title), html.escape(a.subtitle), points,
                f"{lab_old}: {n_old} pages · {lab_new}: {n_new} pages")
        for po, pn, cap in pairs:
            if not (1 <= po <= n_old and 1 <= pn <= n_new):
                usage(f"pair {po}:{pn} is out of range ({n_old} and {n_new} pages)")
            body = (f'<div class="pair"><figure><figcaption><b>{lab_old}</b> · page {po} of {n_old}</figcaption>'
                    f'<img src="{imgs["old"][po - 1].relative_to(tmp)}"></figure>'
                    f'<figure><figcaption><b>{lab_new}</b> · page {pn} of {n_new}</figcaption>'
                    f'<img src="{imgs["new"][pn - 1].relative_to(tmp)}"></figure></div>')
            d.slide("Side by side", html.escape(cap) or f"{lab_old} page {po}, {lab_new} page {pn}", "", body,
                    f"{lab_old} page {po} · {lab_new} page {pn}", cls="tight compare")
        page_html = deck_html(d.S, tmp, out.stem)
        work = tmp / "compare.html"
        work.write_text(page_html)
        fresh = tmp / "compare.pdf"
        with Renderer() as r:
            problems, _ = r.pdf(work, fresh, kind="deck")
        if problems:
            sys.exit("publishing: compare deck failed lint:\n  " + "\n  ".join(problems))
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "xb") as f:
            f.write(fresh.read_bytes())
    print(f"wrote {out} ({pdf.pages(out)} pages)")
    return 0


def cmd_html(a) -> int:
    """A person's HTML file to PDF, always in user-content mode: the entry for services."""
    out = Path(a.output)
    if out.exists():
        usage(f"{out} exists; never overwrite")
    for name in ("max_bytes", "max_pages", "timeout", "max_memory"):
        if getattr(a, name) is not None and getattr(a, name) <= 0:
            usage(f"--{name.replace('_', '-')} must be positive")
    d = Limits()
    limits = Limits(max_bytes=a.max_bytes or d.max_bytes, max_pages=a.max_pages or d.max_pages,
                    timeout=a.timeout or d.timeout, max_memory_mb=a.max_memory or d.max_memory_mb,
                    allow_js=a.allow_js, require_netns=a.require_netns)
    try:
        r = render_html(Path(a.source), out, paper=a.paper, limits=limits)
    except UserContentError as e:
        sys.exit(f"publishing: {e}")
    if a.json:
        print(json.dumps({"output": str(out), "pages": r.pages, "blocked": r.blocked, "sandboxed": r.sandboxed,
                          "netns": r.netns}))
    else:
        print(f"wrote {out} ({r.pages} pages; {len(r.blocked)} request(s) refused; "
              f"network namespace {'on' if r.netns else 'off'})")
    return 0


def _size(p: Path) -> str:
    return video.describe(p) if p.suffix == ".mp4" else f"{pdf.pages(p)} pages"


def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(p)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="publishing", description="House-style decks, memos and documents to PDF, "
                                 "videos to MP4, HTML and markdown to PDF and page images, Office files to PDF. "
                                 "Report rules: ~/Documents/AGENTS.md.")
    ap.add_argument("--version", action="version", version=f"publishing {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new", help="scaffold docs/<kind>/<topic>-v1/")
    p.add_argument("folder")
    p.add_argument("--format", choices=FORMATS, default="deck")
    p.set_defaults(fn=cmd_new, needs_render=False)

    for name, fn, hlp in (("build", cmd_build, "build PDFs (and MP4s) beside their sources"),
                          ("check", cmd_check, "fail unless every PDF and MP4 matches a fresh build of its source")):
        p = sub.add_parser(name, help=hlp)
        p.add_argument("targets", nargs="*", help="source folders, markdown files, PDFs or MP4s (default: docs/)")
        if name == "build":
            p.add_argument("-o", "--output", help="the PDF or MP4 path (one source only)")
            p.add_argument("--format", choices=FORMATS, help="override the format")
            p.add_argument("--force", action="store_true", help="rewrite even when the output is current")
            p.add_argument("--png", metavar="DIR", help="also write one PNG per page (video: per second) under DIR/<name>/")
        else:
            p.set_defaults(format=None, output=None)
        p.add_argument("--user-content", action="store_true",
                       help="render as untrusted content: sandbox on, no network, no files outside the source")
        p.set_defaults(fn=fn)

    p = sub.add_parser("publish", help="copy a built report to ~/Documents/<folder>/ (never overwrites)")
    p.add_argument("target")
    p.add_argument("--name", help="published name without extension (kebab-case, -vN)")
    p.set_defaults(fn=cmd_publish)

    p = sub.add_parser("setup", help="install the pinned Chromium (and HyperFrames, office2pdf) into the user cache")
    p.add_argument("--render", action="store_true", help="the pinned Chromium (the default without --convert)")
    p.add_argument("--with-deps", action="store_true", help="also Chromium's OS libraries (CI; needs sudo)")
    p.add_argument("--video", action="store_true", help="also the pinned HyperFrames, for videos (the video extra)")
    p.add_argument("--convert", action="store_true", help=f"the pinned office2pdf {convert.VERSION}, checksummed")
    p.add_argument("--bin-dir", metavar="DIR", help="install office2pdf as DIR/office2pdf (default: the user cache)")
    p.set_defaults(fn=cmd_setup, needs_render=False)

    p = sub.add_parser("compare", help="a deck of two PDFs' pages side by side (before/after)")
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--pair", action="append", default=[], metavar="OLD:NEW[:CAPTION]",
                   help="page pairs, with an optional headline (default 1:1 .. 6:6)")
    p.add_argument("--notes", help="markdown file; its '- ' bullets go on the title page")
    p.add_argument("--title", default="Before and after")
    p.add_argument("--subtitle", default="The same source, rendered by the old and the new toolchain")
    p.add_argument("--kicker", default="PDF comparison")
    p.add_argument("--old-label", default="Before")
    p.add_argument("--new-label", default="After")
    p.set_defaults(fn=cmd_compare)

    p = sub.add_parser("html", help="render an untrusted HTML file to PDF (always user-content mode)")
    p.add_argument("source", help="the HTML file; it may load files from its own folder only")
    p.add_argument("-o", "--output", required=True, help="the PDF path (never overwritten)")
    p.add_argument("--paper", choices=("letter", "a4"), default="letter", help="unless the page sets @page size")
    p.add_argument("--allow-js", action="store_true", help="run the page's script (still no network)")
    p.add_argument("--max-bytes", type=int, help="cap on the page plus what it loads (default 50 MiB)")
    p.add_argument("--max-pages", type=int, help="page cap (default 300)")
    p.add_argument("--timeout", type=float, help="wall-clock seconds (default 60)")
    p.add_argument("--max-memory", type=int, metavar="MB", help="memory cap of the render (default 2048)")
    p.add_argument("--require-netns", action="store_true", help="fail unless the render gets no network namespace")
    p.add_argument("--json", action="store_true", help="print the result as one JSON line")
    p.set_defaults(fn=cmd_html)

    for name, what, hlp in (
            ("render-html", "html", "HTML to a PDF, page images and a thumbnail (user-content mode unless --trusted)"),
            ("render-md", "md", "markdown to a house memo or document PDF, page images and a thumbnail (likewise)"),
            ("pdf-pages", "pdf", "a PDF's pages to images and a thumbnail (PDFium, supervised)")):
        p = sub.add_parser(name, help=hlp, description="Exit codes: 0 done (stdout: each file written, or --json); "
                           "1 the render failed; 2 usage; 3 the toolchain or host cannot render safely. "
                           "README \"Render\".")
        renderhtml.add_arguments(p, what)

    p = sub.add_parser("convert", help="an Office file (.docx, .xlsx, .pptx) to a PDF, through office2pdf",
                       description="Exit codes: 0 converted (stdout: the PDF's path); 1 the conversion failed; "
                       "2 usage; 3 no converter (OFFICE2PDF_BIN, or `publishing setup --convert`).")
    convert.add_arguments(p)

    p = sub.add_parser("extract", help="a document (pdf, docx, pptx, xlsx, html, csv, json, xml, epub) to markdown, through markitdown",
                       description="Exit codes: 0 extracted (stdout: the markdown's path); 1 the extraction failed or found no text; "
                       "2 usage; 3 markitdown is not installed (the `extract` extra). Makes no network calls.")
    extract.add_arguments(p)

    a = ap.parse_args(argv)
    if a.cmd == "setup":
        a.render = a.render or a.video or not a.convert
    if NO_RENDER and getattr(a, "needs_render", True):
        _no_render(a.cmd)
    try:
        return a.fn(a)
    except ConfigError as e:
        usage(str(e))
    except BuildError as e:  # a target that is not a source: a usage error, not a failed build
        usage(str(e))
    except ToolchainError as e:
        print(f"publishing: {e}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    sys.exit(main())
