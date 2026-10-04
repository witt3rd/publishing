---
title: The house document
subtitle: Long-form writing with a cover, contents, running header and page numbers
kicker: Publishing · the house document
footer: house-style-document-v1
numbered: true
toc: 2
---

## Purpose

A document is for long, normative or reference writing: a contract, a specification, a handbook. It is markdown, like a memo, and it adds a cover page with the contents, a running header with the title, and page numbers out of the total. The contents are filled in after a first render, so each entry carries the page its heading landed on.

The top-level sections are `##` headings. When the file has no front-matter title, its single `#` heading becomes the title, and an italic paragraph straight after it becomes the subtitle.

## Typography

Reading text is Noto Serif at 10.5 points on a 1.5 line, in a column narrow enough to read comfortably. Headings are Noto Sans, and each top-level section opens with a rule in the accent colour. Quotation marks, dashes and ellipses are set typographically: "quoted", an en dash 1–2, an em dash — like this, and an ellipsis…

> A block quotation sits on an accent rule, in the secondary ink.

### Lists

1. Ordered items number in the accent colour.
2. Items may hold **bold**, *italic* and `code`.
   - Nested items indent under their parent.
   - Lists may follow a paragraph without a blank line.

Term
: A definition list, for a lexicon or a glossary.

## Tables

| Paper | Size | Text column |
|---|---|---|
| Letter | 8.5 × 11 in | 175.9 mm |
| A4 | 210 × 297 mm | 170 mm |

: Choose the paper in docs/report.toml (`paper`) or per document.

A table's header row repeats when the table crosses a page, and no row is split across pages.

## Code

Fenced code is highlighted and wraps rather than leaving the column:

```python
from publishing.page import Deck

d = Deck(__file__, "topic-v1")
d.slide("Kicker", "Headline", "Standfirst", "<p>Body</p>", "Source line")
TITLE, S = d.TITLE, d.S
```

```sh
publishing build docs/spire.md --output docs/Spire.pdf --format document
publishing check
```

## Long-document options

Two front-matter keys shape a long document. `numbered: true` numbers the sections 1, 1.1, 1.1.1 in the headings and the contents alike; only top-level headings count, so the heading of a summary box stays plain. `toc: 1`, `2` (the default) or `3` sets how many heading levels the contents list, and `toc: false` leaves the contents out. This sample sets both.

## Page furniture

The cover carries no header. Every later page carries the title on the left and the kicker on the right at the top, and the footer text and the page number out of the total at the bottom. PDF bookmarks follow the headings.

### A fixed path

A repo whose document has a fixed name lists it in `docs/report.toml` as a `[[document]]` with its `source` and `pdf`. `publishing check` then rebuilds and compares it like any other.
