"""Office to PDF: `publishing convert SRC [-o OUT]`, and `convert()` for callers in Python.

The converter is office2pdf (pure Rust, no LibreOffice), pinned at VERSION with a checksum for each
release build in PINS and installed by `publishing setup --convert`. This module uses the standard
library only: it is the whole of the convert profile (`publishing[convert]`), which installs and
runs without Playwright or Chromium.

Behaviour moved from spire-venue server/office-pdf.ts, unchanged on success:

- In: a file named .docx, .xlsx or .pptx, in any letter case; nothing else reaches the converter.
  Out: one PDF, by default beside the source with the suffix .pdf. An existing file is never
  overwritten.
- Which converter: OFFICE2PDF_BIN, when set, is authoritative even when it is wrong or empty and
  never falls back. Otherwise /usr/local/bin/office2pdf, then the pinned install in the cache, then
  a developer build (~/src/ext/office2pdf/target/release/office2pdf). Only an executable regular
  file is a converter.
- The call: `office2pdf SRC -o OUT` into a fresh temporary folder (under TMPDIR), moved into place
  when it succeeds; the folder is always removed.
- Failure: a non-zero exit is an error carrying at most 400 characters of the converter's stderr,
  or `office2pdf failed (<status>)` when it wrote none. A zero exit with no output is the same
  error: never a PDF.

Added by the move, changing nothing on success: a time limit (TIMEOUT), a cap on the output's size
(MAX_BYTES, enforced while the converter runs), and an output that does not start `%PDF-` is an
error. Exit codes of the command: 0 converted (stdout: the PDF's path), 1 the conversion failed,
2 usage (not an Office file, no such source, the output exists), 3 no converter, or setup failed.
"""
import argparse
import hashlib
import os
import platform
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

VERSION = "v0.6.7"  # developer0hye/office2pdf; tag commit 8f34766a1d1567b9d81d606e45ea690987a7c6ed
# target -> (sha256 of the release archive, sha256 of the office2pdf binary inside it). The archive
# hashes are the release's own asset digests; each was downloaded and checked against them.
PINS = {
    "x86_64-unknown-linux-musl": ("f6bffbe26aadfed49687144dfd7a999bc7d88ddb1eea0ab7e763e80720db292a",
                                  "2658c000d90a95640ebc49f64108f3736d9e09865ae620cbe71de3769c435e46"),
    "x86_64-unknown-linux-gnu": ("c4679a39d2a1e2b587786d561c83e95171b31e651df2bef68782ea2eb18031ca",
                                 "9b3567d14147c5e8792ffd846e5d4b1c1552068bd3895a73f53657cf267778b4"),
    "aarch64-unknown-linux-gnu": ("1a86b1e6d04ce7acb77b1c815d17400d8ab9ee69c8439a716cbd67343f345edc",
                                  "e5a6662272a4aa2c97a1c587e0ecc7be474412b05416034888d9366fad88598a"),
    "x86_64-apple-darwin": ("2a73c3a3d320e0e4917a707ec0323007785591babee6fc47e132d766b1d19ad8",
                            "d59a62e5ab0ad7e89debb5a7af0eebe879e8bcd1524cb2de44a9901bb13f081f"),
    "aarch64-apple-darwin": ("9d8a6acb9a528623082aff209223c41a57efc9d48a869b860b2e4a26f6207b19",
                             "ff9e1a060c06b7dcdaa95495aa478f74914195d570796870add00c890c7b4de0"),
}
RELEASES = "https://github.com/developer0hye/office2pdf/releases/download"
OFFICE = (".docx", ".xlsx", ".pptx")
SYSTEM_BIN = Path("/usr/local/bin/office2pdf")
DEV_BIN = Path.home() / "src/ext/office2pdf/target/release/office2pdf"
TIMEOUT = 120.0  # seconds
MAX_BYTES = 256 * 2**20
STDERR_CHARS = 400
_POLL = 0.05  # seconds between checks of a running converter's output size


class ConvertError(Exception):
    """The conversion failed (exit 1). Subclasses carry their own exit code."""
    exit_code = 1


class NotOffice(ConvertError):
    exit_code = 2


class SourceMissing(ConvertError):
    exit_code = 2


class OutputExists(ConvertError):
    exit_code = 2


class ConverterNotFound(ConvertError):
    exit_code = 3


class SetupError(ConvertError):
    exit_code = 3


# --- which converter --------------------------------------------------------------------------

def cache_root() -> Path:
    if os.environ.get("PUBLISHING_CACHE"):
        return Path(os.environ["PUBLISHING_CACHE"])
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "publishing"


def host_target() -> str | None:
    """The release build for this machine: an office2pdf target triple, or None."""
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(platform.machine().lower())
    if arch is None:
        return None
    if sys.platform == "darwin":
        return f"{arch}-apple-darwin"
    if sys.platform.startswith("linux"):
        return f"{arch}-unknown-linux-{'gnu' if platform.libc_ver()[0] == 'glibc' else 'musl'}"
    return None


def pinned_bin(target: str | None = None) -> Path:
    """Where `publishing setup --convert` puts the pinned build without --bin-dir."""
    return cache_root() / f"office2pdf-{VERSION}-{target or host_target() or 'unknown'}" / "office2pdf"


def _is_converter(p: str) -> bool:
    return bool(p) and os.path.isfile(p) and os.access(p, os.X_OK)


def office2pdf_bin() -> Path | None:
    """The converter `convert` runs, or None. OFFICE2PDF_BIN, when set, is the only candidate."""
    env = os.environ.get("OFFICE2PDF_BIN")
    candidates = [env] if env is not None else [str(SYSTEM_BIN), str(pinned_bin()), str(DEV_BIN)]
    return next((Path(p) for p in candidates if _is_converter(p)), None)


# --- the conversion ---------------------------------------------------------------------------

def is_office(path) -> bool:
    return Path(path).suffix.lower() in OFFICE


def convert(src, dest=None, *, timeout: float = TIMEOUT, max_bytes: int = MAX_BYTES) -> Path:
    """Convert the Office file `src` to the PDF `dest` (default: beside it, suffix .pdf).

    Returns `dest`. Raises a ConvertError subclass, and leaves no `dest`, on any failure."""
    src = Path(src)
    if not is_office(src):
        raise NotOffice(f"{src}: not an Office file (.docx, .xlsx or .pptx)")
    if not src.is_file():
        raise SourceMissing(f"{src}: no such file")
    dest = Path(dest) if dest is not None else src.with_suffix(".pdf")
    if dest.exists():
        raise OutputExists(f"{dest} exists; never overwrite")
    bin_ = office2pdf_bin()
    if bin_ is None:
        env = os.environ.get("OFFICE2PDF_BIN")
        why = (f"OFFICE2PDF_BIN={env!r} is not an executable file" if env is not None
               else "run `publishing setup --convert`, or set OFFICE2PDF_BIN")
        raise ConverterNotFound(f"office2pdf not found ({why})")
    temporary = Path(tempfile.mkdtemp(prefix="publishing-convert-"))
    try:
        output = temporary / "output.pdf"
        _run(bin_, src.resolve(), output, temporary / "stderr", timeout, max_bytes)
        size = output.stat().st_size
        if size > max_bytes:
            raise ConvertError(f"office2pdf output is {size} bytes, over the {max_bytes}-byte cap")
        with open(output, "rb") as f:
            if f.read(5) != b"%PDF-":
                raise ConvertError("office2pdf output is not a PDF")
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


def _run(bin_: Path, src: Path, output: Path, err_path: Path, timeout: float, max_bytes: int) -> None:
    with open(err_path, "wb") as err:
        proc = subprocess.Popen([str(bin_), str(src), "-o", str(output)], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=err, start_new_session=True)
        try:
            deadline = time.monotonic() + timeout
            while proc.poll() is None:
                if time.monotonic() >= deadline:
                    raise ConvertError(f"office2pdf timed out after {timeout:g} s")
                if output.exists() and output.stat().st_size > max_bytes:
                    raise ConvertError(f"office2pdf output is over the {max_bytes}-byte cap")
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
        raise ConvertError(text or f"office2pdf failed ({status if status >= 0 else f'signal {-status}'})")


# --- the pinned install -----------------------------------------------------------------------

def archive_stem(target: str) -> str:
    return f"office2pdf-{VERSION}-{target}"


def url(target: str) -> str:
    return f"{RELEASES}/{VERSION}/{archive_stem(target)}.tar.gz"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _fetch(address: str, out: Path) -> None:
    with urllib.request.urlopen(address, timeout=60) as r, open(out, "wb") as f:
        shutil.copyfileobj(r, f)


def install(bin_dir=None, target: str | None = None) -> Path:
    """Install the pinned office2pdf for `target` (default: this machine) as `<bin_dir>/office2pdf`
    (default: the cache path the lookup tries). Checks the archive's and the binary's checksums;
    an install that already matches downloads nothing. Returns the binary's path."""
    target = target or host_target()
    if target not in PINS:
        raise SetupError(f"no pinned office2pdf build for {target or platform.machine()} "
                         f"(pinned: {', '.join(sorted(PINS))})")
    archive_sha, binary_sha = PINS[target]
    dest = Path(bin_dir) / "office2pdf" if bin_dir else pinned_bin(target)
    if dest.is_file() and _sha256(dest) == binary_sha and os.access(dest, os.X_OK):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="publishing-setup-", dir=dest.parent) as tmp:
        archive = Path(tmp) / "office2pdf.tar.gz"
        try:
            _fetch(url(target), archive)
        except OSError as e:
            raise SetupError(f"could not download {url(target)}: {e}") from None
        if _sha256(archive) != archive_sha:
            raise SetupError(f"{url(target)} does not match its pinned checksum; nothing installed")
        member = f"{archive_stem(target)}/office2pdf"
        with tarfile.open(archive) as t:
            try:
                info = t.getmember(member)
            except KeyError:
                raise SetupError(f"{url(target)} has no {member}") from None
            if not info.isfile():
                raise SetupError(f"{url(target)}: {member} is not a file")
            staged = Path(tmp) / "office2pdf"
            with t.extractfile(info) as f, open(staged, "wb") as out:
                shutil.copyfileobj(f, out)
        if _sha256(staged) != binary_sha:
            raise SetupError(f"{member} does not match its pinned checksum; nothing installed")
        staged.chmod(0o755)
        os.replace(staged, dest)
    return dest


def setup(bin_dir=None, target: str | None = None) -> int:
    try:
        dest = install(bin_dir, target)
    except SetupError as e:
        print(f"publishing: {e}", file=sys.stderr)
        return e.exit_code
    print(f"office2pdf {VERSION} ({target or host_target()}): {dest}")
    if office2pdf_bin() != dest:
        print(f"publishing: note: convert finds {office2pdf_bin() or 'no converter'} first; "
              f"set OFFICE2PDF_BIN={dest} to use this one", file=sys.stderr)
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
    p.add_argument("src", help="the Office file: .docx, .xlsx or .pptx")
    p.add_argument("-o", "--output", help="the PDF path (default: beside SRC, suffix .pdf; never overwritten)")
    p.add_argument("--timeout", type=_positive(float), default=TIMEOUT, metavar="SECONDS",
                   help=f"stop the converter after this long (default {TIMEOUT:g})")
    p.add_argument("--max-bytes", type=_positive(int), default=MAX_BYTES, metavar="N",
                   help=f"refuse an output larger than this (default {MAX_BYTES})")
    p.set_defaults(fn=run, needs_render=False)


def run(a) -> int:
    try:
        dest = convert(a.src, a.output, timeout=a.timeout, max_bytes=a.max_bytes)
    except ConvertError as e:
        print(f"publishing: {e}", file=sys.stderr)
        return e.exit_code
    print(dest)
    return 0
