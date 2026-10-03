"""Deck page helpers, so a slides.py holds only its content.

    from publishing.page import Deck
    d = Deck(__file__, "topic-v1")
    d.title("Kicker", "Headline", "Standfirst", ["<b>Point.</b> ...", ...], "footer source")
    d.slide("Kicker", "Headline", "Standfirst", body_html, "source line")
    d.slide("Questions", "...", "", d.q(1, "Title", "Ask", "Recommendation", "What it changes"))
    TITLE, S = d.TITLE, d.S

Page numbers are automatic: the footer's total is filled in at build time. A slides.py that
defines its own helpers (TITLE, S and optionally TOTAL) builds unchanged.
"""
import html
from pathlib import Path

TOTAL = "%%TOTAL%%"  # replaced with the page count at build time


def esc(text: str) -> str:
    return html.escape(text, quote=False)


class Deck:
    def __init__(self, here, title: str, credit: str = ""):
        self.here = Path(here).resolve()
        if self.here.is_file():
            self.here = self.here.parent
        self.TITLE = title
        self.credit = credit
        self.S: list[str] = []

    def foot(self, n: int, src: str = "") -> str:
        return f'<div class="rule"></div><div class="foot"><span>{src}</span><span>{n} / {TOTAL}</span></div>'

    def title(self, kicker: str, h1: str, h2: str = "", points=(), src: str = "", cls: str = "short") -> str:
        n = len(self.S) + 1
        items = "".join(f"<li>{p}</li>" for p in points)
        page = (f'<section class="slide title {cls}"><div class="kicker">{kicker}</div><h1>{h1}</h1>'
                + (f"<h2>{h2}</h2>" if h2 else "") + (f"<ol>{items}</ol>" if items else "")
                + f"{self.foot(n, src)}</section>")
        self.S.append(page)
        return page

    def slide(self, kicker: str, h1: str, h2: str = "", body: str = "", src: str = "", cls: str = "") -> str:
        n = len(self.S) + 1
        page = (f'<section class="slide {cls}"><div class="kicker">{kicker}</div><h1>{h1}</h1>'
                + (f"<h2>{h2}</h2>" if h2 else "") + f'<div class="body">{body}</div>{self.foot(n, src)}</section>')
        self.S.append(page)
        return page

    @staticmethod
    def q(n: int, title: str, ask: str, rec: str, chg: str) -> str:
        """The captain-question card: the question, a recommendation, and what the answer changes."""
        return (f'<div class="q"><h3><span>{n}.</span> {title}</h3><p>{ask}</p>'
                f"<p><b>Recommendation.</b> {rec}</p><p><b>What the answer changes.</b> {chg}</p></div>")

    @staticmethod
    def card(h3: str, body: str, style: str = "") -> str:
        st = f' style="{style}"' if style else ""
        return f'<div class="card"{st}><h3>{h3}</h3>{body}</div>'

    def svg(self, name: str) -> str:
        """Inline an SVG from the source folder (drop any XML prolog)."""
        s = (self.here / name).read_text()
        return s[s.index("<svg"):]

    def shot(self, img: str, cap: str, style: str = "") -> str:
        credit = f" · {self.credit}" if self.credit else ""
        st = f' style="{style}"' if style else ""
        return f'<div class="shot"{st}><img src="img/{img}"><div class="cap">{cap}{credit}</div></div>'
