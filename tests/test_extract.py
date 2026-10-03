"""publishing extract: one small self-contained fixture per format, the limits, the errors, no network.

The format tests need the `extract` extra (markitdown) and skip without it, as the render tests skip
without Playwright; the Dockerfile.extract test stage and CI run them with it. Fixtures are built here
from the standard library (OOXML, EPUB and PDF by hand) so no binary file is committed.
"""
import http.server
import io
import json
import os
import subprocess
import sys
import threading
import zipfile

import re
from pathlib import Path

import pytest

from publishing import extract as ex

needs_markitdown = pytest.mark.skipif(not ex.available(), reason="the extract extra is not installed")

WORD = "Zebrafish"


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            z.writestr(zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)), text)
    return buf.getvalue()


def docx() -> bytes:
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    return _zip({
        "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/document.xml": f'<?xml version="1.0"?><w:document {ns}><w:body>'
        f'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Title {WORD}</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>Body paragraph.</w:t></w:r></w:p></w:body></w:document>',
    })


def pptx() -> bytes:
    from pptx import Presentation

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = f"Slide {WORD}"
    slide.placeholders[1].text = "Bullet one"
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def xlsx() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["name", "count"])
    ws.append([WORD, 3])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def epub() -> bytes:
    return _zip({
        "mimetype": "application/epub+zip",
        "META-INF/container.xml": '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        "content.opf": '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Book</dc:title><dc:identifier id="id">x</dc:identifier>'
        '<dc:language>en</dc:language></metadata><manifest><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/></manifest>'
        '<spine><itemref idref="c1"/></spine></package>',
        "c1.xhtml": f'<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Chapter {WORD}</h1><p>Text.</p></body></html>',
    })


def pdf() -> bytes:
    stream = f"BT /F1 24 Tf 72 700 Td ({WORD} in a PDF) Tj ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


FIXTURES = {
    "a.pdf": pdf,
    "a.docx": docx,
    "a.pptx": pptx,
    "a.xlsx": xlsx,
    "a.epub": epub,
    "a.html": lambda: f"<html><body><h1>Page {WORD}</h1><p>Hello <a href='https://example.invalid/x'>link</a></p></body></html>".encode(),
    "a.csv": lambda: f"name,count\n{WORD},3\n".encode(),
    "a.json": lambda: json.dumps({"name": WORD, "n": 3}).encode(),
    "a.xml": lambda: f"<root><item>{WORD}</item></root>".encode(),
    "a.txt": lambda: f"{WORD} plain text\n".encode(),
}


@needs_markitdown
@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_each_format_becomes_markdown_with_its_text(tmp_path, name):
    src = tmp_path / name
    src.write_bytes(FIXTURES[name]())
    dest = ex.extract(src)
    assert dest == src.with_suffix(".md")
    assert WORD in dest.read_text(encoding="utf-8")
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([name, dest.name])


@needs_markitdown
def test_html_keeps_structure_and_the_command_prints_only_the_path(tmp_path, capsys):
    from publishing import cli

    src = tmp_path / "A.HTML"  # letter case does not matter
    src.write_bytes(FIXTURES["a.html"]())
    assert cli.main(["extract", str(src), "-o", str(tmp_path / "out" / "x.md")]) == 0
    assert capsys.readouterr().out == f"{tmp_path / 'out' / 'x.md'}\n"
    text = (tmp_path / "out" / "x.md").read_text()
    assert text.startswith(f"# Page {WORD}") and "[link](https://example.invalid/x)" in text


@needs_markitdown
def test_spreadsheet_is_a_table(tmp_path):
    src = tmp_path / "a.xlsx"
    src.write_bytes(xlsx())
    text = ex.extract(src).read_text()
    assert "## Sheet1" in text and "| name | count |" in text


def test_unsupported_types_never_reach_markitdown(tmp_path):
    for name in ("a.png", "a.mp3", "a.zip", "a", "a.doc"):
        (tmp_path / name).write_bytes(b"x")
        with pytest.raises(ex.Unsupported) as e:
            ex.extract(tmp_path / name)
        assert e.value.exit_code == 2


def test_usage_errors_are_exit_2(tmp_path):
    with pytest.raises(ex.SourceMissing):
        ex.extract(tmp_path / "gone.pdf")
    src = tmp_path / "a.txt"
    src.write_text("x")
    (tmp_path / "a.md").write_text("mine")
    with pytest.raises(ex.OutputExists) as e:
        ex.extract(src)
    assert e.value.exit_code == 2 and (tmp_path / "a.md").read_text() == "mine"


def test_without_markitdown_the_exit_is_3(tmp_path, monkeypatch):
    src = tmp_path / "a.txt"
    src.write_text("x")
    monkeypatch.setattr(ex, "available", lambda: False)
    with pytest.raises(ex.ExtractorNotFound) as e:
        ex.extract(src)
    assert e.value.exit_code == 3 and not (tmp_path / "a.md").exists()


@needs_markitdown
def test_empty_result_is_an_error_and_leaves_nothing(tmp_path):
    src = tmp_path / "blank.txt"
    src.write_text("  \n\n")
    with pytest.raises(ex.ExtractError, match="no text"):
        ex.extract(src)
    assert [p.name for p in tmp_path.iterdir()] == ["blank.txt"]


@needs_markitdown
def test_a_parser_failure_is_one_bounded_message(tmp_path):
    src = tmp_path / "broken.docx"
    src.write_bytes(_zip({"[Content_Types].xml": "not xml " * 100, "word/document.xml": "x"}))
    with pytest.raises(ex.ExtractError) as e:
        ex.extract(src)
    assert 0 < len(str(e.value)) <= ex.STDERR_CHARS and e.value.exit_code == 1
    assert [p.name for p in tmp_path.iterdir()] == ["broken.docx"]


def _stand_in(monkeypatch, tmp_path, body: str):
    """A child that is `body` (Python) instead of markitdown."""
    script = tmp_path / "child.py"
    script.write_text(body)
    real = subprocess.Popen

    def popen(cmd, **kw):
        return real([sys.executable, str(script), *cmd[-2:]], **kw)

    monkeypatch.setattr(ex.subprocess, "Popen", popen)
    monkeypatch.setattr(ex, "available", lambda: True)


def test_the_time_limit_kills_the_child(tmp_path, monkeypatch):
    _stand_in(monkeypatch, tmp_path, "import time; time.sleep(60)")
    (tmp_path / "a.txt").write_text("x")
    with pytest.raises(ex.ExtractError, match="timed out after 0.3 s"):
        ex.extract(tmp_path / "a.txt", timeout=0.3)
    assert not (tmp_path / "a.md").exists()


def test_the_cap_stops_a_child_that_keeps_writing(tmp_path, monkeypatch):
    _stand_in(monkeypatch, tmp_path,
              "import sys,time\nf=open(sys.argv[2],'w')\nwhile True:\n f.write('x'*65536); f.flush(); time.sleep(0.01)")
    (tmp_path / "a.txt").write_text("x")
    with pytest.raises(ex.ExtractError, match="byte cap"):
        ex.extract(tmp_path / "a.txt", max_bytes=100_000, timeout=20)
    assert not (tmp_path / "a.md").exists()


def test_the_limits_change_nothing_on_success(tmp_path, monkeypatch):
    _stand_in(monkeypatch, tmp_path, "import sys; open(sys.argv[2],'w').write('# ok\\n')")
    (tmp_path / "a.txt").write_text("x")
    assert ex.extract(tmp_path / "a.txt", timeout=5, max_bytes=5).read_text() == "# ok\n"


def test_child_stderr_is_bounded(tmp_path, monkeypatch):
    _stand_in(monkeypatch, tmp_path, "import sys; sys.stderr.write('e'*5000); sys.exit(1)")
    (tmp_path / "a.txt").write_text("x")
    with pytest.raises(ex.ExtractError) as e:
        ex.extract(tmp_path / "a.txt")
    assert str(e.value) == "e" * ex.STDERR_CHARS


def test_silent_failure_names_the_status(tmp_path, monkeypatch):
    _stand_in(monkeypatch, tmp_path, "import sys; sys.exit(7)")
    (tmp_path / "a.txt").write_text("x")
    with pytest.raises(ex.ExtractError, match=r"markitdown failed \(7\)"):
        ex.extract(tmp_path / "a.txt")


# --- no network -------------------------------------------------------------------------------

def test_the_child_cannot_open_a_connection(tmp_path):
    """After _block_network, every way to a socket raises, in a fresh interpreter."""
    code = (
        "import socket\nfrom publishing import extract\nextract._block_network()\n"
        "for f in (lambda: socket.create_connection(('127.0.0.1', 9)), lambda: socket.getaddrinfo('localhost', 80),\n"
        "          lambda: socket.socket().connect(('127.0.0.1', 9)), lambda: socket.gethostbyname('localhost')):\n"
        "    try: f()\n    except OSError as e: assert 'disabled' in str(e)\n    else: raise SystemExit('connected')\n"
    )
    assert subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).returncode == 0


@needs_markitdown
def test_a_document_that_references_a_server_never_calls_it(tmp_path):
    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        log_message = lambda *a: None  # noqa: E731

    server = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        src = tmp_path / "a.html"
        src.write_text(f"<html><body><p>{WORD}</p><img src='{base}/i.png'><a href='{base}/l'>l</a>"
                       f"<link rel=stylesheet href='{base}/s.css'></body></html>")
        assert WORD in ex.extract(src).read_text()
        data = tmp_path / "b.txt"
        data.write_text(f"{WORD} {base}/x")
        ex.extract(data)
    finally:
        server.shutdown()
    assert hits == []


@needs_markitdown
def test_markitdown_is_the_pinned_version():
    from importlib.metadata import version

    assert version("markitdown") == ex.MARKITDOWN
    assert f"markitdown[pdf,docx,pptx,xlsx]=={ex.MARKITDOWN}" in open(
        os.path.join(os.path.dirname(__file__), "..", "pyproject.toml")).read()


# --- PDF structure: pages (form feeds) and paragraphs survive, for Chromium output and forms -----

SAMPLES = Path(__file__).resolve().parent / "fixtures"  # Chromium-made, copies of docs/samples


def _pdf_pages(pages: list[list[tuple[int, int, str]]]) -> bytes:
    """A small PDF: each page a list of (x, y, text) in Helvetica 10."""
    n = len(pages)
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{' '.join(f'{3 + 2 * i} 0 R' for i in range(n))}] /Count {n} >>"]
    for i, items in enumerate(pages):
        stream = "BT /F1 10 Tf " + " ".join(f"1 0 0 1 {x} {y} Tm ({t}) Tj" for x, y, t in items) + " ET"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
                    f"/Resources << /Font << /F1 {3 + 2 * n} 0 R >> >> >>")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def _form_pdf() -> bytes:
    """Three pages of borderless three-column rows: markitdown 0.1.8 takes these for forms."""
    page = [(72 + 150 * c, 700 - 20 * r, f"{h} {r}") for r in range(8) for c, h in enumerate(("Item", "Qty", "Price"))]
    return _pdf_pages([page, page, page])


def _text(tmp_path, name, data) -> str:
    src = tmp_path / name
    src.write_bytes(data)
    return ex.extract(src).read_text(encoding="utf-8")


def _paragraphs(text: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", text.replace("\f", "\n\n")) if p.strip()]


@needs_markitdown
@pytest.mark.parametrize("name,pages", [("house-style-deck-v1.pdf", 4), ("house-style-memo-v1.pdf", 2),
                                        ("house-style-document-v1.pdf", 3)])
def test_chromium_pdf_keeps_pages_and_paragraphs(tmp_path, name, pages):
    text = _text(tmp_path, name, (SAMPLES / name).read_bytes())
    assert text.count("\f") in (pages, pages - 1)
    assert len(_paragraphs(text)) >= 5 * pages  # blank-line separated, not one block per page
    assert "ﬁ" not in text and "ﬀ" not in text  # ligatures are letters
    assert not re.search(r"\b(?:[A-Z] ){4,}[A-Z]\b", text)  # kickers are closed up
    assert "PUBLISHING" in text


@needs_markitdown
def test_form_like_pdf_keeps_its_pages(tmp_path):
    data = _form_pdf()
    from markitdown import MarkItDown
    src = tmp_path / "f.pdf"
    src.write_bytes(data)
    # the reason for the fix: markitdown's own PDF converter loses the page breaks on this file
    assert "\f" not in MarkItDown(enable_plugins=False, exiftool_path="").convert_local(str(src)).markdown
    text = _text(tmp_path, "form.pdf", data)
    assert text.count("\f") in (3, 2)
    assert "Price 7" in text


@needs_markitdown
def test_plain_pdf_text_is_pdfminers_after_normalisation(tmp_path):
    from pdfminer.high_level import extract_text

    def norm(t):
        t = "\n".join(line.rstrip() for line in t.replace("\r\n", "\n").split("\n"))
        return re.sub(r"\n{3,}", "\n\n", t)
    data = _pdf_pages([[(72, 700, "First paragraph."), (72, 640, "Second paragraph.")], [(72, 700, "Page two.")]])
    src = tmp_path / "p.pdf"
    src.write_bytes(data)
    assert norm(_text(tmp_path, "q.pdf", data)) == norm(extract_text(str(src)))
    assert _text(tmp_path, "r.pdf", data).count("\f") in (1, 2)


def test_close_kicker_only_touches_letter_spaced_lines():
    assert ex._close_kicker("D E S I G N   N O T E") == "DESIGN NOTE"
    assert ex._close_kicker("P U B L I S H I N G   ·   T H E   H OU S E") == "PUBLISHING · THE HOUSE"
    for line in ("A B C", "Option A B C D E is fine", "I do not know"):
        assert ex._close_kicker(line) == line


@needs_markitdown
def test_no_text_is_exit_4_and_a_parser_failure_stays_1(tmp_path):
    blank = tmp_path / "blank.pdf"
    blank.write_bytes(_pdf_pages([[]]))
    with pytest.raises(ex.NoText) as e:
        ex.extract(blank)
    assert e.value.exit_code == 4 and not (tmp_path / "blank.md").exists()
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    with pytest.raises(ex.ExtractError) as e:
        ex.extract(broken)
    assert e.value.exit_code == 1 and not isinstance(e.value, ex.NoText)
