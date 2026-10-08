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


def test_section_title_sits_below_the_kicker_and_the_source_label_reads(renderer, tmp_path):
    m = measure(renderer, tmp_path, lambda x: x.section("Part two", "Starting your own", "Sub", number="2", src="S",
                                                        notes="n"), ["h1", ".kicker"])
    assert m["h1"][0][1] - (m[".kicker"][0][1] + m[".kicker"][0][3]) >= 115  # the exemplar gap (~205px from the kicker top)


def test_sub_lines_move_quote_and_two_column_bodies_down(renderer, tmp_path):
    a = measure(renderer, tmp_path, lambda x: x.twocol("K", "T", ("L", "hit", ["a"]), ("R", "red", ["b"]), notes="n"), [".cards"])
    b = measure(renderer, tmp_path, lambda x: x.twocol("K", "T", ("L", "hit", ["a"]), ("R", "red", ["b"]), sub="S", notes="n"),
                [".cards", "h2"])
    assert b[".cards"][0][1] == a[".cards"][0][1] + 40 and b["h2"]


def test_heatmap_cells_rows_and_outline(renderer, tmp_path):
    rows = [("Recall", "top-5", [(".41", .41), (".63", .63), (".88", .88)]),
            ("Cost", "", [(".90", .9), (".50", .5), (".20", .2)])]
    m = measure(renderer, tmp_path, lambda x: x.heatmap("K", "T", ["A", "B", "C"], rows, notes="n"),
                [".heatmap", ".hm-c", ".hm-c.best", ".hm-h.last"])
    assert m[".heatmap"][0][1] == 280
    assert len(m[".hm-c"]) == 6 and all(c[3] == 60 for c in m[".hm-c"])
    assert m[".hm-c.best"] == [m[".hm-c"][2], m[".hm-c"][3]]  # the row's strongest cell: last of row 1, first of row 2
    assert len(m[".hm-h.last"]) == 1


def test_heatmap_refuses_ragged_rows_and_bad_levels(tmp_path):
    from publishing.explainer import Explainer
    x = Explainer(tmp_path / "e.py", "T")
    with pytest.raises(ValueError, match="cells"):
        x.heatmap("K", "T", ["A", "B"], [("r", "", [("1", .5)])], notes="n")
    with pytest.raises(ValueError, match="level"):
        x.heatmap("K", "T", ["A"], [("r", "", [("1", 1.5)])], notes="n")


def test_twocol_outline_rims_the_whole_card(renderer, tmp_path):
    m = measure(renderer, tmp_path, lambda x: x.twocol("K", "T", ("Good", "hit", ["a"]), ("Weak", "red", ["b"]),
                                                       outline=True, notes="n"), [".card"])
    assert len(m[".card"]) == 2 and m[".card"][0][3] < 400  # compact, not stretched
    import re
    x = Explainer(tmp_path / "e.py", "T")
    x.twocol("K", "T", ("Good", "hit", ["a"]), ("Weak", "red", ["b"]), outline=True, notes="n")
    assert len(re.findall(r'style="border:4px solid var\(--(?:hit|red)\)"', x.S[0])) == 2 and "border-top:10px" not in x.S[0]
