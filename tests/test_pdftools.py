"""publishing pdf: merge, pages and strip, one test group per capability, plus the cleaning, the limits, the
refusals and determinism. They need pypdf and skip without it; the Dockerfile.pdf test stage and CI run them in
the image, with no network. Fixtures are generated here (pypdf), so no binary is committed.
"""
import subprocess
import sys

import pytest

pypdf = pytest.importorskip("pypdf")
from pypdf import PdfReader, PdfWriter  # noqa: E402
from pypdf.generic import (ArrayObject, DictionaryObject, NameObject, NumberObject,  # noqa: E402
                           TextStringObject)

from publishing import pdftools  # noqa: E402


def cli(*args, cwd=None):
    return subprocess.run([sys.executable, "-m", "publishing.cli", "pdf", *args], capture_output=True,
                          text=True, cwd=cwd)


def make(path, sizes=((200, 100),), **meta):
    """A PDF whose page i has width sizes[i][0]: the width tells the pages apart."""
    w = PdfWriter()
    for width, height in sizes:
        w.add_blank_page(width, height)
    if meta:
        w.add_metadata(meta)
    with open(path, "wb") as f:
        w.write(f)
    return path


def widths(path):
    return [int(p.mediabox.width) for p in PdfReader(str(path)).pages]


def action(subtype, **extra):
    d = DictionaryObject({NameObject("/S"): NameObject(subtype)})
    d.update({NameObject(k): TextStringObject(v) for k, v in extra.items()})
    return d


def annotated(path):
    """One page with: a URI link, a JavaScript link, a launch link, a widget, a file attachment."""
    w = PdfWriter()
    page = w.add_blank_page(300, 200)
    rect = ArrayObject([NumberObject(0), NumberObject(0), NumberObject(10), NumberObject(10)])

    def annot(subtype, **kw):
        a = DictionaryObject({NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject(subtype),
                              NameObject("/Rect"): rect})
        a.update({NameObject(k): v for k, v in kw.items()})
        return w._add_object(a)

    page[NameObject("/Annots")] = ArrayObject([
        annot("/Link", **{"/A": action("/URI", **{"/URI": "https://example.com/"})}),
        annot("/Link", **{"/A": action("/JavaScript", **{"/JS": "app.alert(1)"})}),
        annot("/Link", **{"/A": action("/Launch", **{"/F": "calc.exe"})}),
        annot("/Widget"),
        annot("/FileAttachment"),
    ])
    page[NameObject("/AA")] = DictionaryObject({NameObject("/O"): action("/JavaScript", **{"/JS": "x"})})
    w.add_js("app.alert('doc')")
    w.add_attachment("secret.txt", b"secret")
    w.add_metadata({"/Title": "Private Title", "/Author": "Jane Roe"})
    w.add_outline_item("Chapter", 0)
    with open(path, "wb") as f:
        w.write(f)
    return path


# --- merge ------------------------------------------------------------------------------------

def test_merge_joins_in_order(tmp_path):
    a = make(tmp_path / "a.pdf", [(101, 50), (102, 50)])
    b = make(tmp_path / "b.pdf", [(103, 50)])
    out = pdftools.merge([b, a], tmp_path / "o.pdf")
    assert widths(out) == [103, 101, 102]


def test_merge_needs_two(tmp_path):
    a = make(tmp_path / "a.pdf")
    with pytest.raises(pdftools.UsageError):
        pdftools.merge([a], tmp_path / "o.pdf")


# --- pages ------------------------------------------------------------------------------------

@pytest.fixture
def five(tmp_path):
    return make(tmp_path / "five.pdf", [(101 + i, 50) for i in range(5)])


@pytest.mark.parametrize("spec,expected", [
    ("1", [101]), ("2-3", [102, 103]), ("4-", [104, 105]), ("-2", [101, 102]),
    ("5,1-2", [105, 101, 102]), ("1,1", [101, 101]),
])
def test_pages_selects(five, tmp_path, spec, expected):
    assert widths(pdftools.pages(five, tmp_path / "o.pdf", select=spec)) == expected


@pytest.mark.parametrize("spec", ["0", "3-2", "x", "", "1;2", "-"])
def test_pages_bad_range_is_usage(five, tmp_path, spec):
    with pytest.raises(pdftools.UsageError):
        pdftools.pages(five, tmp_path / "o.pdf", select=spec)
    assert not (tmp_path / "o.pdf").exists()


def test_pages_past_the_end_is_refused(five, tmp_path):
    with pytest.raises(pdftools.PdfError, match="has 5 pages"):
        pdftools.pages(five, tmp_path / "o.pdf", select="4-9")
    assert not (tmp_path / "o.pdf").exists()


# --- strip and cleaning -----------------------------------------------------------------------

def test_strip_drops_metadata_outline_js_and_attachments(tmp_path):
    src = annotated(tmp_path / "in.pdf")
    out = pdftools.strip(src, tmp_path / "o.pdf")
    raw = out.read_bytes()
    for needle in (b"Private Title", b"Jane Roe", b"app.alert", b"secret", b"Chapter", b"calc.exe", b"/JavaScript",
                   b"/EmbeddedFile", b"/Launch"):
        assert needle not in raw, needle
    r = PdfReader(str(out))
    assert len(r.pages) == 1 and not r.outline and not r.attachments
    assert dict(r.metadata) == {"/Producer": pdftools.PRODUCER}
    assert "/AA" not in r.pages[0]


def test_strip_keeps_plain_links_only(tmp_path):
    out = pdftools.strip(annotated(tmp_path / "in.pdf"), tmp_path / "o.pdf")
    annots = [a.get_object() for a in PdfReader(str(out)).pages[0]["/Annots"]]
    assert [str(a["/Subtype"]) for a in annots] == ["/Link"]
    assert str(annots[0]["/A"]["/URI"]) == "https://example.com/"


def test_merge_and_pages_clean_too(tmp_path):
    src = annotated(tmp_path / "in.pdf")
    other = make(tmp_path / "b.pdf")
    for out in (pdftools.merge([src, other], tmp_path / "m.pdf"), pdftools.pages(src, tmp_path / "p.pdf", select="1")):
        raw = out.read_bytes()
        assert b"/JavaScript" not in raw and b"Private Title" not in raw and b"secret" not in raw


def test_deterministic(tmp_path):
    src = annotated(tmp_path / "in.pdf")
    a = pdftools.strip(src, tmp_path / "a.pdf")
    b = pdftools.strip(src, tmp_path / "b.pdf")
    assert a.read_bytes() == b.read_bytes()


# --- refusals and limits ----------------------------------------------------------------------

def test_never_overwrites(five, tmp_path):
    (tmp_path / "o.pdf").write_bytes(b"mine")
    with pytest.raises(pdftools.UsageError, match="never overwrite"):
        pdftools.strip(five, tmp_path / "o.pdf")
    assert (tmp_path / "o.pdf").read_bytes() == b"mine"


def test_refuses_what_is_not_a_local_pdf(tmp_path):
    (tmp_path / "x.txt").write_text("hi")
    (tmp_path / "fake.pdf").write_text("not a pdf at all")
    for bad in ("https://example.com/a.pdf", "/dev/null", "-", tmp_path / "x.txt", tmp_path / "missing.pdf"):
        with pytest.raises(pdftools.UsageError):
            pdftools.strip(bad, tmp_path / "o.pdf")
    with pytest.raises(pdftools.PdfError, match="not a PDF"):
        pdftools.strip(tmp_path / "fake.pdf", tmp_path / "o.pdf")
    with pytest.raises(pdftools.UsageError):
        pdftools.strip(make(tmp_path / "a.pdf"), tmp_path / "o.txt")
    assert not (tmp_path / "o.pdf").exists()


def test_refuses_encrypted(tmp_path):
    w = PdfWriter()
    w.add_blank_page(100, 100)
    w.encrypt("pw")
    with open(tmp_path / "enc.pdf", "wb") as f:
        w.write(f)
    with pytest.raises(pdftools.PdfError, match="encrypted"):
        pdftools.strip(tmp_path / "enc.pdf", tmp_path / "o.pdf")


def test_refuses_damaged(tmp_path):
    (tmp_path / "bad.pdf").write_bytes(b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\n")
    with pytest.raises(pdftools.PdfError):
        pdftools.strip(tmp_path / "bad.pdf", tmp_path / "o.pdf")
    assert not (tmp_path / "o.pdf").exists()


def test_page_cap(five, tmp_path):
    with pytest.raises(pdftools.PdfError, match="over 3 pages"):
        pdftools.strip(five, tmp_path / "o.pdf", max_pages=3)
    assert not (tmp_path / "o.pdf").exists()


def test_input_and_output_caps(five, tmp_path):
    with pytest.raises(pdftools.PdfError, match="input is over"):
        pdftools.strip(five, tmp_path / "o.pdf", max_input_bytes=100)
    with pytest.raises(pdftools.PdfError, match="output is"):
        pdftools.strip(five, tmp_path / "o.pdf", max_bytes=100)
    assert not (tmp_path / "o.pdf").exists()
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith("publishing-pdf-")] == []


def test_timeout_kills_the_child(five, tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(pdftools, "_open", lambda *a, **k: time.sleep(30))
    t = time.monotonic()
    with pytest.raises(pdftools.PdfError, match="timed out"):
        pdftools.strip(five, tmp_path / "o.pdf", timeout=0.5)
    assert time.monotonic() - t < 10 and not (tmp_path / "o.pdf").exists()


# --- the command ------------------------------------------------------------------------------

def test_cli_pages_prints_the_path(five, tmp_path):
    r = cli("pages", str(five), "--select", "2-3", "-o", str(tmp_path / "o.pdf"))
    assert r.returncode == 0 and r.stdout.strip() == str(tmp_path / "o.pdf") and r.stderr == ""
    assert widths(tmp_path / "o.pdf") == [102, 103]


def test_cli_merge(tmp_path):
    a, b = make(tmp_path / "a.pdf"), make(tmp_path / "b.pdf", [(300, 100)])
    r = cli("merge", str(a), str(b), "-o", str(tmp_path / "o.pdf"))
    assert r.returncode == 0 and widths(tmp_path / "o.pdf") == [200, 300]


@pytest.mark.parametrize("args,code", [
    (["strip", "missing.pdf", "-o", "o.pdf"], 2),
    (["pages", "{five}", "--select", "9", "-o", "o.pdf"], 1),
    (["pages", "{five}", "--select", "0", "-o", "o.pdf"], 2),
    (["strip", "{five}", "-o", "o.png"], 2),
])
def test_cli_exit_codes(five, tmp_path, args, code):
    r = cli(*[a.format(five=five) for a in args], cwd=tmp_path)
    assert r.returncode == code and r.stdout == "" and r.stderr.startswith("publishing:")
