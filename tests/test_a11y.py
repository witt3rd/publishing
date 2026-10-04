from pathlib import Path

import pytest

pytest.importorskip("pypdf")
from pypdf import PdfWriter

from publishing import a11y
from publishing.cli import main

SAMPLES = Path(__file__).parent.parent / "docs" / "samples"


@pytest.mark.parametrize("name,kind", [("deck", "deck"), ("memo", "memo"), ("document", "document")])
def test_house_samples_pass(name, kind):
    assert a11y.check(SAMPLES / f"house-style-{name}-v1.pdf", kind=kind)[0] == []


def bare(tmp_path, pages=2):
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(200, 200)
    out = tmp_path / "bare.pdf"
    with out.open("wb") as f:
        w.write(f)
    return out


def test_untagged_pdf_names_each_problem(tmp_path):
    problems = a11y.check(bare(tmp_path), kind="memo")[0]
    text = "\n".join(problems)
    for needle in ("not tagged", "no structure tree", "no document language", "no title", "/DisplayDocTitle", "no bookmarks"):
        assert needle in text


def test_cli_exit_codes(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["publishing", "a11y", str(SAMPLES / "house-style-memo-v1.pdf")])
    assert main() == 0
    monkeypatch.setattr("sys.argv", ["publishing", "a11y", str(bare(tmp_path))])
    assert main() == 1
    assert "problem(s)" in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["publishing", "a11y", str(tmp_path / "nope.pdf")])
    with pytest.raises(SystemExit) as e:
        main()
    assert e.value.code == 2


def test_figure_without_alt_is_advice_not_failure():
    problems, advice = a11y.check(SAMPLES / "house-style-memo-v1.pdf", kind="memo")
    assert problems == [] and any("alternate text" in a for a in advice)
