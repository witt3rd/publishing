"""Slides for {name}.pdf. Build: publishing build {rel}"""
from publishing.page import Deck

d = Deck(__file__, "{name}")

d.title("{kicker}", "The answer, in one line",
        "One sentence that says what this report is and what it asks of the reader.",
        ["<b>The finding.</b> Plain English, one idea per line.",
         "<b>The recommendation.</b> What we propose, and why.",
         "<b>The ask.</b> The numbered questions on the last page."],
        "Source: say where the evidence comes from")

d.slide("The idea", "One simple diagram", "What the reader should see in it.",
        f'<div class="diagram" style="width:1500px; margin:0 auto">{d.svg("diagram.svg")}</div>',
        "Diagram: drawn for this report")

d.slide("Questions", "What we need decided", "Each question has a recommendation and what the answer changes.",
        '<div class="stack">'
        + d.q(1, "The first question?", "What exactly is being asked.", "What we recommend.", "What changes with each answer.")
        + "</div>")

TITLE, S = d.TITLE, d.S
