"""User-content mode: render HTML that a person supplied as if it were hostile.

The trusted build (`render.Renderer`) renders a repository's own sources: Chromium's sandbox off,
pages loaded from `file://`, no request filter. That is wrong for a page made from someone's
upload, which could pull `/etc/passwd` or an internal address into the PDF. This mode:

- runs each render in its own supervised process tree, killed at the wall-clock limit or when its
  memory passes the memory limit, with secrets scrubbed from the environment;
- puts that tree in a fresh network namespace with no interfaces where the host allows
  unprivileged user namespaces (`unshare --user --net`), so nothing in it can reach a network;
- launches Chromium with its own sandbox ON and refuses to render if the renderers are not
  sandboxed (it never falls back to no sandbox);
- never loads a `file://` URL: the page is served from the virtual origin http://publishing.invalid,
  `/doc/` maps to the document's own folder and `/_theme/` to the house theme; every other request
  (any host, any other path, a hidden file, a symlink out of the folder) is refused, a navigation
  after the first (a meta refresh, a frame) gets an empty 204, and DNS and a dead proxy back the
  filter up; a Content-Security-Policy header is a second, independent filter;
- runs no script unless `allow_js` (then still no network: the filter and CSP stand);
- caps the bytes the page loads and the pages it prints.

Container requirements and residual risks: docs/user-content.md.
"""
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

ORIGIN = "http://publishing.invalid"
HOST = "publishing.invalid"
DOC, THEME = "/doc/", "/_theme/"
CHROMIUM_ARGS = [
    "--host-resolver-rules=MAP * ~NOTFOUND",  # no name resolves (and no DNS prefetch leaks)
    "--proxy-server=http://proxy.invalid:9", "--proxy-bypass-list=<-loopback>",  # unrouted -> dead proxy
    "--disable-background-networking", "--disable-component-update", "--no-pings",
    "--disable-features=DnsOverHttps,MediaRouter",
]
ENV_KEEP = ("PATH", "HOME", "LANG", "LANGUAGE", "TZ", "TMPDIR", "PLAYWRIGHT_BROWSERS_PATH", "XDG_CACHE_HOME",
            "FONTCONFIG_FILE", "FONTCONFIG_PATH")
STDERR_CHARS = 400


class UserContentError(Exception):
    """The render was refused or stopped: a limit, a missing sandbox, or a crash."""


class _Limit(Exception):
    """Raised in the child when the page passes a limit; its message goes to the caller as is."""


@dataclass(frozen=True)
class Limits:
    max_bytes: int = 50 * 2**20  # the document plus every file it loads
    max_pages: int = 300
    timeout: float = 60  # seconds of wall clock for one render, browser start included
    max_memory_mb: int = 2048  # private memory of the whole render tree
    allow_js: bool = False
    require_netns: bool = False  # fail rather than render with the host's network namespace

    FIELDS = ("max_bytes", "max_pages", "timeout", "max_memory_mb", "allow_js", "require_netns")


@dataclass
class Result:
    pages: int
    blocked: list = field(default_factory=list)  # every request the filter refused
    sandboxed: bool = False
    netns: bool = False
    problems: list = field(default_factory=list)  # layout lint (build mode)
    text: str = ""


# ---------------------------------------------------------------- the parent: supervise one render

def render_html(src: Path, out: Path, *, paper: str = "letter", limits: Limits | None = None) -> Result:
    """Render a person's HTML file to `out` (never overwritten). Its folder is all it can load."""
    limits = limits or Limits()
    src, out = Path(src).resolve(), Path(out)
    if out.exists():
        raise UserContentError(f"{out} exists; never overwrite")
    if not src.is_file():
        raise UserContentError(f"{src}: not a file")
    result, data = _render(src, src.parent, DOC + quote(src.name), kind="html", paper=paper, limits=limits)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "xb") as f:
        f.write(data)
    return result


class UserContentRenderer:
    """The build's renderer in user-content mode: `with UserContentRenderer() as r: build(s, cfg, r)`.
    Same interface as `render.Renderer`; each page is its own sandboxed, supervised render."""

    untrusted = True

    def __init__(self, limits: Limits | None = None):
        self.limits = limits or Limits()
        self._root: Path | None = None
        self.results: list[Result] = []

    def __enter__(self):
        _require_linux()
        return self

    def __exit__(self, *exc):
        pass

    def url(self, path: Path) -> str:
        """The page's URL for `path`: the theme, or the document's folder (which becomes its root)."""
        from .build import theme

        path = Path(path).resolve()
        if path.is_relative_to(theme()):
            return ORIGIN + THEME + quote(str(path.relative_to(theme())))
        self._root = path
        return ORIGIN + DOC

    def pdf(self, html: Path, out: Path, *, kind: str, paper: str = "letter") -> tuple[list[str], str]:
        html = Path(html).resolve()
        root = self._root or html.parent
        result, data = _render(html, root, DOC + quote(html.name), kind=kind, paper=paper, limits=self.limits)
        Path(out).write_bytes(data)
        self.results.append(result)
        return result.problems, result.text


def child_env() -> dict:
    """The render's environment: locale, paths and the browser cache, never a token."""
    env = {k: v for k, v in os.environ.items() if k in ENV_KEEP or k.startswith("LC_")}
    env.setdefault("PATH", os.defpath)
    pkg_parent = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = pkg_parent
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _require_linux():
    if not sys.platform.startswith("linux"):
        raise UserContentError("user-content mode needs Linux (namespaces and /proc supervise the render)")


@lru_cache(maxsize=1)
def netns_available() -> bool:
    """True when this host lets an unprivileged user make a user and network namespace."""
    if not shutil.which("unshare"):
        return False
    try:
        return subprocess.run(["unshare", "--user", "--net", "--map-current-user", "true"],
                              capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _render(document: Path, root: Path, doc_path: str, *, kind: str, paper: str,
            limits: Limits, csp: bool = True) -> tuple[Result, bytes]:
    """One supervised render. `csp=False` only lets the tests prove the request filter on its own."""
    _require_linux()
    size = document.stat().st_size
    if size > limits.max_bytes:
        raise UserContentError(f"{document.name} is {size} bytes, over the input limit of {limits.max_bytes}")
    netns = netns_available()
    if limits.require_netns and not netns:
        raise UserContentError("no network namespace here (unprivileged user namespaces are blocked) and "
                               "require_netns is set")
    with tempfile.TemporaryDirectory(prefix="publishing-uc-") as tmp:
        tmp = Path(tmp)
        job = {"document": str(document), "root": str(Path(root).resolve()), "doc_path": doc_path, "kind": kind,
               "paper": paper, "out": str(tmp / "out.pdf"), "result": str(tmp / "result.json"),
               "limits": {k: getattr(limits, k) for k in Limits.FIELDS}, "csp": csp}
        (tmp / "job.json").write_text(json.dumps(job))
        cmd = [sys.executable, "-m", "publishing.usercontent", str(tmp / "job.json")]
        if netns:
            cmd = ["unshare", "--user", "--net", "--map-current-user", "--", *cmd]
        with open(tmp / "stderr", "w+b") as err:
            code, why = _supervise(cmd, tmp, err, limits)
            err.seek(0)
            stderr = err.read().decode(errors="replace")
        reply = json.loads((tmp / "result.json").read_text()) if (tmp / "result.json").is_file() else {}
        if why:
            raise UserContentError(f"{document.name}: {why}")
        if reply.get("limit"):
            raise UserContentError(f"{document.name}: {reply['error']}")
        if code != 0 or "error" in reply:
            raise UserContentError(_failure(reply.get("error"), reply.get("detail", "") + stderr, code))
        data = (tmp / "out.pdf").read_bytes()
        from . import pdf

        pages = pdf.pages(tmp / "out.pdf")
        if pages > limits.max_pages:
            raise UserContentError(f"{document.name}: over the page limit of {limits.max_pages}")
        result = Result(pages=pages, blocked=reply["blocked"], sandboxed=reply["sandboxed"], netns=netns,
                        problems=reply["problems"], text=reply["text"])
        return result, data


def _failure(error: str | None, detail: str, code: int) -> str:
    text = f"{error or ''}\n{detail}"
    if re.search(r"sandbox(ing)? failed|No usable sandbox|not sandboxed", text, re.I):
        return ("Chromium could not start its sandbox here (user namespaces are blocked?); user-content mode "
                "never renders without it. Container requirements: docs/user-content.md")
    if re.search(r"crash", text, re.I):
        return "the page crashed the renderer"
    tail = (error or detail.strip() or f"exit status {code}")[-STDERR_CHARS:]
    return f"render failed: {tail}"


def _supervise(cmd, cwd, err, limits: Limits) -> tuple[int | None, str | None]:
    """Run the render child; kill its whole tree at the time or memory limit. Returns (exit code, why)."""
    proc = subprocess.Popen(cmd, cwd=cwd, env=child_env(), stdin=subprocess.DEVNULL, stdout=err, stderr=err,
                            start_new_session=True)
    deadline = time.monotonic() + limits.timeout
    cap = limits.max_memory_mb * 2**20
    why = None
    try:
        while proc.poll() is None:
            if time.monotonic() > deadline:
                why = f"over the time limit of {limits.timeout:g} s"
            else:
                used = _memory(_tree(proc.pid))
                if used > cap:
                    why = f"over the memory limit of {limits.max_memory_mb} MB"
            if why:
                _kill(proc)
                break
            time.sleep(0.1)
    finally:
        if proc.poll() is None:
            _kill(proc)
    return proc.returncode, why


def _tree(pid: int) -> list[int]:
    """`pid` and every descendant (from /proc, so it sees into the sandbox's own pid namespaces)."""
    kids: dict[int, list[int]] = {}
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                with open(f"/proc/{d}/stat") as f:
                    ppid = int(f.read().rsplit(")", 1)[1].split()[1])
            except (OSError, ValueError, IndexError):
                continue
            kids.setdefault(ppid, []).append(int(d))
    out, todo = [], [pid]
    while todo:
        p = todo.pop()
        out.append(p)
        todo += kids.get(p, [])
    return out


def _memory(pids: list[int]) -> int:
    """Private resident bytes (resident minus shared pages) summed over `pids`."""
    page = os.sysconf("SC_PAGE_SIZE")
    total = 0
    for p in pids:
        try:
            with open(f"/proc/{p}/statm") as f:
                v = f.read().split()
            total += max(int(v[1]) - int(v[2]), 0) * page
        except (OSError, ValueError, IndexError):
            continue
    return total


def _kill(proc):
    for p in _tree(proc.pid):  # Chromium may sit in its own session: kill by tree, not by group
        try:
            os.kill(p, 9)
        except OSError:
            pass
    try:
        os.killpg(proc.pid, 9)
    except OSError:
        pass
    proc.wait()


# ---------------------------------------------------------------- the sandbox check

def _ns(pid, kind: str) -> str | None:
    try:
        return os.readlink(f"/proc/{pid}/ns/{kind}")
    except OSError:
        return None


def _renderers_sandboxed(root_pid: int) -> bool:
    """True when the browser under `root_pid` runs renderers, and every one is in its own user or
    pid namespace (Chromium's namespace sandbox), with no --no-sandbox anywhere in the tree."""
    mine = (_ns(root_pid, "user"), _ns(root_pid, "pid"))
    renderers = 0
    for p in _tree(root_pid):
        try:
            with open(f"/proc/{p}/cmdline", "rb") as f:
                args = f.read().decode(errors="replace").replace("\0", " ").split()  # Chromium rewrites argv
        except OSError:
            continue
        if "--no-sandbox" in args:
            return False
        if "--type=renderer" in args:
            renderers += 1
            theirs = (_ns(p, "user"), _ns(p, "pid"))
            if None in theirs or theirs == mine:
                return False
    return renderers > 0


def sandboxed(root_pid: int, browser) -> bool:
    """Whether `browser` (a Playwright browser launched under `root_pid`) renders in Chromium's sandbox."""
    page = browser.new_page()
    try:
        page.set_content("<p>sandbox probe</p>")
        return _renderers_sandboxed(root_pid)
    finally:
        page.close()


# ---------------------------------------------------------------- the child: one render, filtered

def _csp(allow_js: bool) -> str:
    script = "'self' 'unsafe-inline' 'unsafe-eval'" if allow_js else "'none'"
    return ("default-src 'none'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline' data:; "
            f"font-src 'self' data:; media-src 'self' data: blob:; script-src {script}; connect-src 'none'; "
            "frame-src 'none'; child-src 'none'; worker-src 'none'; object-src 'none'; manifest-src 'none'; "
            "form-action 'none'; base-uri 'self'")


def _local(url: str, mounts: dict) -> Path | None:
    """The file a virtual-origin URL names, or None when it is not one this page may load."""
    u = urlsplit(url)
    if u.scheme != "http" or u.netloc != HOST:
        return None
    path = unquote(u.path)
    for prefix, root in mounts.items():
        if path.startswith(prefix):
            rel = path[len(prefix):]
            parts = rel.split("/")
            if not rel or any(p in ("", ".", "..") or p.startswith(".") or "\0" in p for p in parts):
                return None
            try:
                f = (root / rel).resolve(strict=True)
            except (OSError, RuntimeError):
                return None
            return f if f.is_relative_to(root) and f.is_file() else None
    return None


def _child(job_path: str) -> int:
    from playwright.sync_api import sync_playwright

    from .build import theme
    from .render import DECK_LINT, MARGIN_MM, MM, PAGE_LINT, PAPER_MM

    job = json.loads(Path(job_path).read_text())
    lim = Limits(**job["limits"])
    reply_path = Path(job["result"])
    document, kind = Path(job["document"]), job["kind"]
    mounts = {DOC: Path(job["root"]), THEME: theme()}
    main_url = ORIGIN + job["doc_path"]
    state = {"served": 0, "navigated": False, "over": None}
    blocked: list[str] = []

    def handle(route):
        try:
            serve(route)
        except Exception:  # a file that vanished, a closed page: refuse rather than leave it hanging
            blocked.append(route.request.url)
            route.abort("blockedbyclient")

    def serve(route):
        req = route.request
        url = req.url
        if req.is_navigation_request():
            frame = req.frame
            if not state["navigated"] and url == main_url and frame.parent_frame is None:
                state["navigated"] = True
                body = document.read_bytes()
                state["served"] += len(body)
                headers = {"content-security-policy": _csp(lim.allow_js)} if job["csp"] else {}
                return route.fulfill(body=body, content_type="text/html; charset=utf-8", headers=headers)
            blocked.append(url)
            return route.fulfill(status=204)  # no content: the frame stays where it is
        f = _local(url, mounts)
        if f is None:
            blocked.append(url)
            return route.abort("blockedbyclient")
        size = f.stat().st_size
        if state["served"] + size > lim.max_bytes:
            state["over"] = url
            blocked.append(url)
            return route.abort("blockedbyclient")
        body = f.read_bytes()
        state["served"] += len(body)
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        route.fulfill(body=body, content_type=ctype, headers={"x-content-type-options": "nosniff"})

    def console(msg):  # what Chromium itself refused (file:// from this origin, CSP): record the URL
        if re.search(r"Not allowed to load local resource|Content Security Policy|Refused to", msg.text):
            m = re.search(r"'((?:https?|wss?|file|ftp):[^']*)'|resource: (\S+)", msg.text)
            blocked.append((m.group(1) or m.group(2)) if m else msg.text[:200])

    try:
        if kind == "deck":
            viewport = {"width": 1920, "height": 1080}
        else:
            w, h = PAPER_MM[job["paper"]]
            viewport = {"width": round((w - 2 * MARGIN_MM) * MM), "height": round(h * MM)}
        ms = (lim.timeout + 5) * 1000  # the parent's hard limit always decides first
        with sync_playwright() as pw:
            browser = pw.chromium.launch(chromium_sandbox=True, args=CHROMIUM_ARGS, timeout=ms)
            ctx = browser.new_context(java_script_enabled=lim.allow_js, service_workers="block",
                                      accept_downloads=False, viewport=viewport)
            ctx.set_default_timeout(ms)
            ctx.route("**/*", handle)
            # a routed WebSocket that is never connected to its server stays a mock (closing it hangs)
            ctx.route_web_socket(re.compile(".*"), lambda ws: blocked.append(ws.url))
            page = ctx.new_page()
            page.on("console", console)
            page.goto(main_url, wait_until="load")
            if not _renderers_sandboxed(os.getpid()):
                raise RuntimeError("Chromium is not sandboxed")  # fail closed
            if state["over"]:
                raise _Limit(f"the page loads more than the input limit of {lim.max_bytes} bytes")
            page.evaluate("Promise.allSettled([...document.fonts].map((f) => f.load()))"
                          ".then(() => document.fonts.ready).then(() => true)")  # a refused font is no error
            height = page.evaluate("document.documentElement.scrollHeight")
            if height / viewport["height"] > 2 * lim.max_pages:  # far past it: stop before laying out print
                raise _Limit(f"about {height // viewport['height']} pages, over the page limit of {lim.max_pages}")
            problems = page.evaluate(DECK_LINT if kind == "deck" else PAGE_LINT) if kind != "html" else []
            text = page.evaluate("document.body ? document.body.innerText : ''")
            paper = {"format": "Letter" if job["paper"] == "letter" else "A4"} if kind == "html" else {}
            page.pdf(path=job["out"], prefer_css_page_size=True, print_background=True, tagged=True,
                     outline=kind in ("memo", "document"), page_ranges=f"1-{lim.max_pages + 1}", **paper)
            if state["over"]:
                raise _Limit(f"the page loads more than the input limit of {lim.max_bytes} bytes")
            browser.close()
    except _Limit as e:
        reply_path.write_text(json.dumps({"error": str(e), "limit": True}))
        return 1
    except Exception as e:  # report it to the parent, which owns the message
        first = str(e).splitlines()[0] if str(e) else ""
        reply_path.write_text(json.dumps({"error": f"{type(e).__name__}: {first}", "detail": str(e)[-4000:]}))
        return 1
    blocked = list(dict.fromkeys(blocked))
    reply_path.write_text(json.dumps({"blocked": blocked, "sandboxed": True, "problems": problems, "text": text}))
    return 0


def limits_from(table: dict) -> Limits | None:
    """`[user_content]` from report.toml: None unless `enabled = true`; ValueError on a bad key or value."""
    unknown = set(table) - {"enabled", *Limits.FIELDS}
    if unknown:
        raise ValueError(f"[user_content] has unknown keys {sorted(unknown)}")
    for k, v in table.items():
        want = bool if k in ("enabled", "allow_js", "require_netns") else (int, float) if k == "timeout" else int
        if not isinstance(v, want) or (want is not bool and (isinstance(v, bool) or v <= 0)):
            raise ValueError(f"[user_content] {k} = {v!r}: not a valid value")
    if not table.get("enabled", False):
        return None
    return Limits(**{k: v for k, v in table.items() if k != "enabled"})


if __name__ == "__main__":
    sys.exit(_child(sys.argv[1]))

