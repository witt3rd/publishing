"""Any document to markdown: `publishing extract SRC [-o OUT]`, and `extract()` for callers in Python.

The extractor is markitdown, pinned exactly in the `extract` extra (pyproject.toml, uv.lock). This
module imports the standard library only; markitdown runs in a child interpreter, so the time limit
and the output cap are enforced on a process that can be killed, and a crash in a parser costs the
call, not the caller.

Behaviour moved from spire-venue server/graph-drive.ts (`pip install markitdown` and a shell-out,
60 s and a 32 MiB buffer), unchanged on success: the same converter, the same markdown. Added: an
exact pin, no overwrite, an empty result is an error, bounded stderr, and no network.

- In: a local file named .pdf .docx .pptx .xlsx .html .htm .csv .json .xml .epub or .txt, in any
  letter case. Nothing else is tried (exit 2). Images and audio are not extracted: markitdown reads
  them through exiftool, a speech service or an LLM, none of which this profile has or may call.
- Out: one markdown file, by default beside the source with the suffix .md; its path is the only
  line on stdout. An existing file is never overwritten.
- No network: markitdown is called through `convert_local` with no plugins, no LLM client and no
  exiftool; the child also replaces every socket connect and name lookup with an error before
  markitdown is imported. A remote reference in a document is text, never a request.
- Limits: TIMEOUT seconds of wall clock, and MAX_BYTES of output enforced while the child runs.
  Neither changes an extraction that stays inside them.
- Failure: a child that fails carries at most 400 characters of its stderr (`Type: message`);
  an empty or whitespace-only result is an error.

- PDF: read with pdfminer.six (markitdown's own PDF dependency, so the same pin) directly, not
  through markitdown's PDF converter: that converter switches a page it takes for a form to
  pdfplumber text, which has no form feed between pages and no blank line between paragraphs.
  pdfminer's output keeps both: one `\\f` ends each page, a blank line separates paragraphs. Two
  repairs are applied on top, the ones markitdown's path made: typographic ligatures (`ﬁ`) become
  letters, and letter-spaced kickers (`D E S I G N`) are closed up.
- Not supported: `.msg` and `.rtf` (markitdown has no RTF reader, and Outlook needs an extra
  dependency); they are refused with exit 2 like any other unlisted type.

Exit codes of the command: 0 extracted, 1 failed, 2 usage (unsupported type, no such source, the
output exists), 3 markitdown is not installed (`pip install 'publishing[extract]'`), 4 the document
has no text (a scanned PDF; the file was read fine).
"""
import argparse
import importlib.util
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

MARKITDOWN = "0.1.8"  # the exact pin in pyproject.toml's `extract` extra
SUFFIXES = (".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".csv", ".json", ".xml", ".epub", ".txt")
TIMEOUT = 60.0  # seconds; the venue's
MAX_BYTES = 32 * 2**20  # the venue's buffer
STDERR_CHARS = 400
_POLL = 0.05


class ExtractError(Exception):
    """The extraction failed (exit 1). Subclasses carry their own exit code."""
    exit_code = 1


class Unsupported(ExtractError):
    exit_code = 2


class SourceMissing(ExtractError):
    exit_code = 2


class OutputExists(ExtractError):
    exit_code = 2


class ExtractorNotFound(ExtractError):
    exit_code = 3


class NoText(ExtractError):
    exit_code = 4


def is_supported(path) -> bool:
    return Path(path).suffix.lower() in SUFFIXES


def available() -> bool:
    return importlib.util.find_spec("markitdown") is not None


def extract(src, dest=None, *, timeout: float = TIMEOUT, max_bytes: int = MAX_BYTES) -> Path:
    """Extract the document `src` to the markdown file `dest` (default: beside it, suffix .md).

    Returns `dest`. Raises an ExtractError subclass, and leaves no `dest`, on any failure."""
    src = Path(src)
    if not is_supported(src):
        raise Unsupported(f"{src}: not a supported document ({', '.join(SUFFIXES)})")
    if not src.is_file():
        raise SourceMissing(f"{src}: no such file")
    dest = Path(dest) if dest is not None else src.with_suffix(".md")
    if dest.exists():
        raise OutputExists(f"{dest} exists; never overwrite")
    if not available():
        raise ExtractorNotFound("markitdown not found (install `publishing[extract]`)")
    temporary = Path(tempfile.mkdtemp(prefix="publishing-extract-"))
    try:
        output = temporary / "output.md"
        _run(src.resolve(), output, temporary / "stderr", timeout, max_bytes)
        size = output.stat().st_size
        if size > max_bytes:
            raise ExtractError(f"markitdown output is {size} bytes, over the {max_bytes}-byte cap")
        with open(output, "rb") as f:
            if not f.read(max_bytes + 1).strip():
                raise NoText(f"markitdown found no text in {src.name}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(output, "rb") as f, open(dest, "xb") as out:
                shutil.copyfileobj(f, out)
        except FileExistsError:
            raise OutputExists(f"{dest} exists; never overwrite") from None
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
        return dest
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _run(src: Path, output: Path, err_path: Path, timeout: float, max_bytes: int) -> None:
    with open(err_path, "wb") as err:
        proc = subprocess.Popen([sys.executable, "-m", "publishing.extract", "--worker", str(src), str(output)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err,
                                start_new_session=True)
        try:
            deadline = time.monotonic() + timeout
            while proc.poll() is None:
                if time.monotonic() >= deadline:
                    raise ExtractError(f"markitdown timed out after {timeout:g} s")
                if output.exists() and output.stat().st_size > max_bytes:
                    raise ExtractError(f"markitdown output is over the {max_bytes}-byte cap")
                try:
                    proc.wait(timeout=_POLL)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
    status = proc.returncode
    if status != 0 or not output.is_file():
        with open(err_path, "rb") as f:
            text = f.read(16 * STDERR_CHARS).decode("utf-8", "replace")[:STDERR_CHARS].rstrip()
        raise ExtractError(text or f"markitdown failed ({status if status >= 0 else f'signal {-status}'})")


# --- the child --------------------------------------------------------------------------------

def _block_network() -> None:
    """Every way out of the process raises, before markitdown (or anything it imports) can use one."""
    import socket

    def refuse(*args, **kwargs):
        raise OSError("network access is disabled in publishing extract")

    for name in ("connect", "connect_ex", "sendto", "sendmsg"):
        setattr(socket.socket, name, refuse)
    for name in ("create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex"):
        setattr(socket, name, refuse)


_LIGATURES = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl",
              "\ufb05": "st", "\ufb06": "st"}
_KICKER_TOKEN = re.compile(r"[A-Z0-9·&/-]{1,2}")


def _close_kicker(line: str) -> str:
    """`D E S I G N   N O T E` -> `DESIGN NOTE`: a line of at least five one or two character upper-case
    tokens, at least four of one character; words are the 2+ space gaps. Any other line is unchanged."""
    tokens = line.split()
    if len(tokens) < 5 or sum(len(t) == 1 for t in tokens) < 4 or not all(_KICKER_TOKEN.fullmatch(t) for t in tokens):
        return line
    return " ".join(w.replace(" ", "") for w in re.split(r" {2,}", line.strip()))


def pdf_text(src: str) -> str:
    """The text of a PDF, pdfminer's layout kept (form feed per page, blank line per paragraph)."""
    from pdfminer.high_level import extract_text
    text = extract_text(src)
    for ligature, letters in _LIGATURES.items():
        text = text.replace(ligature, letters)
    return "\n".join(_close_kicker(line) if "\f" not in line else
                     "\f" * line.count("\f") + _close_kicker(line.replace("\f", ""))
                     for line in text.split("\n"))


def _worker(src: str, out: str) -> int:
    _block_network()
    try:
        from markitdown import MarkItDown
    except ModuleNotFoundError:
        print("markitdown not found (install `publishing[extract]`)", file=sys.stderr)
        return 3
    try:
        # No plugins, no LLM client, no exiftool (None is "look it up", so point it nowhere real).
        if src.lower().endswith(".pdf"):
            text = pdf_text(src)
        else:
            text = MarkItDown(enable_plugins=False, exiftool_path="").convert_local(src).markdown
    except BaseException as e:  # any parser failure is the call's failure, with one bounded message
        print(f"{type(e).__name__}: {' '.join(str(e).split())}", file=sys.stderr)
        return 1
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    return 0


# --- the command ------------------------------------------------------------------------------

def _positive(kind):
    def parse(text):
        try:
            value = kind(text)
        except ValueError:
            value = 0
        if value <= 0:
            raise argparse.ArgumentTypeError(f"{text!r} is not a positive number")
        return value
    return parse


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("src", help="the document: " + " ".join(SUFFIXES))
    p.add_argument("-o", "--output", help="the markdown path (default: beside SRC, suffix .md; never overwritten)")
    p.add_argument("--timeout", type=_positive(float), default=TIMEOUT, metavar="SECONDS",
                   help=f"stop the extractor after this long (default {TIMEOUT:g})")
    p.add_argument("--max-bytes", type=_positive(int), default=MAX_BYTES, metavar="N",
                   help=f"refuse an output larger than this (default {MAX_BYTES})")
    p.set_defaults(fn=run, needs_render=False)


def run(a) -> int:
    try:
        dest = extract(a.src, a.output, timeout=a.timeout, max_bytes=a.max_bytes)
    except ExtractError as e:
        print(f"publishing: {e}", file=sys.stderr)
        return e.exit_code
    print(dest)
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        sys.exit(_worker(sys.argv[2], sys.argv[3]))
    sys.exit("publishing.extract is a library; run `publishing extract`")
