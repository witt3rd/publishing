"""Explainer deck helpers: one source, a PDF and an editable PPTX (README "Explainer decks").

    from publishing.explainer import Explainer
    x = Explainer(__file__, "Title of the deck", author="Example Author")
    x.title("Kicker", "Title", "One-line subtitle", notes="What the presenter says.")
    x.statement("The point", "Headline", ["<b>Idea.</b> One per line"], src="Where it comes from", notes="...")
    x.diagram("The loop", "Headline", "diagram.svg", takeaway=("In short", "The one sentence to keep."), src="...", notes="...")
    x.cards("Three jobs", "Headline", [("Name", "Words", "accent"), ...], lesson=("Why", "Words"), notes="...")
    x.agenda("Nine parts", "Headline", [("What it is", "One line of words"), ("How it works", "...")], notes="...")
    x.story("A lesson", "Headline", what="...", why="...", fix="...", lesson="...", notes="...")
    x.map("The mapping", "Headline", ("Ours", "Theirs", "Same?"), [("a", "b", "same", "same idea")], notes="...")
    x.contrast("Before and after", "Headline", ("Before", "Now"), "old way", "new way", [("Case", "text")], notes="...")
    x.twocol("Two sides", "Headline", ("Left", "red", ["point"]), ("Right", "hit", ["point"]), notes="...")
    x.section("Part two", "Headline", "Subtitle", number="2", notes="...")
    x.quote("Said", "Headline", "The words", who="Someone", notes="...")
    x.closing("Closing", "Headline", "Subtitle", [("45x", "what it means")] * 3, notes="...")
    TITLE, S, NOTES, AUTHOR = x.TITLE, x.S, x.NOTES, x.AUTHOR

Every slide takes `notes`, the speaker notes (required: the build refuses a slide without them) and
`src`, the small print on the slide, which also ends the notes as `Source: ...`. Headings and labels
are escaped; paragraphs, points and cell text are HTML (`<b>`, `<span class='dim'>`) from the author's own
code. Colours are palette names (accent, detour, hit, missed, red, ink, ink2, muted) or a `#hex`.
"""
import html
from pathlib import Path

TOTAL = "%%TOTAL%%"  # replaced with the slide count at build time
PALETTE = {"accent", "detour", "hit", "approx", "missed", "red", "ink", "ink2", "muted", "unreached"}


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def _color(c: str) -> str:
    if c in PALETTE:
        return f"var(--{c})"
    if len(c) in (4, 7) and c.startswith("#") and all(h in "0123456789abcdefABCDEF" for h in c[1:]):
        return c
    raise ValueError(f"colour {c!r}: a palette name ({', '.join(sorted(PALETTE))}) or #hex")


class Explainer:
    def __init__(self, here, title: str, author: str = ""):
        self.here = Path(here).resolve()
        if self.here.is_file():
            self.here = self.here.parent
        self.TITLE = title
        self.AUTHOR = author
        self.S: list[str] = []
        self.NOTES: list[str] = []

    # -------------------------------------------------------------- furniture
    def _add(self, page: str, notes: str, src: str) -> str:
        if not notes or not notes.strip():
            raise ValueError(f"slide {len(self.S) + 1}: notes are required (what the presenter says)")
        self.NOTES.append(notes.strip() + (f"\n\nSource: {src}" if src else ""))
        self.S.append(page)
        return page

    def _foot(self, src: str) -> str:
        n = len(self.S) + 1
        s = f'<span class="src"><b>Source:</b> {esc(src)}</span>' if src else '<span class="src"></span>'
        return f'<div class="rule"></div><div class="foot">{s}<span class="num">{n} / {TOTAL}</span></div>'

    @staticmethod
    def _head(kicker: str, title: str, sub: str = "", first: bool = False) -> str:
        cls = ' class="first"' if first else ""
        return (f'<div class="kicker">{esc(kicker)}</div><h1{cls}>{esc(title)}</h1>'
                + (f"<h2>{esc(sub)}</h2>" if sub else ""))

    # -------------------------------------------------------------- slides
    def title(self, kicker, title, sub="", presenter="", *, src="", notes=""):
        page = (f'<section class="slide title">{self._head(kicker, title, sub, True)}'
                + (f'<div class="presenter">{esc(presenter)}</div>' if presenter else "")
                + f"{self._foot(src)}</section>")
        return self._add(page, notes, src)

    def section(self, kicker, title, sub="", number="", *, src="", notes=""):
        page = (f'<section class="slide section">'
                + (f'<div class="big">{esc(number)}</div>' if number else "")
                + f"{self._head(kicker, title, sub)}{self._foot(src)}</section>")
        return self._add(page, notes, src)

    def statement(self, kicker, title, points, sub="", *, src="", notes=""):
        pts = "".join(f"<li>{p}</li>" for p in points)
        top = 330 if sub else 300
        page = (f'<section class="slide">{self._head(kicker, title, sub)}<div class="body" style="top:{top}px">'
                f'<ul class="points big">{pts}</ul></div>{self._foot(src)}</section>')
        return self._add(page, notes, src)

    def quote(self, kicker, title, words, who="", *, src="", notes=""):
        page = (f'<section class="slide">{self._head(kicker, title)}<div class="body"><div class="quote">{words}</div>'
                + (f'<div class="who">{esc(who)}</div>' if who else "") + f"</div>{self._foot(src)}</section>")
        return self._add(page, notes, src)

    def diagram(self, kicker, title, svg, sub="", *, takeaway=None, top=None, src="", notes=""):
        """`svg`: a file in the source folder, inlined so its text uses the vendored fonts. `takeaway`: (label, words),
        a dark bar under the diagram (the cards' lesson bar) that says what to take from it."""
        text = (self.here / svg).read_text()
        text = text[text.index("<svg"):]
        top = top if top is not None else (300 if sub else 250)
        bar = f'<div class="lesson"><span>{esc(takeaway[0])}</span>{takeaway[1]}</div>' if takeaway else ""
        page = (f'<section class="slide">{self._head(kicker, title, sub)}'
                f'<div class="diagram{" barred" if takeaway else ""}" style="top:{top}px">{text}</div>{bar}{self._foot(src)}</section>')
        return self._add(page, notes, src)

    def cards(self, kicker, title, cards, sub="", *, cols=3, lesson=None, top=None, src="", notes=""):
        """`cards`: (heading, words, colour) tuples; `lesson`: (label, words), a bar under the cards."""
        body = "".join(f'<div class="card" style="border-top:10px solid {_color(c)}">'
                       f'<h3 style="color:{_color(c)}">{esc(h)}</h3><p>{p}</p></div>' for h, p, c in cards)
        top = top if top is not None else (340 if sub else 280)
        bar = f'<div class="lesson"><span>{esc(lesson[0])}</span>{lesson[1]}</div>' if lesson else ""
        page = (f'<section class="slide">{self._head(kicker, title, sub)}<div class="body cards{" lessoned" if lesson else ""}" '
                f'style="top:{top}px; grid-template-columns:repeat({cols},1fr)">{body}</div>{bar}{self._foot(src)}</section>')
        return self._add(page, notes, src)

    def agenda(self, kicker, title, items, sub="", *, cols=3, top=None, src="", notes=""):
        """The outline: numbered cards, `items` as (heading, words) tuples, numbered from 1 in order."""
        body = "".join(f'<div class="item"><div class="n">{i}</div><h3>{esc(h)}</h3><p>{p}</p></div>'
                       for i, (h, p) in enumerate(items, 1))
        top = top if top is not None else (340 if sub else 270)
        page = (f'<section class="slide">{self._head(kicker, title, sub)}<div class="body agenda" '
                f'style="top:{top}px; grid-template-columns:repeat({cols},1fr)">{body}</div>{self._foot(src)}</section>')
        return self._add(page, notes, src)

    def story(self, kicker, title, *, what, why, fix, lesson, sub="", top=330, src="", notes=""):
        """Three cards (what went wrong, why it got through, the rule now) and a lesson bar."""
        body = "".join(f'<div class="card {c}"><div class="tag">{tag}</div><p class="sp">{words}</p></div>'
                       for c, tag, words in (("what", "What went wrong", what), ("why", "Why it got through", why),
                                             ("fix", "The rule now", fix)))
        page = (f'<section class="slide">{self._head(kicker, title, sub)}<div class="body story" '
                f'style="top:{top}px; bottom:250px">{body}</div><div class="lesson"><span>Lesson</span>{esc(lesson)}</div>'
                f"{self._foot(src)}</section>")
        return self._add(page, notes, src)

    def map(self, kicker, title, head, rows, *, src="", notes=""):
        """A table of `rows`: (ours, theirs, chip colour class same|ahead|behind|differs, chip text)."""
        for r in rows:
            if r[2] not in ("same", "ahead", "behind", "differs"):
                raise ValueError(f"map chip {r[2]!r}: same, ahead, behind or differs")
        body = "".join(f'<tr><td class="ours">{esc(a)}</td><td class="arrow">→</td><td class="theirs">{esc(b)}</td>'
                       f'<td><span class="chip {c}">{esc(t)}</span></td></tr>' for a, b, c, t in rows)
        page = (f'<section class="slide">{self._head(kicker, title)}<div class="maptable"><table><thead><tr>'
                f'<th>{esc(head[0])}</th><th></th><th>{esc(head[1])}</th><th>{esc(head[2])}</th></tr></thead>'
                f"<tbody>{body}</tbody></table></div>{self._foot(src)}</section>")
        return self._add(page, notes, src)

    def contrast(self, kicker, title, tags, before, after, examples, *, src="", notes=""):
        """Before and after cards, and a row of `examples`: (heading, words)."""
        ex = "".join(f'<div class="ex"><div class="exh">{esc(h)}</div><div class="ext">{esc(t)}</div></div>'
                     for h, t in examples)
        page = (f'<section class="slide">{self._head(kicker, title)}<div class="body contrast">'
                f'<div class="card then-card"><div class="tag">{esc(tags[0])}</div><p>{esc(before)}</p></div>'
                f'<div class="card now-card"><div class="tag">{esc(tags[1])}</div><p>{esc(after)}</p></div></div>'
                f'<div class="exrow" style="grid-template-columns:repeat({len(examples)},1fr)">{ex}</div>'
                f"{self._foot(src)}</section>")
        return self._add(page, notes, src)

    def twocol(self, kicker, title, left, right, *, top=300, src="", notes=""):
        """Two cards: (heading, colour, [points]) each."""
        def col(c):
            h, colr, pts = c
            li = "".join(f"<li>{p}</li>" for p in pts)
            return (f'<div class="card" style="border-top:10px solid {_color(colr)}"><h3 style="color:{_color(colr)}">'
                    f'{esc(h)}</h3><ul class="points mid">{li}</ul></div>')
        page = (f'<section class="slide">{self._head(kicker, title)}<div class="body cards" style="top:{top}px; '
                f'grid-template-columns:1fr 1fr">{col(left)}{col(right)}</div>{self._foot(src)}</section>')
        return self._add(page, notes, src)

    def closing(self, kicker, title, sub, evidence, *, src="", notes=""):
        """The last slide: three big numbers, (figure, words) each."""
        ev = "".join(f'<div class="ev"><div class="evn">{esc(big)}</div><div class="evt">{t}</div></div>'
                     for big, t in evidence)
        page = (f'<section class="slide title closing">{self._head(kicker, title, sub)}'
                f'<div class="evrow">{ev}</div>{self._foot(src)}</section>')
        return self._add(page, notes, src)
