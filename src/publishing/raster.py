"""PDF pages to PNG images, in a supervised child: the page images and the thumbnail of `render-html`,
`render-md` and `pdf-pages`.

The rasterizer is PDFium (pinned by pypdfium2 in the render profile), the engine Chromium shows PDFs
with. A PDF may be a person's upload, so PDFium never runs in the caller's process. Each call:

- runs in its own process tree under the user-content supervisor (`usercontent._supervise`): killed
  at the wall-clock limit or when its private memory passes the memory limit, with secrets scrubbed
  from its environment, and in a fresh network namespace where the host allows one;
- reads one file (the PDF, copied into the job's own temporary folder) and writes PNGs there only;
- refuses a PDF over `max_bytes`, with more than `max_pages` pages, or with a page whose image would
  pass `max_pixels` (a 1 pt x 14400 pt page is a valid PDF and a gigapixel PNG), before it draws;
- draws no form fields and runs no PDF script (PDFium's form environment is never started).

Names are fixed: `page-001.png`, `page-002.png`, ... (three digits, more when there are more than
999 pages) and `thumbnail.png`. The same PDF gives the same PNG bytes.
"""
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from .usercontent import Limits, UserContentError, _require_linux, _supervise, netns_available

MAX_WIDTH = 4000  # pixels: the widest page image or thumbnail
MAX_PIXELS = 40_000_000  # one image's width x height


@dataclass
class Images:
    pages: int  # pages in the PDF
    files: list  # the page images, in page order (empty when only a thumbnail was asked for)
    thumbnail: Path | None
    netns: bool


def page_name(i: int, total: int) -> str:
    """The file name of page `i` (from 1) of `total`: page-001.png, or wider past 999 pages."""
    return f"page-{i:0{max(3, len(str(total)))}d}.png"


def rasterize(pdf: Path, out_dir: Path, *, width: int | None = 1400, thumbnail: int | None = None,
              limits: Limits | None = None, max_pixels: int = MAX_PIXELS, name: str | None = None) -> Images:
    """Draw every page of `pdf` `width` pixels wide into `out_dir` (None: no page images), and the first
    page `thumbnail` pixels wide as thumbnail.png. `out_dir` is created and must hold none of the names.
    Raises UserContentError when the PDF is refused or the child is stopped; `name` labels its messages."""
    _require_linux()
    limits = limits or Limits()
    pdf = Path(pdf)
    name = name or pdf.name
    for w in (width, thumbnail):
        if w is not None and not 1 <= w <= MAX_WIDTH:
            raise ValueError(f"image width {w} is outside 1..{MAX_WIDTH}")
    size = pdf.stat().st_size
    if size > limits.max_bytes:
        raise UserContentError(f"{name} is {size} bytes, over the input limit of {limits.max_bytes}")
    netns = netns_available()
    if limits.require_netns and not netns:
        raise UserContentError("no network namespace here (unprivileged user namespaces are blocked) and "
                               "require_netns is set")
    with tempfile.TemporaryDirectory(prefix="publishing-raster-") as tmp:
        tmp = Path(tmp)
        shutil.copyfile(pdf, tmp / "in.pdf")  # the child reads its own copy, nothing else
        (tmp / "png").mkdir()
        job = {"pdf": str(tmp / "in.pdf"), "out": str(tmp / "png"), "result": str(tmp / "result.json"),
               "width": width, "thumbnail": thumbnail, "max_pages": limits.max_pages, "max_pixels": max_pixels}
        (tmp / "job.json").write_text(json.dumps(job))
        cmd = [sys.executable, "-m", "publishing.raster", str(tmp / "job.json")]
        if netns:
            cmd = ["unshare", "--user", "--net", "--map-current-user", "--", *cmd]
        with open(tmp / "stderr", "w+b") as err:
            code, why = _supervise(cmd, tmp, err, replace(limits, allow_js=False))
            err.seek(0)
            stderr = err.read().decode(errors="replace")
        reply = json.loads((tmp / "result.json").read_text()) if (tmp / "result.json").is_file() else {}
        if why:
            raise UserContentError(f"{name}: drawing the pages went {why}")
        if code != 0 or "error" in reply:
            tail = (reply.get("error") or stderr.strip() or f"exit status {code}")[-400:]
            raise UserContentError(f"{name}: {tail}")
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        names = list(reply["files"]) + (["thumbnail.png"] if thumbnail else [])
        clash = [n for n in names if (out_dir / n).exists()]
        if clash:
            raise FileExistsError(f"{out_dir / clash[0]} exists; never overwrite")
        written = []
        try:
            for n in names:
                with open(out_dir / n, "xb") as f:
                    written.append(out_dir / n)
                    f.write((tmp / "png" / n).read_bytes())
        except BaseException:
            for p in written:
                p.unlink(missing_ok=True)
            raise
        return Images(pages=reply["pages"], files=[out_dir / n for n in reply["files"]],
                      thumbnail=out_dir / "thumbnail.png" if thumbnail else None, netns=netns)


# ---------------------------------------------------------------- the child: PDFium on one file

def _child(job_path: str) -> int:
    job = json.loads(Path(job_path).read_text())
    reply = Path(job["result"])
    try:
        import pypdfium2 as pdfium

        out = Path(job["out"])
        try:
            doc = pdfium.PdfDocument(job["pdf"])
        except pdfium.PdfiumError as e:
            raise ValueError(f"not a readable PDF ({e})") from None
        try:
            n = len(doc)
            if n == 0:
                raise ValueError("the PDF has no pages")
            if n > job["max_pages"]:
                raise ValueError(f"{n} pages, over the page limit of {job['max_pages']}")
            wanted = [(i, job["width"], page_name(i + 1, n)) for i in range(n)] if job["width"] else []
            if job["thumbnail"]:
                wanted.append((0, job["thumbnail"], "thumbnail.png"))
            for i, width, name in wanted:  # every size first: refuse before drawing anything
                page = doc[i]
                w, h = page.get_size()
                page.close()
                if w <= 0 or h <= 0 or width * width * h / w > job["max_pixels"]:
                    raise ValueError(f"page {i + 1} is {w:g} x {h:g} pt: at {width} px wide its image passes "
                                     f"the pixel limit of {job['max_pixels']}")
            for i, width, name in wanted:
                page = doc[i]
                img = page.render(scale=width / page.get_width(), may_draw_forms=False).to_pil()
                img.save(out / name, format="PNG")  # Pillow writes no time stamp: same pages, same bytes
                page.close()
        finally:
            doc.close()
        files = [name for _, _, name in wanted if name != "thumbnail.png"]
    except Exception as e:  # the parent owns the message
        reply.write_text(json.dumps({"error": str(e) or type(e).__name__}))
        return 1
    reply.write_text(json.dumps({"pages": n, "files": files}))
    return 0


if __name__ == "__main__":
    sys.exit(_child(sys.argv[1]))
