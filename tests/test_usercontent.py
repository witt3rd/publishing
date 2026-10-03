"""User-content mode: hostile pages must not reach the network, read files outside their folder,
run script, follow a refresh, or run past the size, page, time and memory limits.

Each test builds its hostile fixture in a temporary folder and renders it through the same entry
a service uses (`render_html`, the `publishing html` command, or a build in user-content mode).
"""
import http.server
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from publishing import pdf
from publishing.build import BuildError, build, resolve
from publishing.cli import main
from publishing.config import load
from publishing.usercontent import Limits, UserContentError, UserContentRenderer, child_env, render_html, sandboxed

MARKER = "EXFILTRATED-MARKER"


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


def test_external_fetches_are_blocked(tmp_path, server):
    url, hits = server
    src = page(tmp_path / "doc", f"""
        <p>Visible text.</p>
        <img src="{url}/img.png"><img srcset="{url}/srcset.png 2x">
        <picture><source srcset="{url}/picture.png"><img src="x.png"></picture>
        <iframe src="{url}/frame"></iframe><object data="{url}/object"></object><embed src="{url}/embed">
        <video poster="{url}/poster.png"></video><audio src="{url}/audio.mp3"></audio>
        <div style="background:url({url}/bg.png)">bg</div>
        <script src="{url}/script.js"></script>
        <svg><image href="{url}/svg-image.png" width="10" height="10"/></svg>
    """, head=f"""
        <link rel="stylesheet" href="{url}/style.css">
        <link rel="preload" as="image" href="{url}/preload.png"><link rel="prefetch" href="{url}/prefetch">
        <link rel="icon" href="{url}/favicon.ico">
        <style>@import url("{url}/import.css"); @font-face {{ font-family: X; src: url({url}/font.woff2); }}
               p {{ font-family: X; }}</style>
    """)
    out = tmp_path / "out.pdf"
    result = render_html(src, out)
    assert hits == []
    assert any(u.startswith(url) for u in result.blocked)
    assert "Visible text." in pdf.text(out) and MARKER not in pdf.text(out)


def test_the_request_filter_alone_blocks_the_network(tmp_path, server, monkeypatch):
    """With the CSP header and the network namespace both off, the request filter still refuses all."""
    from publishing import usercontent

    url, hits = server
    monkeypatch.setattr(usercontent, "netns_available", lambda: False)
    src = page(tmp_path / "doc", f'<p>Text.</p><img src="{url}/img.png"><iframe src="{url}/frame"></iframe>'
               f'<script>fetch("{url}/fetch"); new WebSocket("{url.replace("http", "ws")}/ws");</script>',
               head=f'<link rel="stylesheet" href="{url}/style.css">'
               f'<meta http-equiv="refresh" content="0; url={url}/r">')
    result, _ = usercontent._render(src, src.parent, "/doc/index.html", kind="html", paper="letter",
                                    limits=Limits(allow_js=True), csp=False)
    time.sleep(0.5)
    assert hits == [] and result.netns is False
    assert {f"{url}/img.png", f"{url}/frame", f"{url}/style.css", f"{url}/fetch", f"{url}/r"} <= set(result.blocked)


def test_a_base_href_cannot_point_the_page_at_the_network(tmp_path, server):
    url, hits = server
    src = page(tmp_path / "doc", '<p>Text.</p><img src="relative.png">', head=f'<base href="{url}/">'
               '<link rel="stylesheet" href="style.css">')
    render_html(src, tmp_path / "out.pdf")
    assert hits == []


def test_files_outside_the_folder_are_not_read(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text(MARKER)
    (outside / "secret.css").write_text(f"body::after {{ content: '{MARKER}-css' }}")
    (outside / "secret.svg").write_text(f'<svg xmlns="http://www.w3.org/2000/svg"><text y="20">{MARKER}</text></svg>')
    doc = tmp_path / "doc"
    doc.mkdir()
    (doc / "leak.txt").symlink_to(outside / "secret.txt")
    (doc / "leak.css").symlink_to(outside / "secret.css")
    (doc / ".env.css").write_text(f"body::after {{ content: '{MARKER}-hidden' }}")
    (doc / "ok.css").write_text("body::before { content: 'ALLOWED-IN-FOLDER' }")
    src = page(doc, f"""
        <p>Visible text.</p>
        <iframe src="file:///etc/passwd"></iframe><iframe src="{(outside / 'secret.txt').as_uri()}"></iframe>
        <iframe src="../outside/secret.txt"></iframe><iframe src="leak.txt"></iframe>
        <object data="file:///etc/passwd"></object><embed src="../outside/secret.svg">
        <img src="../outside/secret.svg"><img src="{(outside / 'secret.svg').as_uri()}">
        <a href="file:///etc/passwd">a link is not a fetch</a>
    """, head=f"""
        <link rel="stylesheet" href="ok.css">
        <link rel="stylesheet" href="{(outside / 'secret.css').as_uri()}">
        <link rel="stylesheet" href="../outside/secret.css"><link rel="stylesheet" href="leak.css">
        <link rel="stylesheet" href=".env.css"><link rel="stylesheet" href="%2e%2e/outside/secret.css">
    """)
    out = tmp_path / "out.pdf"
    render_html(src, out)
    text = pdf.text(out)
    assert "ALLOWED-IN-FOLDER" in text and "Visible text." in text  # the folder itself still works
    assert MARKER not in text and "root:" not in text


def test_a_user_content_build_reads_nothing_outside_its_folder(repo):
    (repo / "outside.svg").write_text(f'<svg xmlns="http://www.w3.org/2000/svg"><text y="20">{MARKER}</text></svg>')
    folder = repo / "docs" / "notes" / "memo-v1"
    assert main(["new", str(folder), "--format", "memo"]) == 0
    (folder / "memo.md").write_text("# Memo\n\nText.\n\n![figure](../../../outside.svg)\n")
    cfg = load(folder)
    s = resolve(folder, cfg)
    with UserContentRenderer() as r, pytest.raises(BuildError, match="image not found: ../../../outside.svg"):
        build(s, cfg, r)  # not inlined, and its fetch refused: the trusted build would inline it
    assert not s.pdf.exists()
    (folder / "memo.md").write_text('# Memo\n\nText.\n\n<iframe src="file:///etc/passwd"></iframe>\n\n'
                                    '<link rel="stylesheet" href="file:///etc/passwd">\n')
    with UserContentRenderer() as r:
        assert build(s, cfg, r) == "built"
    assert "Text." in pdf.text(s.pdf) and "root:" not in pdf.text(s.pdf)


def test_a_huge_page_stops_at_the_page_limit(tmp_path):
    src = page(tmp_path / "doc", '<div style="height:10000000px">tall</div>')
    out = tmp_path / "out.pdf"
    with pytest.raises(UserContentError, match="page limit"):
        render_html(src, out, limits=Limits(max_pages=20))
    assert not out.exists()
    src = page(tmp_path / "doc2", "".join(f"<p>Paragraph {i}.</p>" for i in range(3000)))
    with pytest.raises(UserContentError, match="page limit"):
        render_html(src, out, limits=Limits(max_pages=20))
    src = page(tmp_path / "doc3", "".join(f'<p style="break-before:page">Page {i}.</p>' for i in range(8)))
    with pytest.raises(UserContentError, match="over the page limit of 5"):  # short on screen, 8 pages in print
        render_html(src, out, limits=Limits(max_pages=5))
    assert not out.exists()
    assert render_html(src, out, limits=Limits(max_pages=8)).pages == 8


def test_input_bytes_are_capped(tmp_path):
    src = page(tmp_path / "doc", "<p>" + "x" * 200_000 + "</p>")
    with pytest.raises(UserContentError, match="input limit"):
        render_html(src, tmp_path / "out.pdf", limits=Limits(max_bytes=100_000))
    doc = tmp_path / "doc2"
    src = page(doc, '<p>Small page, big picture.</p><img src="big.png">')
    (doc / "big.png").write_bytes(b"\x89PNG" + b"\0" * 300_000)
    with pytest.raises(UserContentError, match="input limit"):
        render_html(src, tmp_path / "out.pdf", limits=Limits(max_bytes=100_000))
    assert not (tmp_path / "out.pdf").exists()


def test_script_does_not_run_by_default(tmp_path):
    src = page(tmp_path / "doc", "<p>Original text.</p><script>document.body.innerHTML = 'JS RAN';</script>"
               "<script>while (true) {}</script>")
    out = tmp_path / "out.pdf"
    t = time.monotonic()
    render_html(src, out, limits=Limits(timeout=20))
    assert time.monotonic() - t < 20
    assert "Original text." in pdf.text(out) and "JS RAN" not in pdf.text(out)


def test_an_infinite_loop_with_script_allowed_hits_the_time_limit(tmp_path):
    src = page(tmp_path / "doc", "<p>Loop.</p><script>while (true) {}</script>")
    out = tmp_path / "out.pdf"
    t = time.monotonic()
    with pytest.raises(UserContentError, match="time limit"):
        render_html(src, out, limits=Limits(timeout=4, allow_js=True))
    assert time.monotonic() - t < 15
    assert not out.exists()


def test_a_memory_bomb_hits_the_memory_limit(tmp_path):
    src = page(tmp_path / "doc", "<p>Bomb.</p><script>const a = []; while (true) a.push(new Array(1e6).fill(1.5));"
               "</script>")
    with pytest.raises(UserContentError, match="memory limit|crashed"):
        render_html(src, tmp_path / "out.pdf", limits=Limits(timeout=60, max_memory_mb=1024, allow_js=True))


def test_script_allowed_still_cannot_reach_the_network(tmp_path, server):
    url, hits = server
    src = page(tmp_path / "doc", f"""<p id="p">Text.</p><script>
        fetch("{url}/fetch").catch(() => {{}});
        const x = new XMLHttpRequest(); x.open("GET", "{url}/xhr"); x.send();
        try {{ new WebSocket("{url.replace('http', 'ws')}/ws"); }} catch (e) {{}}
        navigator.sendBeacon && navigator.sendBeacon("{url}/beacon", "x");
        new Image().src = "{url}/image";
        document.getElementById("p").textContent = "Script ran.";
    </script>""")
    out = tmp_path / "out.pdf"
    render_html(src, out, limits=Limits(allow_js=True))
    time.sleep(0.5)
    assert "Script ran." in pdf.text(out)
    assert hits == []


@pytest.mark.parametrize("target", ["{url}/refresh", "file:///etc/passwd", "", "elsewhere.html"])
def test_a_meta_refresh_is_not_followed(tmp_path, server, target):
    url, hits = server
    doc = tmp_path / "doc"
    page(doc, "<p>Other page.</p>", name="elsewhere.html")
    src = page(doc, "<p>Original page.</p>",
               head=f'<meta http-equiv="refresh" content="0; url={target.format(url=url)}">')
    out = tmp_path / "out.pdf"
    result = render_html(src, out)
    assert hits == []
    assert "Original page." in pdf.text(out) and "Other page." not in pdf.text(out)
    assert "root:" not in pdf.text(out)
    assert result.blocked


def test_chromium_runs_sandboxed_and_the_trusted_renderer_does_not(tmp_path):
    from publishing.render import Renderer

    with Renderer() as r:
        assert sandboxed(os.getpid(), r._browser) is False  # the detector tells the two apart
    result = render_html(page(tmp_path / "doc", "<p>Text.</p>"), tmp_path / "out.pdf")
    assert result.sandboxed is True


@pytest.mark.skipif(not shutil.which("unshare"), reason="no unshare")
def test_the_render_runs_without_a_network_where_namespaces_allow(tmp_path):
    probe = subprocess.run(["unshare", "--user", "--net", "--map-current-user", "true"], capture_output=True)
    if probe.returncode:
        pytest.skip("user and network namespaces are not available here")
    result = render_html(page(tmp_path / "doc", "<p>Text.</p>"), tmp_path / "out.pdf",
                         limits=Limits(require_netns=True))
    assert result.netns is True


@pytest.mark.skipif(not shutil.which("bwrap"), reason="no bwrap to take user namespaces away")
def test_no_sandbox_means_no_render(tmp_path):
    """Where Chromium cannot sandbox itself the render fails; it never falls back to no sandbox."""
    src = page(tmp_path / "doc", "<p>Text.</p>")
    out = tmp_path / "out.pdf"
    p = subprocess.run(["bwrap", "--dev-bind", "/", "/", "--unshare-user", "--disable-userns",
                        sys.executable, "-m", "publishing.cli", "html", str(src), "-o", str(out)],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode != 0 and "sandbox" in p.stderr.lower()
    assert not out.exists()


def test_the_html_command_renders_and_never_overwrites(tmp_path, capsys):
    src = page(tmp_path / "doc", "<p>Hello from a person.</p>")
    out = tmp_path / "out.pdf"
    assert main(["html", str(src), "-o", str(out), "--json"]) == 0
    assert '"pages": 1' in capsys.readouterr().out
    assert "Hello from a person." in pdf.text(out)
    with pytest.raises(SystemExit, match="exists"):
        main(["html", str(src), "-o", str(out)])


def test_a_user_content_build_matches_the_trusted_build(repo, renderer):
    for fmt in ("memo", "document"):
        folder = repo / "docs" / "notes" / f"same-{fmt}-v1"
        assert main(["new", str(folder), "--format", fmt]) == 0
        cfg = load(folder)
        s = resolve(folder, cfg)
        build(s, cfg, renderer)
        trusted = s.pdf.read_bytes()
        with UserContentRenderer() as r:
            assert build(s, cfg, r) == "current"  # same words, same pages
        assert s.pdf.read_bytes() == trusted


def test_report_toml_turns_user_content_mode_on_and_a_deck_is_refused(repo):
    (repo / "docs" / "report.toml").write_text("[user_content]\nenabled = true\nmax_pages = 5\n")
    folder = repo / "docs" / "notes" / "deck-v1"
    assert main(["new", str(folder), "--format", "deck"]) == 0
    cfg = load(folder)
    assert cfg.user_content == Limits(max_pages=5)
    assert main(["build", str(folder)]) == 1
    assert not folder.with_suffix(".pdf").exists()
    with UserContentRenderer() as r, pytest.raises(BuildError, match="slides.py is code"):
        build(resolve(folder, cfg), cfg, r)


def test_the_environment_forces_user_content_mode(repo, monkeypatch):
    folder = repo / "docs" / "notes" / "deck-v1"
    assert main(["new", str(folder), "--format", "deck"]) == 0
    monkeypatch.setenv("PUBLISHING_USER_CONTENT", "1")
    assert main(["build", str(folder)]) == 1  # a deck is code: refused
    monkeypatch.delenv("PUBLISHING_USER_CONTENT")
    assert main(["build", str(folder)]) == 0


def test_the_render_child_gets_no_secrets_from_the_environment(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "ghp_secret")
    monkeypatch.setenv("DOPPLER_TOKEN", "dp.st.secret")
    env = child_env()
    assert "GH_TOKEN" not in env and "DOPPLER_TOKEN" not in env
    assert env.get("PATH")
