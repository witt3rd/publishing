"""PDF tools through pypdf: `publishing pdf merge|pages|strip|split`, and the functions below for callers in Python.

pypdf only (exact pin in the `pdf` extra); no Playwright, no Chromium, no PDFium, no network.

- In: local files, by path, with the suffix .pdf. A URL, a device or a pipe is refused. A file that does not
  start with %PDF- or that is encrypted is refused; so is one over MAX_INPUT_BYTES.
- Out: one .pdf, built in a temporary folder beside it and linked into place: an existing OUT is never
  overwritten (exit 2) and a failure or a limit leaves no OUT. The path is the only line on stdout.
- Clean: an output holds the chosen pages and nothing else of its sources. The document info, XMP, outlines,
  named destinations, form, attached files, JavaScript and page-level metadata are not copied; annotations that
  could run or fetch something (JavaScript, launch, form-submit and remote-go-to actions, widgets, file
  attachments, screens, movies, sound, 3D, rich media) are dropped; plain links (URI, go-to) stay. The output
  carries one fixed /Producer and nothing else.
- Deterministic: the same pypdf build turns the same inputs into the same bytes.
- Limits: TIMEOUT seconds of wall clock (the work runs in a child process that is killed), MAX_INPUT_BYTES per
  input, MAX_PAGES of output, MAX_BYTES of output.

- Split: `split` writes the pages of one PDF as consecutive parts of N pages each into a folder, named
  `<stem>-001.pdf`, `<stem>-002.pdf`, ... Parts are cleaned like any output. Nothing in the folder is
  overwritten (exit 2, nothing written); a failure or a limit leaves no part. Each part's path is a line on stdout.

Exit codes of the command: 0 done, 1 a PDF could not be read or a limit was hit, 2 usage (unsupported type,
no such source, the output exists, a bad page range), 3 pypdf is not installed.
"""
import argparse
import multiprocessing
import os
import shutil
import sys
import tempfile
from pathlib import Path

from ._shared import local_dest, local_source, positive

SUFFIXES = (".pdf",)
PRODUCER = "publishing"
TIMEOUT = 60.0
MAX_INPUT_BYTES = 128 * 2**20
MAX_PAGES = 2000  # of output
MAX_BYTES = 256 * 2**20  # output
MAX_INPUTS = 100

# An annotation is dropped when its subtype is here, or it carries an action other than a link.
_DROP_SUBTYPES = {"/Widget", "/FileAttachment", "/Screen", "/Movie", "/Sound", "/3D", "/RichMedia"}
_KEEP_ACTIONS = {"/URI", "/GoTo"}


class PdfError(Exception):
    """A PDF could not be read or written, or a limit was hit (exit 1). Subclasses carry their own code."""
    exit_code = 1


class UsageError(PdfError):
    exit_code = 2


class ToolNotFound(PdfError):
    exit_code = 3


def _pypdf():
    try:
        import pypdf
    except ImportError:
        raise ToolNotFound("pypdf is not installed (the `pdf` extra, or the pdf image)") from None
    return pypdf


def parse_pages(spec: str) -> list[tuple[int, int | None]]:
    """`1-3,5,7-` as [(1, 3), (5, 5), (7, None)]: 1-based, inclusive, in the order given."""
    ranges = []
    for part in str(spec).split(","):
        part = part.strip()
        try:
            if "-" in part:
                lo, hi = (s.strip() for s in part.split("-", 1))
                if not lo and not hi:
                    raise ValueError(part)
                first, last = int(lo or 1), (int(hi) if hi else None)
            else:
                first = last = int(part)
        except ValueError:
            raise UsageError(f"{part!r} is not a page or a range (like 3, 2-5 or 7-)") from None
        if first < 1 or (last is not None and last < first):
            raise UsageError(f"{part!r} is not a valid page range")
        ranges.append((first, last))
    return ranges


def _expand(ranges, count: int, name: str) -> list[int]:
    """0-based page numbers for `ranges` in a document of `count` pages."""
    out = []
    for first, last in ranges:
        last = count if last is None else last
        if last > count:
            raise PdfError(f"{name}: has {count} pages; asked for {last}")
        out.extend(range(first - 1, last))
    return out


def _open(src: Path, max_input_bytes: int):
    pypdf = _pypdf()
    if src.stat().st_size > max_input_bytes:
        raise PdfError(f"{src.name}: input is over the {max_input_bytes}-byte cap")
    with open(src, "rb") as f:
        if f.read(1024).find(b"%PDF-") < 0:
            raise PdfError(f"{src.name}: not a PDF")
    try:
        reader = pypdf.PdfReader(str(src))
        if reader.is_encrypted:
            raise PdfError(f"{src.name}: encrypted; decrypt it first")
        len(reader.pages)  # parses the page tree
    except PdfError:
        raise
    except Exception as e:  # pypdf raises many types on damaged files
        raise PdfError(f"{src.name}: not readable as a PDF ({' '.join(str(e).split())[:300]})") from None
    return reader


def _clean(page) -> None:
    """Remove from a page of a source (in memory; the file is untouched) what could run, fetch or carry anything beyond its look."""
    from pypdf.generic import NameObject

    for key in ("/AA", "/Metadata", "/PieceInfo", "/B", "/Thumb"):
        if key in page:
            del page[key]
    annots = page.get("/Annots")
    if annots is None:
        return
    kept = []
    for ref in annots.get_object():
        annot = ref.get_object()
        if str(annot.get("/Subtype")) in _DROP_SUBTYPES or "/AA" in annot:
            continue
        action = annot.get("/A")
        if action is not None and str(action.get_object().get("/S")) not in _KEEP_ACTIONS:
            continue
        kept.append(ref)
    if kept:
        page[NameObject("/Annots")] = type(annots.get_object())(kept)
    else:
        del page["/Annots"]


def _save(writer, out) -> None:
    writer.add_metadata({"/Producer": PRODUCER})
    writer.generate_file_identifiers()
    with open(out, "wb") as f:
        writer.write(f)


def _split_work(src, every, folder, stem, max_pages, max_input_bytes, conn):
    try:
        pypdf = _pypdf()
        reader = _open(src, max_input_bytes)
        count = len(reader.pages)
        if count > max_pages:
            raise PdfError(f"the output would have over {max_pages} pages")
        width = max(3, len(str(-(-count // every))))
        names = []
        for i, first in enumerate(range(0, count, every), 1):
            writer = pypdf.PdfWriter()
            for n in range(first, min(first + every, count)):
                page = reader.pages[n]
                _clean(page)
                writer.add_page(page)
            name = f"{stem}-{i:0{width}d}.pdf"
            _save(writer, folder / name)
            names.append(name)
        conn.send(names)
    except PdfError as e:
        conn.send((type(e).__name__, str(e)))
    except BaseException as e:
        conn.send(("PdfError", f"{type(e).__name__}: {' '.join(str(e).split())[:300]}"))
    finally:
        conn.close()


def _work(plan, out, max_pages, max_input_bytes, conn):
    try:
        pypdf = _pypdf()
        writer = pypdf.PdfWriter()
        total = 0
        for src, ranges in plan:
            reader = _open(src, max_input_bytes)
            numbers = _expand(ranges, len(reader.pages), src.name) if ranges else range(len(reader.pages))
            total += len(numbers)
            if total > max_pages:
                raise PdfError(f"the output would have over {max_pages} pages")
            for n in numbers:
                page = reader.pages[n]
                _clean(page)  # before the copy: what is dropped must not reach the writer at all
                writer.add_page(page)
        _save(writer, out)
        conn.send(None)
    except PdfError as e:
        conn.send((type(e).__name__, str(e)))
    except BaseException as e:  # a parser bug must not escape as a traceback
        conn.send(("PdfError", f"{type(e).__name__}: {' '.join(str(e).split())[:300]}"))
    finally:
        conn.close()


def _process(plan, dest: Path, *, timeout, max_bytes, max_pages, max_input_bytes) -> Path:
    """Write the pages of `plan` ([(path, ranges or None)]) as `dest`, in a child process killed after
    `timeout`; the result is linked into place unless `dest` appeared."""
    _pypdf()
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="publishing-pdf-", dir=dest.parent))
    try:
        out = temporary / "out.pdf"
        ctx = multiprocessing.get_context("fork")
        recv, send = ctx.Pipe(duplex=False)
        proc = ctx.Process(target=_work, args=(plan, out, max_pages, max_input_bytes, send), daemon=True)
        proc.start()
        send.close()
        proc.join(timeout)
        if proc.is_alive():
            proc.kill()
            proc.join()
            raise PdfError(f"timed out after {timeout:g} s")
        result = recv.recv() if recv.poll() else ("PdfError", f"the parser stopped ({proc.exitcode})")
        if result is not None:
            raise PdfError(result[1])
        if not out.is_file() or out.stat().st_size == 0:
            raise PdfError("nothing was written")
        if out.stat().st_size > max_bytes:
            raise PdfError(f"output is {out.stat().st_size} bytes, over the {max_bytes}-byte cap")
        try:
            os.link(out, dest)  # fails if dest exists: never overwrite
        except FileExistsError:
            raise UsageError(f"{dest} exists; never overwrite") from None
        return dest
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _split_process(src: Path, every: int, folder: Path, *, timeout, max_bytes, max_pages, max_input_bytes) -> list[Path]:
    """Write `src` as parts of `every` pages into `folder` (a child process killed after `timeout`); parts are
    linked into place, all or none, and never over an existing file."""
    _pypdf()
    folder.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="publishing-pdf-", dir=folder.parent))
    linked: list[Path] = []
    try:
        ctx = multiprocessing.get_context("fork")
        recv, send = ctx.Pipe(duplex=False)
        proc = ctx.Process(target=_split_work, args=(src, every, temporary, src.stem, max_pages, max_input_bytes, send),
                           daemon=True)
        proc.start()
        send.close()
        proc.join(timeout)
        if proc.is_alive():
            proc.kill()
            proc.join()
            raise PdfError(f"timed out after {timeout:g} s")
        result = recv.recv() if recv.poll() else ("PdfError", f"the parser stopped ({proc.exitcode})")
        if not isinstance(result, list):
            raise PdfError(result[1])
        for name in result:
            size = (temporary / name).stat().st_size
            if size == 0:
                raise PdfError("nothing was written")
            if size > max_bytes:
                raise PdfError(f"{name} is {size} bytes, over the {max_bytes}-byte cap")
        clash = [n for n in result if (folder / n).exists() or (folder / n).is_symlink()]
        if clash:
            raise UsageError(f"{folder / clash[0]} exists; never overwrite")
        folder.mkdir(exist_ok=True)
        try:
            for name in result:
                os.link(temporary / name, folder / name)
                linked.append(folder / name)
        except FileExistsError:
            raise UsageError(f"{folder / name} exists; never overwrite") from None
        return linked
    except BaseException:
        for p in linked:
            p.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


_LIMITS = dict(timeout=TIMEOUT, max_bytes=MAX_BYTES, max_pages=MAX_PAGES, max_input_bytes=MAX_INPUT_BYTES)


def _source(src) -> Path:
    return local_source(src, SUFFIXES, "PDF", UsageError)


def _dest(out) -> Path:
    return local_dest(out, SUFFIXES, UsageError)


def merge(sources, dest, **limits) -> Path:
    """All pages of each of `sources`, in order, as one PDF."""
    sources = [_source(s) for s in sources]
    if len(sources) < 2:
        raise UsageError("merge needs at least two PDFs")
    if len(sources) > MAX_INPUTS:
        raise UsageError(f"merge takes at most {MAX_INPUTS} PDFs")
    return _process([(s, None) for s in sources], _dest(dest), **{**_LIMITS, **limits})


def pages(src, dest, *, select: str, **limits) -> Path:
    """The pages of `src` named by `select` (`1-3,5,7-`, 1-based, in that order; repeats allowed), as one PDF."""
    src, ranges = _source(src), parse_pages(select)
    return _process([(src, ranges)], _dest(dest), **{**_LIMITS, **limits})


def strip(src, dest, **limits) -> Path:
    """`src` with every page and nothing else of the source: no info, XMP, outline, form, attachment or script."""
    return _process([(_source(src), None)], _dest(dest), **{**_LIMITS, **limits})


def split(src, folder, *, every: int = 1, **limits) -> list[Path]:
    """`src` as consecutive parts of `every` pages each, `<stem>-001.pdf` and so on, in `folder`; returns the paths."""
    src = _source(src)
    if every < 1:
        raise UsageError("--every must be at least 1")
    folder = Path(folder)
    if folder.suffix.lower() == ".pdf":
        raise UsageError(f"{folder}: split writes into a folder, not a .pdf")
    if "://" in str(folder) or (folder.exists() and not folder.is_dir()):
        raise UsageError(f"{folder}: not a local folder")
    return _split_process(src, every, folder, **{**_LIMITS, **limits})


# --- the command ------------------------------------------------------------------------------

def _common(p, folder=False) -> None:
    p.add_argument("-o", "--output", required=True,
                   help="the output folder (parts are never overwritten)" if folder else "the PDF path (never overwritten)")
    p.add_argument("--timeout", type=positive(float), default=TIMEOUT, metavar="SECONDS",
                   help=f"stop after this long (default {TIMEOUT:g})")
    p.add_argument("--max-bytes", type=positive(int), default=MAX_BYTES, metavar="N",
                   help=f"refuse an output larger than this (default {MAX_BYTES})")
    p.add_argument("--max-pages", type=positive(int), default=MAX_PAGES, metavar="N",
                   help=f"refuse an output with more pages than this (default {MAX_PAGES})")
    p.add_argument("--max-input-bytes", type=positive(int), default=MAX_INPUT_BYTES, metavar="N",
                   help=f"refuse an input larger than this (default {MAX_INPUT_BYTES})")
    p.set_defaults(fn=run, needs_render=False)


def add_arguments(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="pdf_cmd", required=True, metavar="{merge,pages,strip,split}")
    m = sub.add_parser("merge", help="join PDFs, in the order given, into one")
    m.add_argument("sources", nargs="+", metavar="SRC")
    _common(m)
    s = sub.add_parser("pages", help="keep the pages named (1-3,5,7-), in that order")
    s.add_argument("src")
    s.add_argument("--select", required=True, metavar="RANGES", help="pages to keep, like 1-3,5,7-")
    _common(s)
    t = sub.add_parser("strip", help="every page, with no metadata, outline, form, attachment or script")
    t.add_argument("src")
    _common(t)
    u = sub.add_parser("split", help="one PDF as parts of N pages each (<stem>-001.pdf ...) in a folder")
    u.add_argument("src")
    u.add_argument("--every", type=positive(int), default=1, metavar="N", help="pages per part (default 1)")
    _common(u, folder=True)


def run(a) -> int:
    kw = dict(timeout=a.timeout, max_bytes=a.max_bytes, max_pages=a.max_pages, max_input_bytes=a.max_input_bytes)
    try:
        if a.pdf_cmd == "merge":
            dest = merge(a.sources, a.output, **kw)
        elif a.pdf_cmd == "split":
            for part in split(a.src, a.output, every=a.every, **kw):
                print(part)
            return 0
        elif a.pdf_cmd == "pages":
            dest = pages(a.src, a.output, select=a.select, **kw)
        else:
            dest = strip(a.src, a.output, **kw)
    except PdfError as e:
        print(f"publishing: {e}", file=sys.stderr)
        return e.exit_code
    print(dest)
    return 0
