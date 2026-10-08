"""Explainer slide layout against the house exemplar (prospecta-explainer-v1): the geometry of each kind, measured in
Chromium on the 1920x1080 slide. The numbers are the exemplar's, read from its PDF (see the PRs for #46)."""
import pytest

from publishing.build import deck_html
from publishing.explainer import Explainer

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1680 440"><rect width="1680" height="440" fill="#eee"/></svg>'


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


def test_diagram_takeaway_bar_matches_the_exemplar(renderer, tmp_path):
    m = measure(renderer, tmp_path, lambda x: x.diagram("What it is", "Memory", "d.svg", sub="One bank per being.",
                                                        takeaway=("In short", "A being retains notes."), notes="n"),
                [".diagram", ".diagram svg", ".lesson", ".lesson span"])
    # the exemplar's bar: x 120..1800, y 860..960 (the cards' lesson bar); the diagram box ends 30px above it
    assert m[".lesson"] == [[120, 860, 1680, 100]]
    top, height = m[".diagram"][0][1], m[".diagram"][0][3]
    assert (top, height) == (300, 530)  # the box ends at y 830, 30px above the bar
    svg = m[".diagram svg"][0]
    assert svg[1] >= top and svg[1] + svg[3] <= top + height + 0.5


def test_diagram_without_a_takeaway_has_no_bar(renderer, tmp_path):
    m = measure(renderer, tmp_path, lambda x: x.diagram("K", "T", "d.svg", notes="n"), [".diagram", ".lesson"])
    assert m[".lesson"] == [] and m[".diagram"][0][3] == pytest.approx(1080 - 112 - 250, abs=1)


def test_diagram_callout_band_sits_above_the_takeaway_bar(renderer, tmp_path):
    m = measure(renderer, tmp_path, lambda x: x.diagram("K", "T", "d.svg", takeaway=("In short", "Words."),
                                                        callout="Retain: write it down.", notes="n"),
                [".diagram", ".callout", ".lesson"])
    assert m[".lesson"] == [[120, 860, 1680, 100]]
    assert m[".callout"] == [[120, 796, 1680, 44]]  # 20px above the bar, 44px tall
    diagram = m[".diagram"][0]
    assert diagram[1] + diagram[3] <= 796 - 29  # the figure ends clear of the band


def test_diagram_callout_without_a_takeaway_sits_at_the_foot(renderer, tmp_path):
    m = measure(renderer, tmp_path, lambda x: x.diagram("K", "T", "d.svg", callout="Retain.", notes="n"),
                [".diagram", ".callout"])
    assert m[".callout"] == [[120, 916, 1680, 44]]
    assert m[".diagram"][0][1] + m[".diagram"][0][3] <= 916 - 29
