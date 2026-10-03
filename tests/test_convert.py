"""`publishing convert`: Office to PDF through office2pdf, run against stand-in executables.

The first seven tests are spire-venue's server/tests/office-pdf.test.ts converter tests, moved here
with the converter (the venue keeps its twin-naming tests). The rest cover what the move adds:
the time limit, the size cap, the temporary folder, no overwrite, the CLI's exit codes and the
pinned install. The real conversion is test_convert_integration.py.
"""
import hashlib
import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from publishing import convert as cv
from publishing.cli import main


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    """A stand-in converter at a path with a space, an Office source and its PDF path.

    `make(script)` writes the stand-in (a Python script); without a call there is no converter."""
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(cv.tempfile, "tempdir", None)  # re-read TMPDIR
    bin_ = tmp_path / "fake converter"
    monkeypatch.setenv("OFFICE2PDF_BIN", str(bin_))
    src = tmp_path / "source document.docx"
    src.write_text("unit input")

    class F:
        dir, bin, dest = tmp_path, bin_, tmp_path / "source document.pdf"

        @staticmethod
        def make(script: str):
            bin_.write_text(f"#!{sys.executable}\nimport os, sys, time\n{script}\n")
            bin_.chmod(0o755)

    F.src = src
    return F


SUCCESS = """
src, flag, dest = sys.argv[1:]
assert len(sys.argv) == 4, sys.argv
assert flag == "-o", flag
assert open(src).read() == "unit input"
open(dest, "w").write("%PDF-1.4\\nunit output")
"""


# --- the seven tests that moved from spire-venue -------------------------------------------------

def test_passes_source_and_output_arguments_to_the_selected_executable(fixture):
    fixture.make(SUCCESS)
    assert cv.office2pdf_bin() == fixture.bin
    assert cv.convert(fixture.src, fixture.dest) == fixture.dest
    assert fixture.dest.read_text() == "%PDF-1.4\nunit output"


def test_explicit_missing_binary_does_not_fall_back_to_a_host_installation(fixture, monkeypatch):
    real = fixture.dir / "installed"
    real.write_text(f"#!{sys.executable}\n{SUCCESS}")
    real.chmod(0o755)
    monkeypatch.setattr(cv, "SYSTEM_BIN", real)  # a host install that would work
    assert cv.office2pdf_bin() is None
    with pytest.raises(cv.ConverterNotFound, match="office2pdf not found"):
        cv.convert(fixture.src, fixture.dest)
    assert fixture.src.read_text() == "unit input"
    assert not fixture.dest.exists()


def test_non_executable_files_directories_and_empty_overrides_are_not_converters(fixture, monkeypatch):
    fixture.make(SUCCESS)
    fixture.bin.chmod(0o644)
    for candidate in (fixture.bin, fixture.dir, ""):
        monkeypatch.setenv("OFFICE2PDF_BIN", str(candidate))
        assert cv.office2pdf_bin() is None
        with pytest.raises(cv.ConverterNotFound, match="office2pdf not found"):
            cv.convert(fixture.src, fixture.dest)


def test_converter_failure_reports_bounded_stderr_and_leaves_no_pdf(fixture):
    fixture.make("sys.stderr.write('conversion rejected' * 40); sys.exit(7)")
    with pytest.raises(cv.ConvertError) as e:
        cv.convert(fixture.src, fixture.dest)
    assert str(e.value) == ("conversion rejected" * 40)[:400]
    assert fixture.src.read_text() == "unit input"
    assert not fixture.dest.exists()


def test_converter_failure_without_stderr_reports_its_exit_status(fixture):
    fixture.make("sys.exit(7)")
    with pytest.raises(cv.ConvertError, match=r"office2pdf failed \(7\)"):
        cv.convert(fixture.src, fixture.dest)


def test_successful_exit_without_output_is_an_error_not_a_pdf(fixture):
    fixture.make("sys.exit(0)")
    with pytest.raises(cv.ConvertError, match=r"office2pdf failed \(0\)"):
        cv.convert(fixture.src, fixture.dest)
    assert not fixture.dest.exists()


def test_non_office_inputs_never_invoke_the_converter(fixture):
    fixture.make("open(os.path.join(os.path.dirname(sys.argv[0]), 'invoked'), 'w').write('yes')")
    for name in ("report.pdf", "report.txt", "report.doc", "report.docx.txt"):
        src = fixture.dir / name
        src.write_text("unit input")
        with pytest.raises(cv.NotOffice):
            cv.convert(src)
    assert not (fixture.dir / "invoked").exists()


# --- what the move adds ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["deck.pptx", "BOOK.XLSX", "Memo.Docx"])
def test_every_office_extension_in_any_case_converts_beside_its_source(fixture, name):
    fixture.make(SUCCESS)
    src = fixture.dir / name
    src.write_text("unit input")
    assert cv.convert(src) == src.with_suffix(".pdf")
    assert src.with_suffix(".pdf").read_text() == "%PDF-1.4\nunit output"


def test_the_limits_change_nothing_on_success(fixture):
    fixture.make(SUCCESS)
    plain = cv.convert(fixture.src, fixture.dir / "a.pdf").read_bytes()
    tight = cv.convert(fixture.src, fixture.dir / "b.pdf", timeout=30, max_bytes=len(plain)).read_bytes()
    assert plain == tight == b"%PDF-1.4\nunit output"


def test_time_limit_stops_the_converter_and_leaves_no_pdf(fixture):
    fixture.make("open(sys.argv[3], 'w').write('%PDF-1.4 partial'); time.sleep(60)")
    with pytest.raises(cv.ConvertError, match=r"office2pdf timed out after 0\.5 s"):
        cv.convert(fixture.src, fixture.dest, timeout=0.5)
    assert not fixture.dest.exists()


def test_size_cap_stops_an_oversized_output_and_leaves_no_pdf(fixture):
    fixture.make("open(sys.argv[3], 'w').write('%PDF-1.4' + 'x' * 5000)")
    with pytest.raises(cv.ConvertError, match="over the 1000-byte cap"):
        cv.convert(fixture.src, fixture.dest, max_bytes=1000)
    assert not fixture.dest.exists()


def test_size_cap_stops_a_converter_that_keeps_writing(fixture):
    fixture.make("f = open(sys.argv[3], 'w')\nwhile True:\n    f.write('x' * 4096); f.flush(); time.sleep(0.01)")
    with pytest.raises(cv.ConvertError, match="over the 100000-byte cap"):
        cv.convert(fixture.src, fixture.dest, max_bytes=100_000, timeout=30)
    assert not fixture.dest.exists()


def test_an_output_that_is_not_a_pdf_is_an_error(fixture):
    fixture.make("open(sys.argv[3], 'w').write('not a pdf')")
    with pytest.raises(cv.ConvertError, match="not a PDF"):
        cv.convert(fixture.src, fixture.dest)
    assert not fixture.dest.exists()


@pytest.mark.parametrize("script", [SUCCESS, "sys.exit(7)", "time.sleep(60)"])
def test_the_temporary_folder_is_always_removed(fixture, script):
    fixture.make(script)
    try:
        cv.convert(fixture.src, fixture.dest, timeout=0.5)
    except cv.ConvertError:
        pass
    assert list((fixture.dir / "tmp").iterdir()) == []


def test_never_overwrites_an_existing_pdf(fixture):
    fixture.make(SUCCESS)
    fixture.dest.write_text("existing PDF")
    with pytest.raises(cv.OutputExists):
        cv.convert(fixture.src, fixture.dest)
    assert fixture.dest.read_text() == "existing PDF"


def test_a_missing_source_is_a_usage_error(fixture):
    fixture.make(SUCCESS)
    with pytest.raises(cv.SourceMissing):
        cv.convert(fixture.dir / "absent.docx")


def test_without_an_override_the_lookup_is_installed_then_pinned_then_developer(tmp_path, monkeypatch):
    monkeypatch.delenv("OFFICE2PDF_BIN", raising=False)
    monkeypatch.setenv("PUBLISHING_CACHE", str(tmp_path / "cache"))
    system, dev = tmp_path / "system" / "office2pdf", tmp_path / "dev" / "office2pdf"
    monkeypatch.setattr(cv, "SYSTEM_BIN", system)
    monkeypatch.setattr(cv, "DEV_BIN", dev)
    pinned = cv.pinned_bin()
    assert pinned.is_relative_to(tmp_path / "cache")
    assert cv.office2pdf_bin() is None
    for p in (dev, pinned, system):  # each one found shadows the ones after it
        p.parent.mkdir(parents=True)
        p.write_text("#!/bin/sh\n")
        p.chmod(0o755)
        assert cv.office2pdf_bin() == p


# --- the CLI: stdout is the PDF's path; exit codes 0 / 1 / 2 / 3 ----------------------------------

def run(*args, env=None):
    return subprocess.run([sys.executable, "-m", "publishing.cli", "convert", *map(str, args)],
                          capture_output=True, text=True, env={**os.environ, **(env or {})})


def test_cli_prints_the_pdf_path_and_exits_0(fixture):
    fixture.make(SUCCESS)
    r = run(fixture.src, "-o", fixture.dir / "out.pdf")
    assert (r.returncode, r.stdout, r.stderr) == (0, f"{fixture.dir / 'out.pdf'}\n", "")
    assert main(["convert", str(fixture.src)]) == 0
    assert fixture.dest.read_text() == "%PDF-1.4\nunit output"


def test_cli_exit_codes(fixture):
    fixture.make("sys.stderr.write('bad file'); sys.exit(4)")
    r = run(fixture.src)
    assert (r.returncode, r.stdout, r.stderr) == (1, "", "publishing: bad file\n")
    other = fixture.dir / "notes.txt"
    other.write_text("x")
    assert run(other).returncode == 2
    assert run(fixture.src, "--timeout", "0").returncode == 2
    assert run(fixture.src, env={"OFFICE2PDF_BIN": ""}).returncode == 3


# --- the pinned install (`publishing setup --convert`) ------------------------------------------

def fake_release(monkeypatch, target="x86_64-unknown-linux-musl", payload=b"#!/bin/sh\necho office2pdf 0.6.7\n"):
    """Pin a fake release for `target` whose archive _fetch returns; returns the archive bytes."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in ((f"{cv.archive_stem(target)}/README.md", b"readme"),
                           (f"{cv.archive_stem(target)}/office2pdf", payload)):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o755
            t.addfile(info, io.BytesIO(data))
    archive = buf.getvalue()
    monkeypatch.setitem(cv.PINS, target, (hashlib.sha256(archive).hexdigest(), hashlib.sha256(payload).hexdigest()))
    monkeypatch.setattr(cv, "_fetch", lambda url, out: out.write_bytes(archive))
    return archive


def test_setup_installs_the_pinned_build_and_is_idempotent(tmp_path, monkeypatch):
    fake_release(monkeypatch)
    dest = cv.install(tmp_path / "bin", target="x86_64-unknown-linux-musl")
    assert dest == tmp_path / "bin" / "office2pdf" and os.access(dest, os.X_OK)
    assert subprocess.run([dest], capture_output=True, text=True).stdout == "office2pdf 0.6.7\n"
    monkeypatch.setattr(cv, "_fetch", lambda url, out: pytest.fail("a current install downloads nothing"))
    assert cv.install(tmp_path / "bin", target="x86_64-unknown-linux-musl") == dest


def test_setup_refuses_an_archive_that_fails_its_checksum(tmp_path, monkeypatch):
    fake_release(monkeypatch)
    monkeypatch.setattr(cv, "_fetch", lambda url, out: out.write_bytes(b"tampered"))
    with pytest.raises(cv.SetupError, match="checksum"):
        cv.install(tmp_path / "bin", target="x86_64-unknown-linux-musl")
    assert not (tmp_path / "bin" / "office2pdf").exists()


def test_setup_refuses_a_target_with_no_pinned_build(tmp_path):
    with pytest.raises(cv.SetupError, match="no pinned office2pdf build for riscv64-unknown-linux-musl"):
        cv.install(tmp_path / "bin", target="riscv64-unknown-linux-musl")


def test_pins_are_the_upstream_v067_release():
    assert cv.VERSION == "v0.6.7"
    assert {"x86_64-unknown-linux-musl", "x86_64-unknown-linux-gnu"} <= set(cv.PINS)
    for archive_sha, binary_sha in cv.PINS.values():
        assert len(archive_sha) == len(binary_sha) == 64
    assert cv.url("x86_64-unknown-linux-musl") == ("https://github.com/developer0hye/office2pdf/releases/download/"
                                                   "v0.6.7/office2pdf-v0.6.7-x86_64-unknown-linux-musl.tar.gz")


# --- the convert profile: no Playwright, no Chromium ---------------------------------------------

def test_convert_imports_only_the_standard_library():
    probe = ("import sys, publishing.convert\n"
             "heavy = [m for m in ('playwright', 'pypdf', 'pypdfium2', 'PIL', 'markdown_it') if m in sys.modules]\n"
             "assert not heavy, heavy")
    subprocess.run([sys.executable, "-c", probe], check=True)


@pytest.fixture
def no_render(tmp_path):
    """An environment in which every module the render extra installs fails to import."""
    from publishing.cli import RENDER_MODULES

    blocker = tmp_path / "blocker"
    for name in RENDER_MODULES:
        (blocker / name).mkdir(parents=True)
        (blocker / name / "__init__.py").write_text(f"raise ModuleNotFoundError({f'No module named {name!r}'!r}, name={name!r})")
    return {"PYTHONPATH": str(blocker)}


def test_convert_runs_without_the_render_profile(fixture, no_render):
    fixture.make(SUCCESS)
    r = run(fixture.src, env=no_render)
    assert (r.returncode, r.stdout, r.stderr) == (0, f"{fixture.dest}\n", "")


def test_render_commands_name_the_render_profile_when_it_is_missing(tmp_path, no_render):
    for cmd in (["build"], ["check"], ["publish", "x"], ["compare", "a", "b", "-o", "c"],
                ["html", "a.html", "-o", "a.pdf"], ["setup"], ["setup", "--render"], ["setup", "--video"]):
        r = subprocess.run([sys.executable, "-m", "publishing.cli", *cmd], capture_output=True, text=True,
                           cwd=tmp_path, env={**os.environ, **no_render})
        assert r.returncode == 3, (cmd, r.stderr)
        assert "publishing[render]" in r.stderr
