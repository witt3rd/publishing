"""`publishing convert` with the pandoc engine, run against stand-in executables.

The routing between the two engines, the hardening flags, the limits, the temporary folder, no
overwrite, the exit codes and the pinned install. The real conversions are test_pandoc_integration.py.
"""
import hashlib
import io
import json
import os
import sys
import tarfile
from pathlib import Path

import pytest

from publishing import convert as cv
from publishing import pandoc as pd
from publishing.cli import main


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    """A stand-in pandoc that records its command line and environment, a markdown source and
    helpers: `make(script)` replaces the stand-in's body; the default writes a valid output."""
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(cv.tempfile, "tempdir", None)
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    bin_ = tmp_path / "fake pandoc"
    monkeypatch.setenv("PANDOC_BIN", str(bin_))
    monkeypatch.setattr(pd.shutil, "which", lambda name, *a, **k: "/bin/true")  # a TeX engine is present
    src = tmp_path / "source note.md"
    src.write_text("# Hello\n")
    log = tmp_path / "log.json"

    class F:
        dir, bin, src_, log_ = tmp_path, bin_, src, log

        @staticmethod
        def make(script: str):
            bin_.write_text(f"#!{sys.executable}\nimport json, os, sys, time\n{script}\n")
            bin_.chmod(0o755)

        @staticmethod
        def ok():
            F.make(f"""
a = sys.argv[1:]
out = a[a.index("-o") + 1]
json.dump({{"args": a, "env": dict(os.environ), "cwd": os.getcwd(), "out": out}}, open({str(log)!r}, "w"))
fmt = a[a.index("-t") + 1]
open(out, "wb").write({{"pdf": b"%PDF-1.5 x", "docx": b"PK\\x03\\x04 x", "html5": b"<!doctype html>"}}[fmt])
""")

        @staticmethod
        def seen():
            return json.loads(log.read_text())

    F.src = src
    return F


def test_markdown_to_pdf_runs_a_hardened_deterministic_pandoc(fixture):
    fixture.ok()
    dest = fixture.dir / "out.pdf"
    assert pd.convert(fixture.src, dest) == dest
    assert dest.read_bytes().startswith(b"%PDF-")
    seen = fixture.seen()
    args = seen["args"]
    assert "--sandbox" in args
    assert args[args.index("-f") + 1] == "markdown-raw_tex-raw_attribute"
    assert "--pdf-engine=pdflatex" in args and "--pdf-engine-opt=-no-shell-escape" in args
    env = seen["env"]
    assert env["SOURCE_DATE_EPOCH"] == "0" and env["FORCE_SOURCE_DATE"] == "1"
    assert env["openin_any"] == "p" and env["openout_any"] == "p" and env["shell_escape"] == "f"
    assert Path(args[-1]).parent == Path(seen["cwd"]).resolve()  # reads a staged copy, in the temporary folder


def test_the_callers_source_date_epoch_is_kept(fixture, monkeypatch):
    fixture.ok()
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    pd.convert(fixture.src, fixture.dir / "o.docx")
    assert fixture.seen()["env"]["SOURCE_DATE_EPOCH"] == "1700000000"


def test_the_environment_carries_no_secrets(fixture, monkeypatch):
    fixture.ok()
    monkeypatch.setenv("SECRET_TOKEN", "hunter2")
    pd.convert(fixture.src, fixture.dir / "o.html")
    assert "SECRET_TOKEN" not in fixture.seen()["env"]


@pytest.mark.parametrize("name,reader", [("a.md", "markdown-raw_tex-raw_attribute"), ("a.MARKDOWN", "markdown-raw_tex-raw_attribute"),
                                         ("a.html", "html"), ("a.htm", "html"), ("a.docx", "docx"), ("a.odt", "odt")])
def test_each_source_format_has_its_reader(fixture, name, reader):
    fixture.ok()
    src = fixture.dir / name
    src.write_text("x")
    pd.convert(src, fixture.dir / "o.html")
    args = fixture.seen()["args"]
    assert args[args.index("-f") + 1] == reader


@pytest.mark.parametrize("suffix,writer,magic", [(".pdf", "pdf", b"%PDF-"), (".docx", "docx", b"PK\x03\x04"),
                                                 (".html", "html5", b"<!doctype"), (".HTM", "html5", b"<!doctype")])
def test_each_output_format_has_its_writer(fixture, suffix, writer, magic):
    fixture.ok()
    dest = fixture.dir / f"o{suffix}"
    pd.convert(fixture.src, dest)
    args = fixture.seen()["args"]
    assert args[args.index("-t") + 1] == writer
    assert dest.read_bytes().startswith(magic)


def test_html_is_standalone_with_a_title_from_the_source_name(fixture):
    fixture.ok()
    pd.convert(fixture.src, fixture.dir / "o.html")
    args = fixture.seen()["args"]
    assert "-s" in args and "pagetitle=source note" in args


def test_default_output_is_beside_the_source_with_the_format_suffix(fixture):
    fixture.ok()
    assert pd.convert(fixture.src) == fixture.dir / "source note.pdf"
    assert pd.convert(fixture.src, to="docx") == fixture.dir / "source note.docx"
    assert pd.convert(fixture.src, to="html") == fixture.dir / "source note.html"


def test_to_must_agree_with_the_output_path(fixture):
    fixture.ok()
    with pytest.raises(pd.UnsupportedConversion):
        pd.convert(fixture.src, fixture.dir / "o.pdf", to="docx")
    with pytest.raises(pd.UnsupportedConversion):
        pd.convert(fixture.src, fixture.dir / "o.rtf")
    with pytest.raises(pd.UnsupportedConversion):
        pd.convert(fixture.src, to="epub")


def test_sources_pandoc_does_not_read_are_refused(fixture):
    fixture.ok()
    for name in ("sheet.xlsx", "deck.pptx", "page.txt", "noext"):
        (fixture.dir / name).write_text("x")
        with pytest.raises(pd.UnsupportedConversion):
            pd.convert(fixture.dir / name, fixture.dir / "o.pdf")
    with pytest.raises(pd.SourceMissing):
        pd.convert(fixture.dir / "missing.md", fixture.dir / "o.pdf")


def test_an_existing_output_is_never_overwritten(fixture):
    fixture.ok()
    dest = fixture.dir / "o.pdf"
    dest.write_text("mine")
    with pytest.raises(pd.OutputExists):
        pd.convert(fixture.src, dest)
    assert dest.read_text() == "mine"
    assert not fixture.log_.exists()  # refused before pandoc ran


def test_no_pandoc_is_exit_3_and_names_the_fix(fixture, monkeypatch):
    fixture.bin.unlink(missing_ok=True)
    with pytest.raises(pd.ConverterNotFound, match="PANDOC_BIN"):
        pd.convert(fixture.src, fixture.dir / "o.pdf")
    monkeypatch.delenv("PANDOC_BIN")
    monkeypatch.setattr(pd, "SYSTEM_BIN", fixture.dir / "none")
    monkeypatch.setenv("PUBLISHING_CACHE", str(fixture.dir / "cache"))
    with pytest.raises(pd.ConverterNotFound, match="setup --pandoc"):
        pd.convert(fixture.src, fixture.dir / "o.pdf")


def test_a_pdf_without_a_tex_engine_is_exit_3_but_html_still_converts(fixture, monkeypatch):
    fixture.ok()
    monkeypatch.setattr(pd.shutil, "which", lambda name, *a, **k: None)
    with pytest.raises(pd.ConverterNotFound, match="pdflatex"):
        pd.convert(fixture.src, fixture.dir / "o.pdf")
    assert pd.convert(fixture.src, fixture.dir / "o.html").exists()


def test_failure_carries_400_chars_of_stderr_and_leaves_no_output(fixture):
    fixture.make('sys.stderr.write("E" * 1000); sys.exit(43)')
    dest = fixture.dir / "o.pdf"
    with pytest.raises(pd.ConvertError) as e:
        pd.convert(fixture.src, dest)
    assert str(e.value) == "E" * 400 and e.value.exit_code == 1
    assert not dest.exists()


def test_silent_failure_names_the_status(fixture):
    fixture.make("sys.exit(3)")
    with pytest.raises(pd.ConvertError, match=r"pandoc failed \(3\)"):
        pd.convert(fixture.src, fixture.dir / "o.docx")


def test_a_zero_exit_with_no_output_is_an_error(fixture):
    fixture.make("pass")
    with pytest.raises(pd.ConvertError, match="pandoc failed"):
        pd.convert(fixture.src, fixture.dir / "o.docx")


@pytest.mark.parametrize("suffix", [".pdf", ".docx"])
def test_an_output_of_the_wrong_kind_is_an_error(fixture, suffix):
    fixture.make('out = sys.argv[sys.argv.index("-o") + 1]; open(out, "wb").write(b"not it")')
    dest = fixture.dir / f"o{suffix}"
    with pytest.raises(pd.ConvertError, match="not a"):
        pd.convert(fixture.src, dest)
    assert not dest.exists()


def test_time_limit_kills_pandoc_and_leaves_nothing(fixture):
    fixture.make("time.sleep(30)")
    with pytest.raises(pd.ConvertError, match="pandoc timed out after 0.3 s"):
        pd.convert(fixture.src, fixture.dir / "o.pdf", timeout=0.3)
    assert list((fixture.dir / "tmp").iterdir()) == []


def test_the_output_cap_stops_pandoc_while_it_runs(fixture):
    fixture.make('out = sys.argv[sys.argv.index("-o") + 1]; open(out, "wb").write(b"%PDF-" + b"0" * 5000); time.sleep(30)')
    with pytest.raises(pd.ConvertError, match="over the 1000-byte cap"):
        pd.convert(fixture.src, fixture.dir / "o.pdf", max_bytes=1000)


def test_the_temporary_folder_is_removed_after_success_and_failure(fixture):
    fixture.ok()
    pd.convert(fixture.src, fixture.dir / "o.pdf")
    fixture.make("sys.exit(1)")
    with pytest.raises(pd.ConvertError):
        pd.convert(fixture.src, fixture.dir / "p.pdf")
    assert list((fixture.dir / "tmp").iterdir()) == []


# --- the routing between engines, and the command -------------------------------------------------

def test_an_office_file_to_pdf_keeps_office2pdf(fixture, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cv, "convert", lambda src, dest=None, **k: calls.append(("office", str(src))) or Path("x.pdf"))
    monkeypatch.setattr(pd, "convert", lambda *a, **k: calls.append(("pandoc",)) or Path("x"))
    for argv in (["a.docx"], ["a.docx", "-o", "b.pdf"], ["a.xlsx"], ["a.PPTX", "--to", "pdf"], ["a.docx", "-o", "weird.xyz"]):
        assert main(["convert", *argv]) == 0
    assert [c[0] for c in calls] == ["office"] * 5


def test_everything_else_goes_to_pandoc(fixture, monkeypatch):
    calls = []
    monkeypatch.setattr(cv, "convert", lambda *a, **k: calls.append("office") or Path("x"))
    monkeypatch.setattr(pd, "convert", lambda src, dest=None, **k: calls.append((str(src), k["to"])) or Path("x"))
    for argv in (["a.md"], ["a.html", "-o", "b.docx"], ["a.docx", "-o", "b.html"], ["a.odt", "--to", "pdf"],
                 ["a.docx", "--engine", "pandoc"]):
        assert main(["convert", *argv]) == 0
    assert calls == [("a.md", "pdf"), ("a.html", "docx"), ("a.docx", "html"), ("a.odt", "pdf"), ("a.docx", "pdf")]


def test_office2pdf_cannot_write_other_formats(fixture, capsys):
    assert main(["convert", "a.docx", "--engine", "office2pdf", "--to", "html"]) == 2
    assert "office2pdf writes PDFs only" in capsys.readouterr().err


def test_a_spreadsheet_to_docx_is_a_usage_error(fixture, capsys):
    (fixture.dir / "s.xlsx").write_text("x")
    assert main(["convert", str(fixture.dir / "s.xlsx"), "-o", str(fixture.dir / "s.docx")]) == 2
    assert "not a document pandoc reads" in capsys.readouterr().err


def test_cli_prints_the_path_and_exit_codes(fixture, capsys):
    fixture.ok()
    dest = fixture.dir / "o.docx"
    assert main(["convert", str(fixture.src), "-o", str(dest)]) == 0
    assert capsys.readouterr().out == f"{dest}\n"
    assert main(["convert", str(fixture.src), "-o", str(dest)]) == 2
    fixture.bin.unlink()
    assert main(["convert", str(fixture.src), "-o", str(fixture.dir / "p.docx")]) == 3
    fixture.make("sys.exit(1)")
    assert main(["convert", str(fixture.src), "-o", str(fixture.dir / "q.docx")]) == 1
    assert "publishing: " in capsys.readouterr().err


def test_convert_with_pandoc_runs_without_the_render_profile(fixture, monkeypatch):
    import publishing.cli as cli
    monkeypatch.setattr(cli, "NO_RENDER", ModuleNotFoundError("playwright"))
    fixture.ok()
    assert main(["convert", str(fixture.src), "-o", str(fixture.dir / "o.html")]) == 0


# --- the pinned install -------------------------------------------------------------------------------

def _archive(binary: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        info = tarfile.TarInfo(f"pandoc-{pd.VERSION}/bin/pandoc")
        info.size, info.mode = len(binary), 0o755
        t.addfile(info, io.BytesIO(binary))
    return buf.getvalue()


@pytest.fixture
def pins(monkeypatch):
    binary = b"#!/bin/sh\necho pandoc\n"
    archive = _archive(binary)
    monkeypatch.setitem(pd.PINS, "amd64", (hashlib.sha256(archive).hexdigest(), hashlib.sha256(binary).hexdigest()))
    return binary, archive


def test_install_checks_both_checksums_and_downloads_nothing_when_current(tmp_path, monkeypatch, pins):
    binary, archive = pins
    monkeypatch.setattr(pd, "_fetch", lambda url, out: out.write_bytes(archive))
    dest = pd.install(tmp_path / "bin", "amd64")
    assert dest == tmp_path / "bin" / "pandoc" and dest.read_bytes() == binary and os.access(dest, os.X_OK)
    monkeypatch.setattr(pd, "_fetch", lambda url, out: pytest.fail("a current install downloads nothing"))
    assert pd.install(tmp_path / "bin", "amd64") == dest


def test_install_refuses_a_tampered_archive_and_installs_nothing(tmp_path, monkeypatch, pins):
    monkeypatch.setattr(pd, "_fetch", lambda url, out: out.write_bytes(b"tampered"))
    with pytest.raises(pd.SetupError, match="pinned checksum"):
        pd.install(tmp_path / "bin", "amd64")
    assert not (tmp_path / "bin" / "pandoc").exists()


def test_install_refuses_a_tampered_binary_inside_a_good_archive(tmp_path, monkeypatch, pins):
    bad = _archive(b"evil")
    monkeypatch.setitem(pd.PINS, "amd64", (hashlib.sha256(bad).hexdigest(), pd.PINS["amd64"][1]))
    monkeypatch.setattr(pd, "_fetch", lambda url, out: out.write_bytes(bad))
    with pytest.raises(pd.SetupError, match="pinned checksum"):
        pd.install(tmp_path / "bin", "amd64")
    assert not (tmp_path / "bin" / "pandoc").exists()


def test_install_has_no_build_for_other_architectures(tmp_path):
    with pytest.raises(pd.SetupError, match="no pinned pandoc build"):
        pd.install(tmp_path, "riscv64")


def test_the_pins_name_a_release_asset_url_per_architecture():
    assert set(pd.PINS) == {"amd64", "arm64"}
    assert pd.url("amd64") == f"https://github.com/jgm/pandoc/releases/download/{pd.VERSION}/pandoc-{pd.VERSION}-linux-amd64.tar.gz"
    assert all(len(h) == 64 for pair in pd.PINS.values() for h in pair)


def test_setup_pandoc_installs_and_reports(tmp_path, monkeypatch, pins, capsys):
    _, archive = pins
    monkeypatch.setattr(pd, "_fetch", lambda url, out: out.write_bytes(archive))
    monkeypatch.setattr(pd, "host_arch", lambda: "amd64")
    assert main(["setup", "--pandoc", "--bin-dir", str(tmp_path)]) == 0
    assert (tmp_path / "pandoc").is_file()
    assert f"pandoc {pd.VERSION} (linux-amd64)" in capsys.readouterr().out
