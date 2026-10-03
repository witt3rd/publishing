from publishing.markdown import front_matter, parse


def test_front_matter_is_flat_key_value():
    meta, body = front_matter('---\ntitle: "The plan"\nlang: en\n---\n\nBody\n')
    assert meta == {"title": "The plan", "lang": "en"}
    assert body == "Body\n"


def test_single_h1_is_the_title_and_emphasis_the_subtitle():
    p = parse("# Spire — the thought\n\n*status: normative*\n\n## The question\n\nText.\n\n### Sub\n\n#### Deep\n")
    assert p.title == "Spire — the thought"
    assert p.subtitle == "status: normative"
    assert p.top == 2
    assert [(lvl, i) for lvl, i, _ in p.headings] == [(1, "the-question"), (2, "sub")]
    assert "<h1" not in p.body


def test_several_h1s_are_sections():
    p = parse("---\ntitle: T\n---\n# One\n\n# Two\n")
    assert p.title == "T" and p.top == 1 and len(p.headings) == 2


def test_heading_attributes_and_unique_ids():
    p = parse("## A {#first .newpage}\n\n## A\n\n## A\n")
    assert '<h2 id="first" class="newpage">A</h2>' in p.body
    assert [i for _, i, _ in p.headings] == ["first", "a", "a-1"]


def test_fenced_divs_and_question_cards():
    p = parse("::: {.summary}\nShort.\n:::\n\n::: q\n### 1. Ask?\n:::\n")
    assert '<div class="summary">' in p.body and '<div class="q">' in p.body
    assert p.headings == []  # headings inside blocks stay out of the contents


def test_figure_and_table_caption():
    p = parse("![**Figure 1.** The map](fig.svg)\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n: Source: the audit.\n")
    assert '<figure><img src="fig.svg"' in p.body
    assert "<figcaption><strong>Figure 1.</strong> The map</figcaption>" in p.body
    assert '<p class="table-caption">Source: the audit.</p>' in p.body


def test_code_is_highlighted_and_unknown_languages_are_plain():
    p = parse("```python\ndef f(): pass\n```\n\n```nosuchlang\nx < y\n```\n")
    assert '<pre class="hl"><code class="language-python">' in p.body and '<span class="k">def</span>' in p.body
    assert "x &lt; y" in p.body


def test_lists_may_follow_a_paragraph_directly():
    p = parse("Items:\n- one\n- two\n")
    assert "<ul>" in p.body


def test_pandoc_attributes_on_images_and_spans():
    p = parse("![Cap](fig.svg){width=76%}\n\nPick [Recommended]{.rec} now.\n")
    assert '<figure style="width:76%"><img src="fig.svg"' in p.body
    assert '<span class="rec">Recommended</span>' in p.body
