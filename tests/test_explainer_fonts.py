"""The ExtraBold weight is vendored, so the numerals (weight 800) render in it rather than falling back to Bold (#46)."""


def test_extrabold_face_is_vendored_and_used(renderer, tmp_path):
    from publishing.build import deck_html
    from publishing.explainer import Explainer
    x = Explainer(tmp_path, "T")
    x.section("Part", "Headline", number="2", notes="n")
    html = tmp_path / "deck.html"
    html.write_text(deck_html(x.S, tmp_path, "T", "explainer.css"), encoding="utf-8")
    page = renderer._browser.new_page(viewport={"width": 1920, "height": 1080})
    try:
        page.goto(html.as_uri(), wait_until="load")
        page.evaluate("document.fonts.ready.then(() => true)")
        loaded = page.evaluate("[...document.fonts].filter(f => f.status === 'loaded').map(f => f.family + ' ' + f.weight)")
    finally:
        page.close()
    assert "Publishing Sans 800" in loaded
