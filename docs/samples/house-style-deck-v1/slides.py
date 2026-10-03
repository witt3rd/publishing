"""The house deck: 1920x1080 slides, one diagram, numbered questions. Build: publishing build docs/samples/house-style-deck-v1"""
from publishing.page import Deck

d = Deck(__file__, "house-style-deck-v1")

d.title("Publishing · the house deck", "One look for every report, from one pinned tool",
        "Decks, memos and long documents share one theme, one set of vendored fonts and one Chromium "
        "render. A repo states the version it builds with, and CI proves every PDF rebuilds from its source.",
        ["<b>The deck</b> is pages of HTML written in Python, at 1920 by 1080, for findings and designs.",
         "<b>The memo</b> is portrait markdown with a title block, tables and figures.",
         "<b>The document</b> is long-form markdown with a cover, contents and running header.",
         "<b>Every build</b> runs a layout lint and a text scan before it writes a PDF."],
        "A sample built by this repo's own CI")

d.slide("The idea", "Sources live in the repo; the tool owns the look",
        "A repo holds its sources and the PDFs built from them. The tool holds the theme, the fonts and the render.",
        f'<div class="diagram" style="width:1560px; margin:30px auto 0">{d.svg("diagram.svg")}</div>',
        "Diagram: inline SVG in the house palette")

d.slide("What a build checks", "Nothing reaches a PDF without passing the lint and the scan",
        "A problem stops the build; the PDF is not written.",
        '<table><tr><th style="width:26%">Check</th><th>Fails when</th></tr>'
        '<tr><td class="k">Layout</td><td>Content runs into the footer, a heading overlaps the body, or anything leaves its page (deck); '
        'a table, code block or figure is wider than the text column (memo, document).</td></tr>'
        '<tr><td class="k">Fonts</td><td>A glyph is outside the vendored faces, or any host font is embedded, so another machine would break lines differently.</td></tr>'
        '<tr><td class="k">Secrets</td><td>A token, key, private key block, e-mail address or home path appears in the text.</td></tr>'
        '<tr><td class="k">Words</td><td>The repo\'s own private words appear (from its docs/report.toml), or a relative day word that goes stale.</td></tr>'
        '<tr><td class="k">Rebuild</td><td>The committed PDF has different words or a different page count from a fresh build (CI).</td></tr></table>',
        "Source: the publishing build and check commands")

d.slide("Questions", "A deck ends with the decisions it needs", "Each question carries a recommendation and what the answer changes.",
        '<div class="stack">'
        + d.q(1, "Adopt the shared tool in the next repo?", "Pin the version in docs/report.toml and add the CI snippet.",
              "Yes, starting with the repo that next produces a report.", "Whether its PDFs gain a rebuild check and the house look.")
        + d.q(2, "Move older reports?", "Rebuild existing reports under the tool, or leave them as they are.",
              "New reports only, unless an old one is revised.", "How much rework the first rollout carries.")
        + "</div>",
        "Questions are numbered across the deck")

TITLE, S = d.TITLE, d.S
