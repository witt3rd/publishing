"""The explainer cover against the house exemplar (prospecta-explainer-v1 page 1), measured in Chromium on the
1920x1080 slide. The numbers are the exemplar's, read from its PDF (see the PRs for #46)."""
import pytest

from publishing.build import deck_html
from publishing.explainer import COVER_MIN, Explainer, cover_size

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


def test_cover_title_size_follows_its_length():
    assert cover_size("Prospecta") == 200 and cover_size("A") == 200
    assert COVER_MIN < cover_size("Title of the explainer") < 200
    assert cover_size("How a community tool shed runs") == COVER_MIN and cover_size("x" * 200) == COVER_MIN


def test_cover_matches_the_exemplar(renderer, tmp_path):
    m = measure(renderer, tmp_path, lambda x: x.title("Prospecta", "Prospecta", "Long-term memory for beings and agents.",
                                                      "An explainer for a reader new to memory systems", notes="n"),
                ["h1", "h2", ".presenter"])
    h1 = m["h1"][0]
    assert h1[0] == 160 and h1[3] == pytest.approx(216, abs=1)  # 200px type on a 1.08 line
    assert h1[1] == pytest.approx(170 + 150, abs=2)  # kicker box (to y 170) then the exemplar's gap; bbox top 291
    assert m["h2"][0][1] == pytest.approx(h1[1] + 216 + 40, abs=2)
    assert m[".presenter"][0][0] == 160 and m[".presenter"][0][1] + m[".presenter"][0][3] == pytest.approx(1080 - 150, abs=1)


def test_a_long_cover_title_keeps_the_old_position(renderer, tmp_path):
    m = measure(renderer, tmp_path, lambda x: x.title("K", "How a community tool shed runs", "Sub", notes="n"), ["h1"])
    assert m["h1"][0][1] == pytest.approx(170 + 170, abs=2)
