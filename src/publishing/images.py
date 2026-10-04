"""Images through Pillow: `publishing images resize|convert|thumbnail|strip`, and the functions below for
callers in Python.

Pillow only (exact pin in the `images` extra); no Playwright, no Chromium, no ffmpeg, no network.

- In: one local file, by path, with an image suffix (INPUT_SUFFIXES). A URL, a device or a pipe is refused.
  The decoder is chosen from the file's content among FORMATS only (no EPS, no Ghostscript, no plugin
  formats), and a suffix that disagrees with the content is refused. An animated image contributes its
  first frame.
- Out: one file whose format is its suffix (.png .jpg .jpeg .webp), built in a temporary folder beside it
  and linked into place: an existing OUT is never overwritten (exit 2) and a failure or a limit leaves no
  OUT. The path is the only line on stdout.
- Metadata: nothing is copied from the source (EXIF, GPS, XMP, ICC, text chunks, comments). The EXIF
  orientation is applied to the pixels first, so stripping does not turn a photo on its side.
- Deterministic: the same Pillow build turns the same input into the same bytes.
- Limits: TIMEOUT seconds of wall clock (the work runs in a child process that is killed), MAX_INPUT_BYTES of
  input, MAX_PIXELS of decoded input (read from the header before decoding), MAX_BYTES of output.

Exit codes of the command: 0 done, 1 the image could not be read or a limit was hit, 2 usage (unsupported
type, no such source, the output exists), 3 Pillow is not installed.
"""
import argparse
import multiprocessing
import os
import shutil
import sys
import tempfile
from pathlib import Path

from ._shared import local_dest, local_source, positive

OUTPUT_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
INPUT_SUFFIXES = OUTPUT_SUFFIXES + (".gif", ".bmp", ".tif", ".tiff")
FORMATS = ["PNG", "JPEG", "WEBP", "GIF", "BMP", "TIFF"]  # decoders Pillow may use, by content
_SUFFIX_FORMAT = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP", ".gif": "GIF",
                  ".bmp": "BMP", ".tif": "TIFF", ".tiff": "TIFF"}
TIMEOUT = 60.0
MAX_INPUT_BYTES = 64 * 2**20
MAX_PIXELS = 50_000_000
MAX_BYTES = 64 * 2**20  # output
MAX_SIDE = 16384  # a requested width, height or thumbnail size
QUALITY = 90


class ImageError(Exception):
    """The image could not be read or written, or a limit was hit (exit 1). Subclasses carry their own code."""
    exit_code = 1


class UsageError(ImageError):
    exit_code = 2


class ToolNotFound(ImageError):
    exit_code = 3


def _pil():
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise ToolNotFound("Pillow is not installed (the `images` extra, or the images image)") from None
    return Image, ImageOps


def _source(src) -> Path:
    return local_source(src, INPUT_SUFFIXES, "image", UsageError)


def _dest(out) -> Path:
    return local_dest(out, OUTPUT_SUFFIXES, UsageError)


def _side(name, value):
    if value is not None and not 1 <= value <= MAX_SIDE:
        raise UsageError(f"{name} must be 1 to {MAX_SIDE}, got {value}")
    return value


def _open(src: Path, max_pixels: int, max_input_bytes: int):
    """The decoded, upright, metadata-free image of `src`, or an ImageError."""
    Image, ImageOps = _pil()
    if src.stat().st_size > max_input_bytes:
        raise ImageError(f"{src.name}: input is over the {max_input_bytes}-byte cap")
    Image.MAX_IMAGE_PIXELS = None  # Pillow's own bomb check is replaced by max_pixels, read from the header below
    try:
        img = Image.open(src, formats=FORMATS)
        if _SUFFIX_FORMAT[src.suffix.lower()] != img.format:
            raise ImageError(f"{src.name}: content is {img.format}, not what the suffix says")
        if img.width * img.height > max_pixels:
            raise ImageError(f"{src.name}: {img.width}x{img.height} is over the {max_pixels}-pixel cap")
        img.seek(0)
        img.load()
        img = ImageOps.exif_transpose(img)  # applies the orientation
        if img.mode == "P" and "transparency" in img.info:
            img = img.convert("RGBA")  # keep the transparency before the metadata goes
        else:
            img = img.copy()
        img.info = {}  # EXIF, GPS, XMP, ICC, text chunks, comments: none reaches the output
    except ImageError:
        raise
    except (OSError, ValueError, SyntaxError, EOFError, Image.DecompressionBombError) as e:
        raise ImageError(f"{src.name}: not readable as an image ({' '.join(str(e).split())[:300]})") from None
    return img


def _fit(img, width, height):
    """Scale to fit within width x height (either may be None), keeping the aspect ratio; never to zero."""
    Image, _ = _pil()
    w, h = img.size
    scale = min((width or 10**9) / w, (height or 10**9) / h)
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    return img.resize(size, Image.Resampling.LANCZOS) if size != img.size else img


def _save(img, out: Path) -> None:
    fmt = _SUFFIX_FORMAT[out.suffix.lower()]
    if fmt == "JPEG":
        if img.mode in ("RGBA", "LA", "P"):  # flatten transparency onto white
            Image, _ = _pil()
            rgba = img.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.getchannel("A"))
            img = flat
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.save(out, "JPEG", quality=QUALITY, optimize=False, progressive=False)
    elif fmt == "WEBP":
        img.convert("RGBA" if "A" in img.getbands() else "RGB").save(out, "WEBP", quality=QUALITY, method=4)
    else:
        if img.mode not in ("1", "L", "LA", "RGB", "RGBA", "P"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        img.save(out, "PNG", optimize=False)


def _work(op, src, out, max_pixels, max_input_bytes, conn):
    try:
        img = _open(src, max_pixels, max_input_bytes)
        if op is not None:
            img = _fit(img, *op)
        _save(img, out)
        conn.send(None)
    except ImageError as e:
        conn.send((type(e).__name__, str(e)))
    except BaseException as e:  # a decoder bug must not escape as a traceback
        conn.send(("ImageError", f"{src.name}: {type(e).__name__}: {' '.join(str(e).split())[:300]}"))
    finally:
        conn.close()


def _process(box, src, dest, *, timeout, max_bytes, max_pixels, max_input_bytes) -> Path:
    """Decode `src`, fit it to `box` (width, height; None: keep the size), write `dest`. The work runs in a
    child process killed after `timeout`; the result is linked into place unless `dest` appeared."""
    _pil()
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="publishing-images-", dir=dest.parent))
    try:
        out = temporary / ("out" + dest.suffix.lower())
        ctx = multiprocessing.get_context("fork")
        recv, send = ctx.Pipe(duplex=False)
        proc = ctx.Process(target=_work, args=(box, src, out, max_pixels, max_input_bytes, send), daemon=True)
        proc.start()
        send.close()
        proc.join(timeout)
        if proc.is_alive():
            proc.kill()
            proc.join()
            raise ImageError(f"timed out after {timeout:g} s")
        result = recv.recv() if recv.poll() else ("ImageError", f"{src.name}: the decoder stopped ({proc.exitcode})")
        if result is not None:
            raise (ImageError(result[1]))
        if not out.is_file() or out.stat().st_size == 0:
            raise ImageError("nothing was written")
        if out.stat().st_size > max_bytes:
            raise ImageError(f"output is {out.stat().st_size} bytes, over the {max_bytes}-byte cap")
        try:
            os.link(out, dest)  # fails if dest exists: never overwrite
        except FileExistsError:
            raise UsageError(f"{dest} exists; never overwrite") from None
        return dest
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


_LIMITS = dict(timeout=TIMEOUT, max_bytes=MAX_BYTES, max_pixels=MAX_PIXELS, max_input_bytes=MAX_INPUT_BYTES)


def resize(src, dest, *, width: int | None = None, height: int | None = None, **limits) -> Path:
    """`src` scaled to fit within `width` x `height` (either alone fixes that side), aspect ratio kept."""
    if width is None and height is None:
        raise UsageError("resize needs --width, --height or both")
    src, dest = _source(src), _dest(dest)
    return _process((_side("width", width), _side("height", height)), src, dest, **{**_LIMITS, **limits})


def convert(src, dest, **limits) -> Path:
    """`src` re-encoded as the format `dest`'s suffix names, at its own size."""
    src, dest = _source(src), _dest(dest)
    return _process(None, src, dest, **{**_LIMITS, **limits})


def thumbnail(src, dest, *, size: int = 256, **limits) -> Path:
    """`src` scaled to fit within `size` x `size`, aspect ratio kept."""
    src, dest = _source(src), _dest(dest)
    return _process((_side("size", size),) * 2, src, dest, **{**_LIMITS, **limits})


def strip(src, dest, **limits) -> Path:
    """`src` re-encoded with no metadata, at its own size (the same as `convert`: every output is stripped;
    this is the name for doing only that, keeping the format)."""
    src, dest = _source(src), _dest(dest)
    return _process(None, src, dest, **{**_LIMITS, **limits})


# --- the command ------------------------------------------------------------------------------

def _common(p) -> None:
    p.add_argument("src")
    p.add_argument("-o", "--output", required=True, help="the image path; its suffix picks the format")
    p.add_argument("--timeout", type=positive(float), default=TIMEOUT, metavar="SECONDS",
                   help=f"stop after this long (default {TIMEOUT:g})")
    p.add_argument("--max-bytes", type=positive(int), default=MAX_BYTES, metavar="N",
                   help=f"refuse an output larger than this (default {MAX_BYTES})")
    p.add_argument("--max-pixels", type=positive(int), default=MAX_PIXELS, metavar="N",
                   help=f"refuse an input with more pixels than this (default {MAX_PIXELS})")
    p.add_argument("--max-input-bytes", type=positive(int), default=MAX_INPUT_BYTES, metavar="N",
                   help=f"refuse an input larger than this (default {MAX_INPUT_BYTES})")
    p.set_defaults(fn=run, needs_render=False)


def add_arguments(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="images_cmd", required=True, metavar="{resize,convert,thumbnail,strip}")
    r = sub.add_parser("resize", help="scale to fit a width and/or height, keeping the aspect ratio")
    _common(r)
    r.add_argument("--width", type=positive(int), help="fit within this width")
    r.add_argument("--height", type=positive(int), help="fit within this height")
    c = sub.add_parser("convert", help="re-encode as " + " ".join(OUTPUT_SUFFIXES))
    _common(c)
    t = sub.add_parser("thumbnail", help="scale to fit a square, keeping the aspect ratio")
    _common(t)
    t.add_argument("--size", type=positive(int), default=256, metavar="PIXELS", help="the square's side (default 256)")
    s = sub.add_parser("strip", help="re-encode with no EXIF, GPS or other metadata (orientation applied)")
    _common(s)


def run(a) -> int:
    kw = dict(timeout=a.timeout, max_bytes=a.max_bytes, max_pixels=a.max_pixels, max_input_bytes=a.max_input_bytes)
    try:
        if a.images_cmd == "resize":
            dest = resize(a.src, a.output, width=a.width, height=a.height, **kw)
        elif a.images_cmd == "convert":
            dest = convert(a.src, a.output, **kw)
        elif a.images_cmd == "thumbnail":
            dest = thumbnail(a.src, a.output, size=a.size, **kw)
        else:
            dest = strip(a.src, a.output, **kw)
    except ImageError as e:
        print(f"publishing: {e}", file=sys.stderr)
        return e.exit_code
    print(dest)
    return 0
