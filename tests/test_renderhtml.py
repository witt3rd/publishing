"""`publishing render-html`, `render-md` and `pdf-pages`: the render entry for services.

The hostile fixtures (an external fetch, a file read, a huge page, a loop, a meta refresh, hostile
PDFs) run through the command a service calls, with page images and a thumbnail asked for, and
prove the safe default holds there: nothing reaches the network or a file outside the folder, every
limit stops the call, and a refused call writes nothing. The golden checks pin page counts, words,
image names and sizes, and that the same source gives the same image bytes.
"""
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from publishing import pdf
from publishing.cli import main
from publishing.renderhtml import NotReady, RenderError, UsageError, pdf_pages, render
from publishing.usercontent import Limits

MARKER = "EXFILTRATED-MARKER"
REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def server():
    """A local HTTP server that records every request it gets: any hit is a leak."""
    hits = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            body = f"body::after {{ content: '{MARKER}' }}".encode()
            self.send_response(200)
            self.send_header("content-type", "text/css")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", hits
    srv.shutdown()


def page(folder: Path, body: str, head: str = "", name: str = "index.html") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / name
    f.write_text(f'<!doctype html><html><head><meta charset="utf-8">{head}</head><body>{body}</body></html>')
    return f


def cli(capsys, *args) -> tuple[int, dict | str, str]:
    """Run the command in-process; returns (exit code, the --json result or stdout, stderr)."""
    code = main(list(args))
    out, err = capsys.readouterr()
    return code, (json.loads(out) if "--json" in args and code == 0 else out), err


def nothing_written(*paths: Path) -> bool:
    return all(not p.exists() or (p.is_dir() and not any(p.iterdir())) for p in paths)


# ---------------------------------------------------------------- the hostile fixtures, through the entry

def test_an_external_fetch_is_refused_and_the_outputs_are_still_made(tmp_path, server, capsys):
    url, hits = server
    src = page(tmp_path / "doc", f"""<p>Visible text.</p><img src="{url}/img.png">
        <iframe src="{url}/frame"></iframe><div style="background:url({url}/bg.png)">bg</div>
        <script src="{url}/script.js"></script>""",
               head=f'<link rel="stylesheet" href="{url}/style.css"><style>@import url("{url}/import.css");</style>')
    out = tmp_path / "out"
    code, r, _ = cli(capsys, "render-html", str(src), "--pdf", str(out / "page.pdf"), "--png", str(out / "img"),
                     "--thumbnail", "200", "--json")
    time.sleep(0.5)
    assert code == 0 and hits == []
    assert r["mode"] == "user-content" and r["sandboxed"] is True
    assert {f"{url}/img.png", f"{url}/style.css"} <= set(r["blocked"])
    text = pdf.text(out / "page.pdf")
    assert "Visible text." in text and MARKER not in text
    assert [Path(p).name for p in r["images"]] == ["page-001.png"] and Path(r["thumbnail"]).name == "thumbnail.png"


def test_markdown_cannot_fetch_either(tmp_path, server, capsys):
    url, hits = server
    doc = tmp_path / "doc"
    doc.mkdir()
    (doc / "memo.md").write_text(f"# Memo\n\nText.\n\n![remote]({url}/fig.png)\n\n"
                                 f'<link rel="stylesheet" href="{url}/style.css">\n\n'
                                 f'<iframe src="{url}/frame"></iframe>\n')
    code, r, _ = cli(capsys, "render-md", str(doc / "memo.md"), "--pdf", str(tmp_path / "memo.pdf"), "--json")
    time.sleep(0.5)
    assert code == 0 and hits == [] and r["sandboxed"] is True
    assert f"{url}/fig.png" in r["blocked"] and MARKER not in pdf.text(tmp_path / "memo.pdf")


def test_files_outside_the_folder_are_not_read(tmp_path, capsys):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text(MARKER)
    (outside / "secret.css").write_text(f"body::after {{ content: '{MARKER}-css' }}")
    (outside / "secret.svg").write_text(f'<svg xmlns="http://www.w3.org/2000/svg"><text y="20">{MARKER}</text></svg>')
    doc = tmp_path / "doc"
    doc.mkdir()
    (doc / "leak.css").symlink_to(outside / "secret.css")
    src = page(doc, f"""<p>Visible text.</p>
        <iframe src="file:///etc/passwd"></iframe><iframe src="{(outside / 'secret.txt').as_uri()}"></iframe>
        <iframe src="../outside/secret.txt"></iframe><img src="../outside/secret.svg">""",
               head='<link rel="stylesheet" href="leak.css"><link rel="stylesheet" href="../outside/secret.css">')
    code, _, _ = cli(capsys, "render-html", str(src), "--pdf", str(tmp_path / "a.pdf"), "--png", str(tmp_path / "img"))
    assert code == 0
    text = pdf.text(tmp_path / "a.pdf")
    assert "Visible text." in text and MARKER not in text and "root:" not in text
    (doc / "memo.md").write_text("# Memo\n\nText.\n\n![figure](../outside/secret.svg)\n\n"
                                 '<iframe src="file:///etc/passwd"></iframe>\n')
    assert cli(capsys, "render-md", str(doc / "memo.md"), "--pdf", str(tmp_path / "m.pdf"))[0] == 0
    text = pdf.text(tmp_path / "m.pdf")  # the trusted build would inline the SVG from outside
    assert "Text." in text and MARKER not in text and "root:" not in text


def test_a_huge_page_stops_at_the_page_limit_and_writes_nothing(tmp_path, capsys):
    src = page(tmp_path / "doc", '<div style="height:10000000px">tall</div>')
    out, img = tmp_path / "out.pdf", tmp_path / "img"
    code, _, err = cli(capsys, "render-html", str(src), "--pdf", str(out), "--png", str(img), "--thumbnail", "100",
                       "--max-pages", "20")
    assert code == 1 and "page limit" in err
    assert nothing_written(out, img)
    src = page(tmp_path / "doc2", "".join(f'<p style="break-before:page">Page {i}.</p>' for i in range(8)))
    code, _, err = cli(capsys, "render-html", str(src), "--pdf", str(out), "--png", str(img), "--max-pages", "5")
    assert code == 1 and "over the page limit of 5" in err and nothing_written(out, img)


def test_a_loop_does_not_run_and_with_script_allowed_hits_the_time_limit(tmp_path, capsys):
    src = page(tmp_path / "doc", "<p>Original text.</p><script>document.body.innerHTML = 'JS RAN';</script>"
               "<script>while (true) {}</script>")
    t = time.monotonic()
    assert cli(capsys, "render-html", str(src), "--pdf", str(tmp_path / "a.pdf"), "--timeout", "20")[0] == 0
    assert time.monotonic() - t < 20
    assert "Original text." in pdf.text(tmp_path / "a.pdf") and "JS RAN" not in pdf.text(tmp_path / "a.pdf")
    t = time.monotonic()
    code, _, err = cli(capsys, "render-html", str(src), "--pdf", str(tmp_path / "b.pdf"), "--png",
                       str(tmp_path / "img"), "--allow-js", "--timeout", "4")
    assert code == 1 and "time limit" in err and time.monotonic() - t < 15
    assert nothing_written(tmp_path / "b.pdf", tmp_path / "img")


@pytest.mark.parametrize("target", ["{url}/refresh", "file:///etc/passwd", "elsewhere.html"])
def test_a_meta_refresh_is_not_followed(tmp_path, server, capsys, target):
    url, hits = server
    doc = tmp_path / "doc"
    page(doc, "<p>Other page.</p>", name="elsewhere.html")
    refresh = f'<meta http-equiv="refresh" content="0; url={target.format(url=url)}">'
    src = page(doc, "<p>Original page.</p>", head=refresh)
    code, r, _ = cli(capsys, "render-html", str(src), "--pdf", str(tmp_path / "a.pdf"), "--thumbnail", "120", "--json")
    time.sleep(0.5)
    assert code == 0 and hits == [] and r["blocked"]
    text = pdf.text(tmp_path / "a.pdf")
    assert "Original page." in text and "Other page." not in text and "root:" not in text


def test_the_whole_call_keeps_one_time_budget(tmp_path):
    """--timeout covers the render and the images: a budget spent in the render leaves the images none."""
    src = page(tmp_path / "doc", "<p>Text.</p>")
    with pytest.raises(RenderError, match="time limit"):
        render(src, png=tmp_path / "img", limits=Limits(timeout=0.05))
    doc = tmp_path / "md"
    doc.mkdir()
    (doc / "memo.md").write_text("# Memo\n\n" + "Text. " * 1000)
    with pytest.raises(RenderError, match="time limit"):
        render(doc / "memo.md", png=tmp_path / "img2", limits=Limits(timeout=0.05))
    assert nothing_written(tmp_path / "img", tmp_path / "img2", doc / "memo.pdf")


def test_input_bytes_are_capped(tmp_path):
    src = page(tmp_path / "doc", "<p>" + "x" * 200_000 + "</p>")
    with pytest.raises(RenderError, match="input limit") as e:
        render(src, limits=Limits(max_bytes=100_000))
    assert e.value.exit_code == 1 and not src.with_suffix(".pdf").exists()


# ---------------------------------------------------------------- hostile PDFs (pdf-pages)

def _blank_pdf(path: Path, pages: int, width: float = 612, height: float = 792) -> Path:
    from pypdf import PdfWriter

    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=width, height=height)
    with open(path, "wb") as f:
        w.write(f)
    return path


def test_pdf_pages_refuses_hostile_pdfs_and_writes_nothing(tmp_path, capsys):
    img = tmp_path / "img"
    (tmp_path / "not-a-pdf.pdf").write_text("<html>not a pdf</html>")
    (tmp_path / "truncated.pdf").write_bytes(_blank_pdf(tmp_path / "t.pdf", 2).read_bytes()[:200])
    _blank_pdf(tmp_path / "gigapixel.pdf", 1, width=1, height=14400)  # a sliver: 1400 x 20 million px
    _blank_pdf(tmp_path / "many-pages.pdf", 301)
    for name in ("not-a-pdf.pdf", "truncated.pdf", "gigapixel.pdf", "many-pages.pdf"):
        src = tmp_path / name
        code, _, err = cli(capsys, "pdf-pages", str(src), "--png", str(img), "--thumbnail", "100")
        assert code == 1, (name, err)
        assert nothing_written(img), name
    assert "pixel limit" in cli(capsys, "pdf-pages", str(tmp_path / "gigapixel.pdf"), "--png", str(img))[2]
    assert "page limit" in cli(capsys, "pdf-pages", str(tmp_path / "many-pages.pdf"), "--png", str(img))[2]
    big = _blank_pdf(tmp_path / "big.pdf", 3)
    code, _, err = cli(capsys, "pdf-pages", str(big), "--png", str(img), "--max-bytes", "100")
    assert code == 1 and "input limit" in err and nothing_written(img)


def test_pdf_pages_draws_every_page_and_a_thumbnail(tmp_path, capsys):
    src = _blank_pdf(tmp_path / "three.pdf", 3)
    code, r, _ = cli(capsys, "pdf-pages", str(src), "--png", str(tmp_path / "img"), "--width", "300",
                     "--thumbnail", "64", "--json")
    assert code == 0 and r["pages"] == 3 and r["pdf"] is None and r["netns"] in (True, False)
    assert sorted(p.name for p in (tmp_path / "img").iterdir()) == ["page-001.png", "page-002.png", "page-003.png",
                                                                      "thumbnail.png"]
    assert Image.open(tmp_path / "img" / "page-002.png").size == (300, 389)
    assert Image.open(tmp_path / "img" / "thumbnail.png").width == 64
    # a thumbnail alone lands beside the PDF
    assert cli(capsys, "pdf-pages", str(src), "--thumbnail", "64")[0] == 0
    assert (tmp_path / "three.thumbnail.png").is_file()


# ---------------------------------------------------------------- golden text, page counts, names

def test_golden_pages_text_names_and_sizes(tmp_path, capsys):
    words = ["Alpha golden", "Bravo golden", "Charlie golden"]
    src = page(tmp_path / "doc", "".join(f'<h1 style="break-before:page">{w}</h1>' for w in words),
               head="<style>@page { size: 8.5in 11in; margin: 1in }</style>")
    out = tmp_path / "out"
    code, r, _ = cli(capsys, "render-html", str(src), "--pdf", str(out / "x.pdf"), "--png", str(out / "img"),
                     "--thumbnail", "240", "--json")
    assert code == 0 and r["pages"] == 3 and pdf.pages(out / "x.pdf") == 3
    assert pdf.text(out / "x.pdf") == " ".join(words)
    assert [Path(p).name for p in r["images"]] == ["page-001.png", "page-002.png", "page-003.png"]
    assert all(Image.open(p).size == (1400, 1812) for p in r["images"])
    assert Image.open(r["thumbnail"]).size == (240, 311)
    # the same source gives the same image bytes (the PDF's own bytes differ run to run)
    again = tmp_path / "again"
    assert cli(capsys, "render-html", str(src), "--png", str(again), "--thumbnail", "240")[0] == 0
    for name in ("page-001.png", "page-002.png", "page-003.png", "thumbnail.png"):
        assert (again / name).read_bytes() == (out / "img" / name).read_bytes(), name
    assert not src.with_suffix(".pdf").exists()  # --png alone writes no PDF


def test_the_default_output_is_the_pdf_beside_the_source(tmp_path, capsys):
    src = page(tmp_path / "doc", "<p>Hello from a person.</p>")
    code, out, _ = cli(capsys, "render-html", str(src), "--thumbnail", "100")
    assert code == 0
    assert out.split() == [str(src.with_suffix(".pdf")), str(src.with_suffix(".thumbnail.png"))]
    assert "Hello from a person." in pdf.text(src.with_suffix(".pdf"))


@pytest.mark.parametrize("sample", ["house-style-memo-v1/memo.md", "house-style-document-v1/document.md"])
def test_render_md_matches_the_committed_samples(tmp_path, capsys, sample):
    """Markdown in user-content mode makes the house memo and document: the same words and pages as the
    samples the trusted build committed (the document fills its contents' page numbers)."""
    src = REPO / "docs" / "samples" / sample
    out = tmp_path / "s.pdf"
    fmt = "document" if sample.endswith("document.md") else "memo"
    code, r, _ = cli(capsys, "render-md", str(src), "--format", fmt, "--pdf", str(out), "--thumbnail", "300", "--json")
    assert code == 0 and r["sandboxed"] is True
    assert pdf.same(out, src.parent.with_suffix(".pdf"))
    assert Image.open(r["thumbnail"]).width == 300


# ---------------------------------------------------------------- the contract: modes, overwrite, codes

def test_nothing_is_ever_overwritten(tmp_path, capsys):
    src = page(tmp_path / "doc", "<p>Text.</p>")
    (tmp_path / "taken.pdf").write_text("keep")
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "page-001.png").write_text("keep")
    for args in (["--pdf", str(tmp_path / "taken.pdf")], ["--png", str(tmp_path / "img")],
                 ["--pdf", str(tmp_path / "new.pdf"), "--png", str(tmp_path / "img")]):
        code, _, err = cli(capsys, "render-html", str(src), *args)
        assert code == 2 and "never overwrite" in err, args
    assert (tmp_path / "taken.pdf").read_text() == "keep" and not (tmp_path / "new.pdf").exists()
    assert sorted(p.name for p in (tmp_path / "img").iterdir()) == ["page-001.png"]
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "unrelated.txt").write_text("a folder may hold other files")
    assert cli(capsys, "render-html", str(src), "--png", str(tmp_path / "other"))[0] == 0


def test_usage_errors_exit_2(tmp_path, capsys):
    src = page(tmp_path / "doc", "<p>Text.</p>")
    md = tmp_path / "doc" / "memo.md"
    md.write_text("# Memo\n")
    for args in (["render-html", str(tmp_path / "missing.html")], ["render-html", str(md)],
                 ["render-md", str(src)], ["pdf-pages", str(src), "--png", str(tmp_path / "i")],
                 ["pdf-pages", str(_blank_pdf(tmp_path / "x.pdf", 1))],  # nothing asked for
                 ["render-html", str(src), "--thumbnail", "5000"]):
        code, _, err = cli(capsys, *args)
        assert code == 2, (args, err)
    for args in (["render-html", str(src), "--width", "0"], ["render-html", str(src), "--timeout", "-1"]):
        with pytest.raises(SystemExit) as e:
            main(args)
        assert e.value.code == 2
    with pytest.raises(UsageError):
        render(src, fmt="memo")  # a format is for markdown


def test_trusted_mode_is_explicit_and_refused_in_a_service(tmp_path, capsys, monkeypatch):
    """--trusted is the house build's renderer: it reads file:// (why it is never for user content),
    and a service's image (PUBLISHING_USER_CONTENT=1) refuses it."""
    (tmp_path / "local.css").write_text(f"body::after {{ content: '{MARKER}' }}")
    link = f'<link rel="stylesheet" href="{(tmp_path / "local.css").as_uri()}">'
    src = page(tmp_path / "doc", "<p>House page.</p>", head=link)
    code, r, _ = cli(capsys, "render-html", str(src), "--trusted", "--pdf", str(tmp_path / "t.pdf"), "--json")
    assert code == 0 and r["mode"] == "trusted" and r["sandboxed"] is False
    assert MARKER in pdf.text(tmp_path / "t.pdf")
    code, r, _ = cli(capsys, "render-html", str(src), "--pdf", str(tmp_path / "u.pdf"), "--json")
    assert code == 0 and r["mode"] == "user-content" and MARKER not in pdf.text(tmp_path / "u.pdf")
    monkeypatch.setenv("PUBLISHING_USER_CONTENT", "1")
    code, _, err = cli(capsys, "render-html", str(src), "--trusted", "--pdf", str(tmp_path / "v.pdf"))
    assert code == 2 and "PUBLISHING_USER_CONTENT" in err and not (tmp_path / "v.pdf").exists()


def test_the_function_raises_with_the_commands_exit_codes(tmp_path):
    with pytest.raises(UsageError) as e:
        pdf_pages(tmp_path / "x.txt", png=tmp_path)
    assert e.value.exit_code == 2
    assert NotReady.exit_code == 3 and RenderError.exit_code == 1
    r = render(page(tmp_path / "doc", "<p>Text.</p>"), pdf=tmp_path / "a.pdf", thumbnail=50)
    assert r.written() == [tmp_path / "a.pdf", tmp_path / "a.thumbnail.png"] and r.pages == 1


@pytest.mark.skipif(not shutil.which("bwrap"), reason="no bwrap to take user namespaces away")
def test_no_sandbox_means_no_render_and_exit_3(tmp_path, no_core_dump):
    src = page(tmp_path / "doc", "<p>Text.</p>")
    p = subprocess.run(["bwrap", "--dev-bind", "/", "/", "--unshare-user", "--disable-userns",
                        sys.executable, "-m", "publishing.cli", "render-html", str(src), "--png", str(tmp_path / "i")],
                       capture_output=True, text=True, timeout=120, preexec_fn=no_core_dump)
    assert p.returncode == 3 and "did not launch it" in p.stderr, p.stderr  # refused before Chromium starts
    assert nothing_written(tmp_path / "i") and not src.with_suffix(".pdf").exists()


def test_the_render_profile_is_named_when_it_is_missing(tmp_path):
    from publishing.cli import RENDER_MODULES

    blocker = tmp_path / "blocker"
    for name in RENDER_MODULES:
        (blocker / name).mkdir(parents=True)
        message = f"No module named {name!r}"
        (blocker / name / "__init__.py").write_text(f"raise ModuleNotFoundError({message!r}, name={name!r})")
    for cmd in (["render-html", "a.html"], ["render-md", "a.md"], ["pdf-pages", "a.pdf", "--png", "i"]):
        r = subprocess.run([sys.executable, "-m", "publishing.cli", *cmd], capture_output=True, text=True,
                           cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(blocker)})
        assert r.returncode == 3 and "publishing[render]" in r.stderr, (cmd, r.stderr)


def test_an_output_that_appears_mid_placement_undoes_the_rest(tmp_path):
    """A file created between the check and the copy is never overwritten, and what was placed is removed."""
    from publishing import renderhtml
    from publishing.raster import Images

    stage = tmp_path / "stage"
    stage.mkdir()
    for n in ("out.pdf", "page-001.png", "page-002.png"):
        (stage / n).write_text(n)
    out = tmp_path / "out"
    out.mkdir()
    (out / "page-002.png").write_text("someone else's")
    images = Images(pages=2, files=[stage / "page-001.png", stage / "page-002.png"], thumbnail=None, netns=False)
    result = renderhtml.Rendered("user-content", 2)
    with pytest.raises(UsageError, match="never overwrite"):
        renderhtml._place(result, stage / "out.pdf", tmp_path / "x.pdf", images, out, None)
    assert not (tmp_path / "x.pdf").exists() and not (out / "page-001.png").exists()
    assert (out / "page-002.png").read_text() == "someone else's"
