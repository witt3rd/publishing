"""Chromium render (pinned Playwright) and the layout lint."""
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

class ToolchainError(Exception):
    """The renderer is not installed or not usable: an operator's problem, not the source's."""


MM = 96 / 25.4  # CSS px per mm
PAPER_MM = {"letter": (215.9, 279.4), "a4": (210.0, 297.0)}
MARGIN_MM = 20  # page.css left/right page margin

DECK_LINT = """() => {
  const out = [];
  document.querySelectorAll('img').forEach((e) => { if (e.complete && !e.naturalWidth) out.push(`image not found: ${e.getAttribute('src')}`); });
  document.querySelectorAll('.slide').forEach((s, i) => {
    const S = s.getBoundingClientRect(), floor = S.bottom - 72;
    const body = s.querySelector('.body');
    if (body) {
      let max = 0;
      body.querySelectorAll('*').forEach((e) => { const r = e.getBoundingClientRect(); if (r.height) max = Math.max(max, r.bottom); });
      if (max > floor + 1) out.push(`page ${i + 1}: content runs into the footer by ${Math.round(max - floor)}px`);
      const h = [...s.querySelectorAll('h1,h2')].map((e) => e.getBoundingClientRect().bottom);
      if (h.some((b) => b > body.getBoundingClientRect().top + 1)) out.push(`page ${i + 1}: heading overlaps body`);
    }
    s.querySelectorAll('*').forEach((e) => {
      const r = e.getBoundingClientRect();
      if (r.width && r.height && (r.right > S.right + 1 || r.bottom > S.bottom + 1)) out.push(`page ${i + 1}: <${e.tagName.toLowerCase()}> leaves the page`);
    });
  });
  return [...new Set(out)];
}"""

PAGE_LINT = """() => {
  const out = [], col = document.querySelector('main') || document.body;
  const right = col.getBoundingClientRect().right;
  const name = (e) => (e.innerText || e.getAttribute('src') || '').trim().split(/\\s+/).slice(0, 6).join(' ');
  document.querySelectorAll('img').forEach((e) => { if (e.complete && !e.naturalWidth) out.push(`image not found: ${e.getAttribute('src')}`); });
  document.querySelectorAll('pre, table, figure, img, svg, .q, .summary, blockquote').forEach((e) => {
    const over = Math.max(e.scrollWidth - e.clientWidth, e.getBoundingClientRect().right - right);
    if (over > 1) out.push(`<${e.tagName.toLowerCase()}> "${name(e)}" is ${Math.round(over)}px wider than the text column`);
  });
  return [...new Set(out)];
}"""

VIDEO_LINT = """(families) => {
  const out = [], allowed = new Set(families.map((f) => f.toLowerCase())), bad = new Set(), text = [];
  const root = document.querySelector('[data-composition-id]');
  if (!root) return { problems: ['no composition: the root element needs data-composition-id'], text: '' };
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n; (n = walk.nextNode());) {
    const p = n.parentElement;
    if (!p || p.closest('script, style, noscript') || !n.textContent.trim()) continue;
    text.push(n.textContent.trim());
    const first = getComputedStyle(p).fontFamily.split(',')[0].trim().replace(/^["']|["']$/g, '');
    if (!allowed.has(first.toLowerCase())) bad.add(first);
  }
  if (bad.size) out.push(`text set in a font that is not vendored (another host renders it differently): ${[...bad].join(', ')}`
    + ' - use the theme (var(--sans), var(--serif), var(--mono)) or a family house.css names');
  document.querySelectorAll('img').forEach((e) => { if (e.complete && !e.naturalWidth) out.push(`image not found: ${e.getAttribute('src')}`); });
  const svg = new Set([...document.querySelectorAll('svg *, svg')].filter((e) => !(e instanceof HTMLElement)
    && getComputedStyle(e).animationName !== 'none').map((e) => `<${e.tagName.toLowerCase()}${e.id ? '#' + e.id : ''}>`));
  if (svg.size) out.push(`CSS animation on an SVG element (HyperFrames seeks HTML elements only, so it would play in real time): ${[...svg].join(', ')}`
    + ' - animate an HTML element that holds it');
  const w = +root.dataset.width, h = +root.dataset.height, d = +root.dataset.duration;
  if (!(w > 0 && h > 0)) out.push('the root composition needs data-width and data-height');
  if (!(d > 0)) out.push('the root composition needs data-duration (seconds): a video has a known end');
  return { problems: out, text: text.join('\\n') };
}"""


class Renderer:
    """One browser for a whole build: `with Renderer() as r: r.pdf(html, out, kind=...)`.
    Nested use shares the browser already running (Playwright's sync API allows one).
    For trusted sources only (sandbox off, file:// pages, no request filter): a person's content
    goes through `usercontent.UserContentRenderer`."""

    _active = None
    untrusted = False

    @staticmethod
    def url(path: Path) -> str:
        """The URL the page uses for a local folder or file."""
        return path.as_uri()

    def __enter__(self):
        if Renderer._active is not None:
            self._browser, self._owner = Renderer._active._browser, False
            return self
        self._owner = True
        Renderer._active = self
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch()
        except PlaywrightError as e:
            self._pw.stop()
            Renderer._active = None
            raise ToolchainError("Chromium is not installed for the pinned Playwright.\n"
                                 "  Run `publishing setup` once (CI: `publishing setup --with-deps`).\n"
                                 + str(e).splitlines()[0]) from None
        return self

    def __exit__(self, *exc):
        if self._owner:
            Renderer._active = None
            self._browser.close()
            self._pw.stop()

    def inspect(self, html: Path, families: list[str]) -> tuple[dict, list[str]]:
        """Open a video composition offline and run the video lint (fonts, images, size, its text).
        Returns the lint result and every request it tried to make off the file system."""
        remote = []
        page = self._browser.new_page(viewport={"width": 1920, "height": 1080})
        try:
            def offline(route):
                if route.request.url.startswith(("file:", "data:", "blob:", "about:")):
                    route.continue_()
                else:
                    remote.append(route.request.url)
                    route.abort()
            page.route("**/*", offline)
            page.goto(html.resolve().as_uri(), wait_until="load")
            page.evaluate("Promise.all([...document.fonts].map((f) => f.load().catch(() => null))).then(() => true)")
            result = page.evaluate(VIDEO_LINT, families)
        finally:
            page.close()
        return result, sorted(set(remote))

    def pdf(self, html: Path, out: Path, *, kind: str, paper: str = "letter") -> tuple[list[str], str]:
        """Render `html` to `out`. Returns the layout-lint problems (empty is clean) and the text as
        printed (innerText: after text-transform, unlike text read back from letter-spaced PDF glyphs)."""
        if kind == "deck":
            viewport = {"width": 1920, "height": 1080}
        else:
            w, h = PAPER_MM[paper]
            viewport = {"width": round((w - 2 * MARGIN_MM) * MM), "height": round(h * MM)}
        page = self._browser.new_page(viewport=viewport)
        try:
            page.goto(html.resolve().as_uri(), wait_until="load")
            # load every vendored face, including those only the print margin boxes use
            page.evaluate("Promise.all([...document.fonts].map((f) => f.load())).then(() => document.fonts.ready).then(() => true)")
            problems = page.evaluate(DECK_LINT if kind == "deck" else PAGE_LINT)
            text = page.evaluate("document.body.innerText")
            page.pdf(path=str(out), prefer_css_page_size=True, print_background=True,
                     outline=kind != "deck", tagged=True)
        finally:
            page.close()
        return problems, text
