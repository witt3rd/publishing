"""User-content mode, attack-style regression fixtures beyond tests/test_usercontent.py.

Two groups. The `_local` tests drive the request filter's path resolution directly with traversal
vectors (no browser). The render tests build a hostile folder and render it through `render_html`; each
asserts the sandbox is on, nothing reached a local server, and no planted secret reached the PDF.
Nothing here loosens a limit or the sandbox: a failing test is a hole, to be fixed in the code.
"""
import re
import time
from pathlib import Path

import pytest

from publishing import pdf
from publishing.usercontent import (DOC, HOST, THEME, Limits, UserContentError, _csp, _local, limits_from,
                                    render_html)

from test_usercontent import MARKER, page, server  # noqa: F401 - `server` is a fixture


@pytest.fixture
def tree(tmp_path):
    """doc/ (the folder), a secret beside it, a sibling that shares doc's name as a prefix, and links out."""
    doc, outside, sibling = tmp_path / "doc", tmp_path / "outside", tmp_path / "doc-secret"
    for d in (doc, outside, sibling, doc / "sub"):
        d.mkdir()
    (doc / "ok.css").write_text("x{}")
    (doc / "sub" / "deep.css").write_text("x{}")
    (doc / ".hidden").mkdir()
    (doc / ".hidden" / "a.css").write_text("x{}")
    (outside / "secret.css").write_text(f"body::after {{ content: '{MARKER}' }}")
    (sibling / "secret.css").write_text(f"body::after {{ content: '{MARKER}' }}")
    (doc / "linkdir").symlink_to(outside, target_is_directory=True)
    (doc / "linkfile.css").symlink_to(outside / "secret.css")
    (doc / "sub" / "up.css").symlink_to("../../outside/secret.css")  # a relative link that climbs out
    return doc


def url(path: str, host: str = HOST, scheme: str = "http") -> str:
    return f"{scheme}://{host}{path}"


@pytest.mark.parametrize("path", [
    "/doc/ok.css", "/doc/sub/deep.css", "/doc/sub//deep.css".replace("//", "/"),
])
def test_local_serves_plain_files_inside_the_folder(tree, path):
    assert _local(url(path), {DOC: tree}) == (tree / path[len(DOC):]).resolve()


@pytest.mark.parametrize("path", [
    "/doc/../outside/secret.css", "/doc/sub/../../outside/secret.css", "/doc/%2e%2e/outside/secret.css",
    "/doc/%2E%2E/outside/secret.css", "/doc/sub/%2e%2e/%2e%2e/outside/secret.css",
    "/doc/%252e%252e/outside/secret.css",  # double-encoded: one decode leaves a literal %2e%2e, no such file
    "/doc/..%2foutside/secret.css", "/doc/sub%2f..%2f..%2foutside%2fsecret.css",
    "/doc/..\\outside\\secret.css", "/doc/%5c..%5coutside%5csecret.css",
    "/doc/./ok.css", "/doc//ok.css", "/doc/sub/./deep.css", "/doc/ok.css%00.png", "/doc/ok.css\0",
    "/doc/", "/doc/sub", "/doc/sub/", "/doc",  # the folder is not a file; "/doc" is no mount at all
    "/doc/.hidden/a.css", "/doc/.hidden", "/doc/%2ehidden/a.css",
    "/doc/linkdir/secret.css", "/doc/linkfile.css", "/doc/sub/up.css",  # symlinks out of the folder
    "/docx/ok.css", "/doc-secret/secret.css", "/DOC/ok.css", "/doc/../doc-secret/secret.css",
    "/_theme/../doc/ok.css", "/etc/passwd", "/", "",
])
def test_local_refuses_traversal_hidden_and_escaping_paths(tree, path):
    (tree.parent / "theme").mkdir(exist_ok=True)
    assert _local(url(path), {DOC: tree, THEME: tree.parent / "theme"}) is None


@pytest.mark.parametrize("u", [
    "https://publishing.invalid/doc/ok.css", "ftp://publishing.invalid/doc/ok.css", "file:///etc/passwd",
    "http://publishing.invalid:8080/doc/ok.css", "http://publishing.invalid.evil.test/doc/ok.css",
    "http://evil.test/doc/ok.css", "http://127.0.0.1/doc/ok.css", "http://localhost/doc/ok.css",
    "http://publishing.invalid@evil.test/doc/ok.css", "http://evil.test@publishing.invalid/doc/ok.css",
    "http://PUBLISHING.INVALID/doc/ok.css", "//publishing.invalid/doc/ok.css", "/doc/ok.css", "doc/ok.css",
    "data:text/css,x{}", "blob:http://publishing.invalid/x", "javascript:1", "",
])
def test_local_refuses_any_other_origin(tree, u):
    assert _local(u, {DOC: tree}) is None


def test_local_never_serves_a_theme_path_outside_the_theme(tmp_path):
    theme = tmp_path / "theme"
    theme.mkdir()
    (theme / "a.css").write_text("x{}")
    (tmp_path / "secret.css").write_text("x{}")
    mounts = {THEME: theme}
    assert _local(url("/_theme/a.css"), mounts) == (theme / "a.css").resolve()
    assert _local(url("/_theme/../secret.css"), mounts) is None
    assert _local(url("/_theme/%2e%2e/secret.css"), mounts) is None


def test_the_csp_has_no_hole_for_the_network_frames_or_script():
    policy = _csp(False)
    for directive in ("default-src 'none'", "script-src 'none'", "connect-src 'none'", "frame-src 'none'",
                      "child-src 'none'", "worker-src 'none'", "object-src 'none'", "form-action 'none'",
                      "base-uri 'self'"):
        assert directive in policy
    assert "http:" not in policy and "https:" not in policy and "*" not in policy
    assert "'unsafe-inline'" not in policy.split("script-src")[1].split(";")[0]
    assert "script-src 'self' 'unsafe-inline' 'unsafe-eval'" in _csp(True)  # script is opt-in, nothing else widens
    strip = lambda p: re.sub(r"script-src [^;]*;", "", p)  # noqa: E731
    assert strip(_csp(True)) == strip(_csp(False))


@pytest.mark.parametrize("table, msg", [
    ({"enabled": True, "no_sandbox": True}, "unknown keys"),
    ({"enabled": True, "sandbox": False}, "unknown keys"),
    ({"enabled": True, "max_bytes": 0}, "not a valid value"),
    ({"enabled": True, "max_bytes": -1}, "not a valid value"),
    ({"enabled": True, "max_pages": True}, "not a valid value"),  # a bool is not a count
    ({"enabled": True, "timeout": "60"}, "not a valid value"),
    ({"enabled": True, "max_memory_mb": 1.5}, "not a valid value"),
    ({"enabled": "yes"}, "not a valid value"),
    ({"enabled": True, "allow_js": 1}, "not a valid value"),
])
def test_report_toml_limits_reject_bad_keys_and_values(table, msg):
    with pytest.raises(ValueError, match=msg):
        limits_from(table)


def test_report_toml_limits_are_off_unless_enabled():
    assert limits_from({}) is None and limits_from({"enabled": False, "max_pages": 3}) is None
    assert limits_from({"enabled": True, "timeout": 5}) == Limits(timeout=5)


def test_a_symlinked_directory_or_file_cannot_leave_the_folder(tmp_path, tree):
    src = page(tree, "<p>Visible text.</p><img src='linkdir/secret.css'><iframe src='linkdir/secret.css'></iframe>",
               head="<link rel=stylesheet href='linkdir/secret.css'><link rel=stylesheet href='sub/up.css'>"
                    "<link rel=stylesheet href='linkfile.css'><style>@import 'linkdir/secret.css';</style>")
    out = tmp_path / "out.pdf"
    render_html(src, out)
    assert "Visible text." in pdf.text(out) and MARKER not in pdf.text(out)


def test_a_sibling_folder_sharing_a_name_prefix_is_not_the_folder(tmp_path, tree):
    src = page(tree, "<p>Visible text.</p>",
               head="<link rel=stylesheet href='../doc-secret/secret.css'><link rel=stylesheet href='/doc-secret/secret.css'>")
    out = tmp_path / "out.pdf"
    render_html(src, out)
    assert MARKER not in pdf.text(out)


def test_a_stylesheet_that_is_served_cannot_pull_in_more(tmp_path, tree, server):
    """A permitted file is still filtered: its own @import and url() get the same refusals."""
    base, hits = server
    (tree / "deep.css").write_text(f"@import '../outside/secret.css'; @import url({base}/x.css);"
                                   f"@import 'linkfile.css'; body::before {{ background: url({base}/bg.png); "
                                   "content: 'DEEP-OK' }}")
    src = page(tree, "<p>Visible text.</p>", head="<link rel=stylesheet href='deep.css'>")
    out = tmp_path / "out.pdf"
    result = render_html(src, out)
    text = pdf.text(out)
    assert "DEEP-OK" in text and MARKER not in text and hits == []
    assert any(u.startswith(base) for u in result.blocked)


def test_script_cannot_read_files_or_other_origins(tmp_path, tree, server):
    base, hits = server
    src = page(tree, f"""<p id="p">Visible text.</p><script>
        const out = [];
        const note = (k) => (v) => out.push(k + ':' + String(v).slice(0, 40));
        const reads = ["file:///etc/passwd", "/doc/../outside/secret.css", "/doc/linkfile.css", "/doc/.hidden/a.css",
                       "{base}/x", "http://127.0.0.1:9/x", "//evil.invalid/x"];
        Promise.allSettled(reads.map((u) => fetch(u).then((r) => r.text().then(note(u)), note('refused ' + u))))
          .then(() => {{ document.getElementById('p').textContent = 'DONE ' + out.join(' | '); }});
    </script>""")
    out = tmp_path / "out.pdf"
    render_html(src, out, limits=Limits(allow_js=True))
    time.sleep(0.5)
    text = pdf.text(out)
    assert "DONE" in text, text  # the script ran and finished: every read ended in a refusal
    assert MARKER not in text and "root:" not in text and hits == []
    assert text.count("refused") == 7  # none produced a body


def test_script_cannot_open_windows_or_nest_documents(tmp_path, tree, server):
    base, hits = server
    src = page(tree, f"""<p id="p">Visible text.</p><script>
        try {{ window.open("{base}/popup"); }} catch (e) {{}}
        try {{ window.open("file:///etc/passwd"); }} catch (e) {{}}
        const f = document.createElement('iframe');
        f.src = "data:text/html,<script>fetch('{base}/data-frame')<\\/script>"; document.body.append(f);
        const g = document.createElement('iframe'); g.srcdoc = "<img src='{base}/srcdoc'>"; document.body.append(g);
        try {{ new Worker(URL.createObjectURL(new Blob(["fetch('{base}/worker')"]))); }} catch (e) {{}}
        try {{ navigator.serviceWorker.register('/doc/sw.js'); }} catch (e) {{}}
        </script>""")
    (tree / "sw.js").write_text(f"fetch('{base}/sw')")
    out = tmp_path / "out.pdf"
    render_html(src, out, limits=Limits(allow_js=True))
    time.sleep(0.5)
    assert hits == []
    assert "Visible text." in pdf.text(out)


@pytest.mark.parametrize("script", [
    "document.getElementById('f').submit();", "document.getElementById('a').click();",
    "location.href = '{base}/nav';",
])
def test_script_cannot_submit_a_form_download_or_navigate_away(tmp_path, tree, server, script):
    """Today these stall the render until the time limit (it fails closed, with nothing written); what must
    never happen is a request reaching the server or a PDF carrying what it fetched."""
    base, hits = server
    src = page(tree, f"""<p>Visible text.</p><form id="f" action="{base}/form" method="post"></form>
        <a id="a" href="{base}/download" download>d</a><script>{script.format(base=base)}</script>""")
    out = tmp_path / "out.pdf"
    try:
        render_html(src, out, limits=Limits(allow_js=True, timeout=6))
    except UserContentError as e:
        assert "time limit" in str(e) and not out.exists()
    else:
        assert MARKER not in pdf.text(out)
    time.sleep(0.3)
    assert hits == []


def test_an_svg_cannot_reach_out_from_any_embedding(tmp_path, tree, server):
    base, hits = server
    (tree / "evil.svg").write_text(f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
      width="50" height="50"><image href="{base}/svg-img.png" width="10" height="10"/>
      <image href="file:///etc/passwd" width="10" height="10"/><image href="../outside/secret.css"/>
      <style>@import url({base}/svg-import.css); rect {{ fill: url({base}/svg-fill); }}</style>
      <foreignObject width="50" height="50"><iframe xmlns="http://www.w3.org/1999/xhtml" src="{base}/fo"/>
      </foreignObject><script>fetch("{base}/svg-script")</script><rect width="5" height="5"/></svg>""")
    src = page(tree, """<p>Visible text.</p><img src="evil.svg"><object data="evil.svg"></object>
        <embed src="evil.svg"><iframe src="evil.svg"></iframe><div style="background:url(evil.svg)">b</div>""")
    out = tmp_path / "out.pdf"
    render_html(src, out, limits=Limits(allow_js=True))
    time.sleep(0.5)
    assert hits == [] and MARKER not in pdf.text(out) and "root:" not in pdf.text(out)


def test_a_symlinked_source_page_is_still_confined_to_its_resolved_folder(tmp_path, tree):
    """render_html resolves its source: a link to a page elsewhere takes that page's folder, not the link's."""
    elsewhere = tmp_path / "elsewhere"
    page(elsewhere, "<p>Linked page.</p><link rel=stylesheet href='../outside/secret.css'>"
         "<iframe src='../outside/secret.css'></iframe>")
    link = tree / "link.html"
    link.symlink_to(elsewhere / "index.html")
    out = tmp_path / "out.pdf"
    render_html(link, out)
    assert "Linked page." in pdf.text(out) and MARKER not in pdf.text(out)


def test_many_small_files_add_up_to_the_input_limit(tmp_path, tree):
    """Each file is under the limit; together they are over it: the total is what is capped."""
    imgs = []
    for i in range(6):
        (tree / f"p{i}.png").write_bytes(b"\x89PNG" + b"\0" * 30_000)
        imgs.append(f"<img src='p{i}.png'>")
    src = page(tree, "<p>Text.</p>" + "".join(imgs))
    out = tmp_path / "out.pdf"
    with pytest.raises(UserContentError, match="input limit"):
        render_html(src, out, limits=Limits(max_bytes=100_000))
    assert not out.exists()


def test_the_same_file_loaded_again_and_again_still_counts(tmp_path, tree):
    (tree / "big.png").write_bytes(b"\x89PNG" + b"\0" * 40_000)
    src = page(tree, "<p>Text.</p>" + "".join(f"<img src='big.png?n={i}'>" for i in range(6)))
    out = tmp_path / "out.pdf"
    with pytest.raises(UserContentError, match="input limit"):
        render_html(src, out, limits=Limits(max_bytes=100_000))
    assert not out.exists()


def test_a_page_exactly_at_the_page_limit_renders_and_one_more_does_not(tmp_path):
    src = page(tmp_path / "doc", "".join(f'<p style="break-before:page">P{i}</p>' for i in range(4)))
    out = tmp_path / "out.pdf"
    assert render_html(src, out, limits=Limits(max_pages=4)).pages == 4
    out2 = tmp_path / "out2.pdf"
    with pytest.raises(UserContentError, match="over the page limit of 3"):
        render_html(src, out2, limits=Limits(max_pages=3))
    assert not out2.exists()


def test_a_refused_render_never_replaces_an_existing_output(tmp_path):
    src = page(tmp_path / "doc", "<p>" + "x" * 5000 + "</p>")
    out = tmp_path / "out.pdf"
    out.write_bytes(b"precious")
    with pytest.raises(UserContentError, match="never overwrite"):
        render_html(src, out)
    out.unlink()
    with pytest.raises(UserContentError, match="input limit"):
        render_html(src, out, limits=Limits(max_bytes=1000))
    assert not out.exists()


def test_a_missing_or_directory_source_is_refused(tmp_path):
    (tmp_path / "d").mkdir()
    for bad in (tmp_path / "nope.html", tmp_path / "d"):
        with pytest.raises(UserContentError, match="not a file"):
            render_html(bad, tmp_path / "out.pdf")
