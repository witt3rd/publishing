"""Diagram sizing against the house exemplar (prospecta-explainer-v1): the figure box is 1760px wide, so a figure
drawn 1760 wide is shown at its own scale (0.14.0's 1680 box showed it at 0.95). See the PR for #46."""
import pytest

from publishing.build import deck_html
from publishing.explainer import Explainer

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1760 440"><rect width="1760" height="440" fill="#eee"/></svg>'


def measure(renderer, tmp_path, build, selectors):
    """Build one deck (`build(x)` adds slides), open it, and return each selector's boxes (x, y, w, h) on slide 1."""
    (tmp_path / "d.svg").write_text(SVG)
    x = Explainer(tmp_path, "T")
    build(x)
    html = tmp_path / "deck.html"
    html.write_text(deck_html(x.S, tmp_path, "T", "explainer.css"), encoding="utf-8")
    page = renderer._browser.new_page(viewport={"width": 1920, "height": 1080})
    try:
        page.goto(html.as_uri(), wait_until="load")
        page.evaluate("document.fonts.ready.then(() => true)")
        return {sel: page.evaluate(
            """(sel) => { const s = document.querySelector('.slide').getBoundingClientRect();
              return [...document.querySelectorAll('.slide ' + sel)].map((e) => { const r = e.getBoundingClientRect();
              return [r.left - s.left, r.top - s.top, r.width, r.height].map((v) => Math.round(v * 10) / 10); }); }""", sel)
            for sel in selectors}
    finally:
        page.close()


def test_a_figure_drawn_1760_wide_shows_at_its_own_scale(renderer, tmp_path):
    m = measure(renderer, tmp_path, lambda x: x.diagram("K", "T", "d.svg", notes="n"), [".diagram", ".diagram svg"])
    assert m[".diagram"][0][:3] == [80, 250, 1760]
    svg = m[".diagram svg"][0]
    assert svg[0] == 80 and svg[2] == 1760 and svg[3] >= 440  # width-limited at scale 1 (a 1680 box gave 0.955)
