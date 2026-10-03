"""Markdown to page HTML for the memo and document formats.

Pandoc-flavoured where reports already rely on it: YAML-style front matter (flat key: value),
fenced divs (`::: {.summary}`, `::: q`), heading attributes (`# Title {#id .newpage}`), pipe
tables with a `: caption` paragraph after them, an image alone in a paragraph as a captioned
figure, footnotes, definition lists, smart punctuation and highlighted code fences.
"""
import html
import re
from dataclasses import dataclass, field

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.container import container_plugin
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.footnote import footnote_plugin
from pygments import highlight as pyg_highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

ATTRS = re.compile(r"\s*\{([^{}]*)\}\s*$")


@dataclass
class Page:
    """A parsed markdown source, ready to wrap in the page template."""
    meta: dict
    title: str  # HTML
    subtitle: str  # HTML
    body: str  # HTML
    headings: list = field(default_factory=list)  # (level, id, html) of every body heading outside divs
    top: int = 1  # the top heading level in the body
    has_cover: bool = False  # the body brings its own ::: cover block


def front_matter(src: str) -> tuple[dict, str]:
    if not src.startswith("---\n"):
        return {}, src
    m = re.search(r"^(?:---|\.\.\.)[ \t]*$", src[4:], re.M)
    if not m:
        return {}, src
    meta = {}
    for line in src[4:4 + m.start()].splitlines():
        k, sep, v = line.partition(":")
        if sep and k.strip() and not k.startswith((" ", "\t", "#")):
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            meta[k.strip().lower()] = v
    return meta, src[4 + m.end():].lstrip("\n")


def parse_attrs(spec: str) -> tuple[str | None, list[str]]:
    ident, classes = None, []
    for part in spec.split():
        if part.startswith("#"):
            ident = part[1:]
        elif part.startswith("."):
            classes.append(part[1:])
        elif "=" not in part:
            classes.append(part)
    return ident, classes


def slug(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower(), flags=re.U)
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return s or "section"


def _highlight(code: str, lang: str, _attrs) -> str:
    try:
        lexer = get_lexer_by_name(lang.strip().split()[0]) if lang.strip() else None
    except ClassNotFound:
        lexer = None
    if lexer is None:
        return ""  # markdown-it escapes and wraps it
    body = pyg_highlight(code, lexer, HtmlFormatter(nowrap=True))
    return f'<pre class="hl"><code class="language-{html.escape(lang)}">{body}</code></pre>'


def _div_render(self, tokens, idx, _options, _env):
    tok = tokens[idx]
    if tok.nesting != 1:
        return "</div>\n"
    info = tok.info.strip()
    inner = info[1:-1] if info.startswith("{") and info.endswith("}") else info
    ident, classes = parse_attrs(inner)
    if "question" in classes:
        classes.append("q")
    attrs = f' id="{html.escape(ident)}"' if ident else ""
    return f'<div class="{html.escape(" ".join(classes))}"{attrs}>\n'


def _engine() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": True, "typographer": True, "highlight": _highlight})
    md.enable(["table", "strikethrough", "replacements", "smartquotes"])
    md.use(footnote_plugin).use(deflist_plugin)
    md.use(container_plugin, "div", validate=lambda params, *_: bool(params.strip()), render=_div_render)
    return md


def _apply_heading_attrs(tokens: list[Token]) -> None:
    for i, tok in enumerate(tokens):
        if tok.type != "heading_open":
            continue
        inline = tokens[i + 1]
        m = ATTRS.search(inline.content)
        if not m:
            continue
        ident, classes = parse_attrs(m.group(1))
        inline.content = inline.content[:m.start()]
        last = inline.children[-1] if inline.children else None
        if last is not None and last.type == "text":
            last.content = ATTRS.sub("", last.content)
        if ident:
            tok.attrSet("id", ident)
        if classes:
            tok.attrSet("class", " ".join(classes))


def _figures(md: MarkdownIt, tokens: list[Token], env) -> list[Token]:
    out, i = [], 0
    while i < len(tokens):
        t = tokens[i]
        if (t.type == "paragraph_open" and i + 2 < len(tokens) and tokens[i + 1].type == "inline"
                and tokens[i + 2].type == "paragraph_close"):
            kids = [c for c in tokens[i + 1].children or [] if not (c.type == "text" and not c.content.strip())]
            if len(kids) == 1 and kids[0].type == "image":
                img = kids[0]
                cap = md.renderer.renderInline(img.children or [], md.options, env)
                src = html.escape(img.attrGet("src") or "")
                alt = html.escape(img.content or "")
                fig = Token("html_block", "", 0)
                fig.content = (f'<figure><img src="{src}" alt="{alt}">'
                               + (f"<figcaption>{cap}</figcaption>" if cap.strip() else "") + "</figure>\n")
                out.append(fig)
                i += 3
                continue
        out.append(t)
        i += 1
    return out


def parse(src: str, *, toc_levels: int = 2) -> Page:
    meta, body = front_matter(src)
    md = _engine()
    env: dict = {}
    tokens = md.parse(body, env)
    _apply_heading_attrs(tokens)

    title = html.escape(meta.get("title", ""))
    subtitle = html.escape(meta.get("subtitle", ""))
    if not title and tokens and tokens[0].type == "heading_open" and tokens[0].tag == "h1":
        h1s = sum(1 for t in tokens if t.type == "heading_open" and t.tag == "h1")
        if h1s == 1:  # the only h1 is the title; h2 is then the top section level
            title = md.renderer.renderInline(tokens[1].children, md.options, env)
            tokens = tokens[3:]
            # an all-emphasis paragraph straight after the title is its subtitle
            if (not subtitle and len(tokens) >= 3 and tokens[0].type == "paragraph_open"
                    and tokens[1].children and tokens[1].children[0].type == "em_open"
                    and tokens[1].children[-1].type == "em_close"
                    and sum(1 for c in tokens[1].children if c.type == "em_open") == 1):
                subtitle = md.renderer.renderInline(tokens[1].children[1:-1], md.options, env)
                tokens = tokens[3:]
    tokens = _figures(md, tokens, env)

    used, headings, depth = set(), [], 0
    levels = [int(t.tag[1]) for t in tokens if t.type == "heading_open"]
    top = min(levels) if levels else 1
    has_cover = False
    for i, t in enumerate(tokens):
        if t.type == "container_div_open":
            depth += 1
            if "cover" in t.info:
                has_cover = True
        elif t.type == "container_div_close":
            depth -= 1
        elif t.type == "heading_open":
            text = tokens[i + 1].content
            ident = t.attrGet("id") or slug(text)
            base, n = ident, 1
            while ident in used:
                ident, n = f"{base}-{n}", n + 1
            used.add(ident)
            t.attrSet("id", ident)
            level = int(t.tag[1])
            if depth == 0 and level < top + toc_levels:
                headings.append((level - top + 1, ident, md.renderer.renderInline(tokens[i + 1].children,
                                                                                     md.options, env)))
    rendered = md.renderer.render(tokens, md.options, env)
    rendered = re.sub(r"</table>\s*<p>(?:Table)?: (.*?)</p>", r'</table>\n<p class="table-caption">\1</p>',
                      rendered, flags=re.S)
    return Page(meta=meta, title=title, subtitle=subtitle, body=rendered, headings=headings, top=top,
                has_cover=has_cover)
