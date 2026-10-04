"""What the single-tool profiles (convert, pandoc, extract, media, images) share, standard library only:
the supervised child run, the pinned-binary installer, the local-file checks and the argparse validator."""
import argparse
import hashlib
import os
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

_POLL = 0.05  # seconds between checks of a running child's output size


def run_supervised(cmd: list, name: str, output: Path, err_path: Path, timeout: float, max_bytes: int,
                   error: type, *, env=None, cwd=None, stderr_chars: int = 400, clip=None,
                   need_output: bool = True) -> None:
    """Run `cmd` (the tool `name`) under the time limit and the output cap, in its own process group, which
    is killed whenever this returns or raises. Raises `error`: on a timeout, on output over `max_bytes`
    while it runs, and on a non-zero exit (or, with `need_output`, a missing `output`), carrying at most
    `stderr_chars` of its stderr (`clip` turns the raw bytes into that text)."""
    with open(err_path, "wb") as err:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err,
                                start_new_session=True, env=env, cwd=cwd)
        try:
            deadline = time.monotonic() + timeout
            while proc.poll() is None:
                if time.monotonic() >= deadline:
                    raise error(f"{name} timed out after {timeout:g} s")
                if output.exists() and output.stat().st_size > max_bytes:
                    raise error(f"{name} output is over the {max_bytes}-byte cap")
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
    if status != 0 or (need_output and not output.is_file()):
        with open(err_path, "rb") as f:
            raw = f.read(16 * stderr_chars)
        text = clip(raw) if clip else raw.decode("utf-8", "replace")[:stderr_chars].rstrip()
        raise error(text or f"{name} failed ({status if status >= 0 else f'signal {-status}'})")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(address: str, out: Path) -> None:
    with urllib.request.urlopen(address, timeout=60) as r, open(out, "wb") as f:
        shutil.copyfileobj(r, f)


def install_pinned(dest: Path, name: str, address: str, member: str, archive_sha: str, binary_sha: str,
                   error: type, fetcher=fetch) -> Path:
    """Install the binary `member` of the archive at `address` as `dest`. Checks the archive's and the
    binary's checksums; an install that already matches downloads nothing. Returns `dest`."""
    if dest.is_file() and sha256(dest) == binary_sha and os.access(dest, os.X_OK):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="publishing-setup-", dir=dest.parent) as tmp:
        archive = Path(tmp) / f"{name}.tar.gz"
        try:
            fetcher(address, archive)
        except OSError as e:
            raise error(f"could not download {address}: {e}") from None
        if sha256(archive) != archive_sha:
            raise error(f"{address} does not match its pinned checksum; nothing installed")
        with tarfile.open(archive) as t:
            try:
                info = t.getmember(member)
            except KeyError:
                raise error(f"{address} has no {member}") from None
            if not info.isfile():
                raise error(f"{address}: {member} is not a file")
            staged = Path(tmp) / name
            with t.extractfile(info) as f, open(staged, "wb") as out:
                shutil.copyfileobj(f, out)
        if sha256(staged) != binary_sha:
            raise error(f"{member} does not match its pinned checksum; nothing installed")
        staged.chmod(0o755)
        os.replace(staged, dest)
    return dest


def local_source(src, kinds, what: str, error: type) -> Path:
    """A local file with one of the suffixes `kinds`: a URL, a device or a pipe is refused."""
    text = str(src)
    path = Path(text)
    if "://" in text or text.startswith(("-", "pipe:", "/dev/")) or path.suffix.lower() not in kinds:
        raise error(f"{text}: not a supported local {what} ({', '.join(kinds)})")
    if not path.is_file():
        raise error(f"{text}: no such file")
    return path.resolve()


def local_dest(out, kinds, error: type) -> Path:
    """An output path with one of the suffixes `kinds`, that does not exist: never overwrite."""
    path = Path(out)
    if path.suffix.lower() not in kinds:
        raise error(f"{path}: output must be one of {', '.join(kinds)}")
    if path.exists():
        raise error(f"{path} exists; never overwrite")
    return path


def positive(kind):
    """An argparse type: `kind(text)`, which must be above zero."""
    def parse(text):
        try:
            value = kind(text)
        except ValueError:
            value = 0
        if value <= 0:
            raise argparse.ArgumentTypeError(f"{text!r} is not a positive number")
        return value
    return parse
