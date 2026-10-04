"""Any document to any document through pinned pandoc: the `pandoc` engine of `publishing convert`.

    publishing convert notes.md -o notes.pdf        # markdown, html, docx or odt in; pdf, docx or html out

Pandoc is pinned at VERSION with a checksum for the archive and for the binary in each linux build
(PINS), installed by `publishing setup --pandoc`. PDFs go through pdfLaTeX (a slim TeX Live, in the
`pandoc` image, Dockerfile.pandoc). This module uses the standard library only: it is the whole of the
pandoc profile (`publishing[pandoc]`), which installs and runs without Playwright or Chromium.

Hardened for a person's content: pandoc runs with `--sandbox` (readers and writers touch only the one
source file: no includes, no images fetched or read, no network), the markdown reader has raw TeX and
raw attributes off, pdfLaTeX has shell escape off and TeX's own file access in paranoid mode (no
reading or writing outside the working folders). The same limits as the Office engine apply: a time
limit and an output cap, a fresh temporary folder that is always removed, an existing output never
overwritten.

Deterministic: SOURCE_DATE_EPOCH (the caller's, else 0) with FORCE_SOURCE_DATE=1 fixes every date and
the PDF's trailer id, so the same source and the same image make the same bytes.
"""
import os
import platform
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

from .convert import (MAX_BYTES, TIMEOUT, ConvertError, ConverterNotFound, OutputExists,
                      SetupError, SourceMissing, _fetch, _run, _sha256, cache_root)

VERSION = "3.12"  # jgm/pandoc
# arch -> (sha256 of the release archive, sha256 of the pandoc binary inside it): the release's own
# asset digests, each downloaded and checked. Linux only; the image is glibc (Debian).
PINS = {
    "amd64": ("67d7d011fed8c8543306022b985b9b2499ab9b74818df91d8727c7e9ebc5ba06",
              "b7d0c52555858b13be79e0cb51a5078547166e22b9654d1a036e4f939665c699"),
    "arm64": ("6cefcf7100e23a99447c26f89d1ff5b253f3407fcef99a9e27ae06f3ed16cb82",
              "5fe3981857a0c8a797dcaba7ecf4733926f134226e3bf060275ca3fd79c264aa"),
}
RELEASES = "https://github.com/jgm/pandoc/releases/download"
# Source suffix -> pandoc reader. Raw TeX in markdown would let a person's text `\input` files.
READERS = {".md": "markdown-raw_tex-raw_attribute", ".markdown": "markdown-raw_tex-raw_attribute",
           ".html": "html", ".htm": "html", ".docx": "docx", ".odt": "odt"}
# Output format -> suffixes that name it.
OUTPUTS = {"pdf": (".pdf",), "docx": (".docx",), "html": (".html", ".htm")}
SYSTEM_BIN = Path("/usr/local/bin/pandoc")
PDF_ENGINE = "pdflatex"
STDERR_CHARS = 400


class UnsupportedConversion(ConvertError):
    exit_code = 2


# --- which pandoc -----------------------------------------------------------------------------

def host_arch() -> str | None:
    if not sys.platform.startswith("linux"):
        return None
    return {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower())


def pinned_bin(arch: str | None = None) -> Path:
    """Where `publishing setup --pandoc` puts the pinned build without --bin-dir."""
    return cache_root() / f"pandoc-{VERSION}-{arch or host_arch() or 'unknown'}" / "pandoc"


def _is_binary(p: str) -> bool:
    return bool(p) and os.path.isfile(p) and os.access(p, os.X_OK)


def pandoc_bin() -> Path | None:
    """The pandoc `convert` runs, or None. PANDOC_BIN, when set, is the only candidate."""
    env = os.environ.get("PANDOC_BIN")
    candidates = [env] if env is not None else [str(SYSTEM_BIN), str(pinned_bin())]
    return next((Path(p) for p in candidates if _is_binary(p)), None)


# --- the conversion ---------------------------------------------------------------------------

def reader(src) -> str | None:
    return READERS.get(Path(src).suffix.lower())


def output_format(dest, to: str | None = None) -> str:
    """The format `to` names, else the one `dest`'s suffix names, else pdf."""
    if to is not None:
        if to not in OUTPUTS:
            raise UnsupportedConversion(f"cannot write {to!r} (pdf, docx or html)")
        if dest is not None and Path(dest).suffix and Path(dest).suffix.lower() not in OUTPUTS[to]:
            raise UnsupportedConversion(f"{dest}: not a .{to} path")
        return to
    if dest is None or not Path(dest).suffix:
        return "pdf"
    suffix = Path(dest).suffix.lower()
    for name, suffixes in OUTPUTS.items():
        if suffix in suffixes:
            return name
    raise UnsupportedConversion(f"{dest}: cannot write {suffix} (pdf, docx or html)")


def _environment(tmp: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "TMPDIR", "LANG", "LC_ALL", "TEXMFHOME")}
    env.update(HOME=str(tmp), SOURCE_DATE_EPOCH=os.environ.get("SOURCE_DATE_EPOCH", "0"), FORCE_SOURCE_DATE="1",
               openin_any="p", openout_any="p", shell_escape="f", TEXMFVAR=str(tmp / "texmf-var"),
               TEXMFCONFIG=str(tmp / "texmf-config"))
    return env


def command(bin_: Path, src: Path, output: Path, to: str, title: str = "") -> list:
    """The pandoc command line, from the source's reader to the output's writer."""
    cmd = [str(bin_), "--sandbox", "-f", READERS[src.suffix.lower()], "-o", str(output)]
    if to == "pdf":
        cmd += ["-t", "pdf", f"--pdf-engine={PDF_ENGINE}", "--pdf-engine-opt=-no-shell-escape",
                "--pdf-engine-opt=-halt-on-error", "-V", "geometry:margin=1in"]
    elif to == "html":
        cmd += ["-t", "html5", "-s", "--metadata", f"pagetitle={title or src.stem}"]
    else:
        cmd += ["-t", "docx"]
    return cmd + [str(src)]


MAGIC = {"pdf": b"%PDF-", "docx": b"PK\x03\x04", "html": b""}


def convert(src, dest=None, *, to: str | None = None, timeout: float = TIMEOUT, max_bytes: int = MAX_BYTES) -> Path:
    """Convert `src` (markdown, html, docx or odt) to `dest` (pdf, docx or html; default: beside `src`
    with the suffix of `to`, else .pdf). Returns `dest`. Raises a ConvertError subclass, and leaves
    no `dest`, on any failure."""
    src = Path(src)
    if reader(src) is None:
        raise UnsupportedConversion(f"{src}: not a document pandoc reads ({', '.join(sorted(READERS))})")
    if not src.is_file():
        raise SourceMissing(f"{src}: no such file")
    fmt = output_format(dest, to)
    dest = Path(dest) if dest is not None else src.with_suffix(OUTPUTS[fmt][0])
    if dest.exists():
        raise OutputExists(f"{dest} exists; never overwrite")
    bin_ = pandoc_bin()
    if bin_ is None:
        env = os.environ.get("PANDOC_BIN")
        why = (f"PANDOC_BIN={env!r} is not an executable file" if env is not None
               else "run `publishing setup --pandoc`, or set PANDOC_BIN")
        raise ConverterNotFound(f"pandoc not found ({why})")
    if fmt == "pdf" and shutil.which(PDF_ENGINE) is None:
        raise ConverterNotFound(f"{PDF_ENGINE} not found: a PDF needs a TeX install (the pandoc image has one)")
    temporary = Path(tempfile.mkdtemp(prefix="publishing-pandoc-"))
    try:
        output = temporary / f"output.{fmt}"
        staged = temporary / f"source{src.suffix.lower()}"  # pandoc reads this copy only, and its name sets no title
        shutil.copyfile(src, staged)
        cmd = command(bin_, staged, output, fmt, src.stem)
        _run(cmd, "pandoc", output, temporary / "stderr", timeout, max_bytes, _environment(temporary), cwd=temporary)
        size = output.stat().st_size
        if size > max_bytes:
            raise ConvertError(f"pandoc output is {size} bytes, over the {max_bytes}-byte cap")
        with open(output, "rb") as f:
            head = f.read(len(MAGIC[fmt]))
        if head != MAGIC[fmt] or size == 0:
            raise ConvertError(f"pandoc output is not a {fmt.upper()}")
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


# --- the pinned install -----------------------------------------------------------------------

def archive_name(arch: str) -> str:
    return f"pandoc-{VERSION}-linux-{arch}.tar.gz"


def url(arch: str) -> str:
    return f"{RELEASES}/{VERSION}/{archive_name(arch)}"


def install(bin_dir=None, arch: str | None = None) -> Path:
    """Install the pinned pandoc for `arch` (default: this machine) as `<bin_dir>/pandoc` (default: the
    cache path the lookup tries). Checks the archive's and the binary's checksums; an install that
    already matches downloads nothing. Returns the binary's path."""
    arch = arch or host_arch()
    if arch not in PINS:
        raise SetupError(f"no pinned pandoc build for {arch or platform.machine()} (pinned: linux {', '.join(sorted(PINS))})")
    archive_sha, binary_sha = PINS[arch]
    dest = Path(bin_dir) / "pandoc" if bin_dir else pinned_bin(arch)
    if dest.is_file() and _sha256(dest) == binary_sha and os.access(dest, os.X_OK):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="publishing-setup-", dir=dest.parent) as tmp:
        archive = Path(tmp) / "pandoc.tar.gz"
        try:
            _fetch(url(arch), archive)
        except OSError as e:
            raise SetupError(f"could not download {url(arch)}: {e}") from None
        if _sha256(archive) != archive_sha:
            raise SetupError(f"{url(arch)} does not match its pinned checksum; nothing installed")
        member = f"pandoc-{VERSION}/bin/pandoc"
        with tarfile.open(archive) as t:
            try:
                info = t.getmember(member)
            except KeyError:
                raise SetupError(f"{url(arch)} has no {member}") from None
            if not info.isfile():
                raise SetupError(f"{url(arch)}: {member} is not a file")
            staged = Path(tmp) / "pandoc"
            with t.extractfile(info) as f, open(staged, "wb") as out:
                shutil.copyfileobj(f, out)
        if _sha256(staged) != binary_sha:
            raise SetupError(f"{member} does not match its pinned checksum; nothing installed")
        staged.chmod(0o755)
        os.replace(staged, dest)
    return dest


def setup(bin_dir=None, arch: str | None = None) -> int:
    try:
        dest = install(bin_dir, arch)
    except SetupError as e:
        print(f"publishing: {e}", file=sys.stderr)
        return e.exit_code
    print(f"pandoc {VERSION} (linux-{arch or host_arch()}): {dest}")
    if pandoc_bin() != dest:
        print(f"publishing: note: convert finds {pandoc_bin() or 'no pandoc'} first; "
              f"set PANDOC_BIN={dest} to use this one", file=sys.stderr)
    return 0
