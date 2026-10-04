"""The real conversions: the pinned pandoc, and pdfLaTeX for PDFs, on small documents.

Skipped unless pandoc (and, for PDFs, pdflatex) is present; with PANDOC_TESTS=1 a missing one fails.
CI runs it in the pandoc image with no network. Only the standard library reads the outputs.
"""
import os
import shutil
import subprocess
import time
import zipfile

import pytest

from publishing import pandoc as pd

REQUIRED = os.environ.get("PANDOC_TESTS") == "1"
needs_pandoc = pytest.mark.skipif(not REQUIRED and pd.pandoc_bin() is None, reason="no pandoc (PANDOC_TESTS=1 requires it)")
needs_tex = pytest.mark.skipif(not REQUIRED and shutil.which(pd.PDF_ENGINE) is None, reason="no pdflatex (PANDOC_TESTS=1 requires it)")

MARKDOWN = """# A heading

A paragraph with *emphasis*, **strong text**, `code`, and café ünïcode.

| a | b |
|---|---|
| 1 | 2 |

- one
- two
"""


@pytest.fixture(autouse=True)
def _present():
    if REQUIRED:
        assert pd.pandoc_bin(), "PANDOC_TESTS=1 requires an executable pandoc; set PANDOC_BIN"
        assert shutil.which(pd.PDF_ENGINE), "PANDOC_TESTS=1 requires pdflatex"


def _write(tmp_path, name, text=MARKDOWN):
    p = tmp_path / name
    p.write_text(text)
    return p


def _docx_text(path):
    with zipfile.ZipFile(path) as z:
        return z.read("word/document.xml").decode()


@needs_pandoc
def test_pandoc_is_the_pinned_version():
    out = subprocess.run([str(pd.pandoc_bin()), "--version"], capture_output=True, text=True, check=True).stdout
    assert out.splitlines()[0] == f"pandoc {pd.VERSION}"


@needs_pandoc
def test_markdown_to_html(tmp_path):
    out = pd.convert(_write(tmp_path, "note.md"), tmp_path / "note.html")
    text = out.read_text()
    assert "<title>note</title>" in text and "<h1" in text and "<em>emphasis</em>" in text and "café" in text
    assert "<table" in text and "<li>one</li>" in text


@needs_pandoc
def test_markdown_to_docx(tmp_path):
    out = pd.convert(_write(tmp_path, "note.md"), tmp_path / "note.docx")
    text = _docx_text(out)
    assert "A heading" in text and "emphasis" in text and "café" in text


@needs_pandoc
def test_docx_and_html_read_back(tmp_path):
    docx = pd.convert(_write(tmp_path, "note.md"), tmp_path / "note.docx")
    html = pd.convert(docx, tmp_path / "from-docx.html")
    assert "A heading" in html.read_text() and "<strong>strong text</strong>" in html.read_text()
    page = _write(tmp_path, "page.html", "<h1>Title</h1><p>Body <b>bold</b></p>")
    assert "Body" in _docx_text(pd.convert(page, tmp_path / "page.docx"))


@needs_pandoc
def test_odt_is_read(tmp_path):
    odt = tmp_path / "note.odt"
    subprocess.run([str(pd.pandoc_bin()), "-f", "markdown", "-o", str(odt), str(_write(tmp_path, "note.md"))], check=True)
    assert "A heading" in pd.convert(odt, tmp_path / "from-odt.html").read_text()


@needs_pandoc
def test_outputs_are_byte_identical_across_runs(tmp_path):
    src = _write(tmp_path, "note.md")
    for suffix in (".docx", ".html"):
        a = pd.convert(src, tmp_path / f"a{suffix}").read_bytes()
        time.sleep(1.1)  # the wall clock moves; the output must not
        b = pd.convert(src, tmp_path / f"b{suffix}").read_bytes()
        assert a == b, suffix


@needs_pandoc
def test_a_persons_markdown_cannot_read_files_or_run_tex(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-VALUE")
    src = _write(tmp_path, "evil.md", f"\\input{{{secret}}}\n\n![img]({secret})\n\n```{{=latex}}\n\\input{{{secret}}}\n```\n\n"
                 f"[inc]: {secret}\n")
    for suffix in (".html", ".docx"):
        out = pd.convert(src, tmp_path / f"evil{suffix}")
        data = out.read_bytes() if suffix == ".html" else _docx_text(out).encode()
        assert b"TOP-SECRET-VALUE" not in data


@needs_pandoc
@needs_tex
def test_markdown_to_pdf(tmp_path):
    out = pd.convert(_write(tmp_path, "note.md"), tmp_path / "note.pdf")
    data = out.read_bytes()
    assert data.startswith(b"%PDF-") and (b"/Type /Page" in data or b"/Type/Page" in data)
    assert 1000 < len(data) < 1_000_000


@needs_pandoc
@needs_tex
def test_pdfs_are_byte_identical_across_runs(tmp_path):
    src = _write(tmp_path, "note.md")
    a = pd.convert(src, tmp_path / "a.pdf").read_bytes()
    b = pd.convert(src, tmp_path / "b.pdf").read_bytes()
    assert a == b


@needs_pandoc
@needs_tex
def test_html_and_docx_to_pdf(tmp_path):
    page = _write(tmp_path, "page.html", "<h1>Title</h1><p>Body</p>")
    assert pd.convert(page, tmp_path / "page.pdf").read_bytes().startswith(b"%PDF-")
    docx = pd.convert(_write(tmp_path, "note.md"), tmp_path / "note.docx")
    assert pd.convert(docx, tmp_path / "from-docx.pdf").read_bytes().startswith(b"%PDF-")


@needs_pandoc
@needs_tex
def test_tex_cannot_read_or_shell_out_from_a_pdf_build(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-VALUE")
    src = _write(tmp_path, "evil.md", f"\\input{{{secret}}}\n\n\\immediate\\write18{{touch {tmp_path}/pwned}}\n")
    pd.convert(src, tmp_path / "evil.pdf")
    assert not (tmp_path / "pwned").exists()
