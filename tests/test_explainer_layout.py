"""Explainer slide layout against the house exemplar (prospecta-explainer-v1): the geometry of each kind, measured in
Chromium on the 1920x1080 slide. The numbers are the exemplar's, read from its PDF (docs in the PR for #46)."""
import pytest

from publishing.build import deck_html
from publishing.explainer import Explainer


def measure(renderer, tmp_path, build, selectors):
    """Build one deck (`build(x)` adds slides), open it, and return each selector's boxes (x, y, w, h) on slide 1."""
    x = Explainer(tmp_path / "explainer.py", "T")
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


ITEMS = [("What it is", "Memory for beings and agents, one bank each, on Postgres."),
         ("How it works", "What is written for every note, and the plan for reading."),
         ("Every technique", "Search, filters, graph, fusion, reranking, answers, sets."),
         ("Scoring", "How a score is built: hit@1, hit@10, cover@10."),
         ("Four questions", "A lookup, a paraphrase, a dated question, a set."),
         ("Why hybrid wins", "The ladder from 0.72 to 0.99."),
         ("Tradeoffs", "Cost, latency, write-time cost, hard lessons."),
         ("Improvements", "What is still weak, said plainly."),
         ("Plugging in", "Rung and Hermes, through thin providers.")]


def test_agenda_cards_match_the_exemplar_grid(renderer, tmp_path):
    m = measure(renderer, tmp_path, lambda x: x.agenda("Nine parts", "From what it is to how it is measured", ITEMS,
                                                       notes="n"), [".agenda .item", ".agenda .n", ".agenda h3"])
    cards = m[".agenda .item"]
    assert len(cards) == 9
    # three columns of 545.3 with a 22px gap, from x=120; rows start at y=270 and keep the exemplar's heights
    assert [c[0] for c in cards[:3]] == pytest.approx([120, 687.3, 1254.7], abs=1)
    assert all(c[2] == pytest.approx(545.3, abs=1) for c in cards)
    assert [c[1] for c in cards[::3]] == pytest.approx([270, 498.5, 727], abs=3)
    assert [c[3] for c in cards[::3]] == pytest.approx([207, 207, 176], abs=3)
    assert m[".agenda .n"][0][3] == 54 and m[".agenda h3"][0][3] == pytest.approx(41, abs=1)


def test_a_single_row_of_cards_is_compact_not_stretched(renderer, tmp_path):
    m = measure(renderer, tmp_path, lambda x: x.cards("Three jobs", "Three volunteers", [
        ("A", "Words " * 12, "accent"), ("B", "Words " * 12, "detour"), ("C", "Words " * 12, "hit")],
        lesson=("Why", "Words"), notes="n"), [".cards .card"])
    cards = m[".cards .card"]
    assert len(cards) == 3 and all(c[3] < 340 for c in cards)  # the exemplar's cards are ~290 tall
    assert len({c[3] for c in cards}) == 1  # equal heights within the row


def test_story_and_two_column_cards_are_compact(renderer, tmp_path):
    m = measure(renderer, tmp_path, lambda x: x.story("K", "T", what="Short.", why="Short.", fix="Short.",
                                                      lesson="L", notes="n"), [".story .card"])
    assert all(c[3] < 340 for c in m[".story .card"])
    m = measure(renderer, tmp_path, lambda x: x.twocol("K", "T", ("L", "hit", ["a", "b"]), ("R", "red", ["a", "b"]),
                                                       notes="n"), [".cards .card"])
    assert all(c[3] < 340 for c in m[".cards .card"])
