import pytest

from publishing.config import ConfigError, load


def test_defaults_without_a_file(tmp_path):
    cfg = load(tmp_path)
    assert cfg.path is None and cfg.paper == "letter" and cfg.days and cfg.format == "pdf"


def test_found_from_a_nested_folder(repo):
    (repo / "docs" / "notes" / "x-v1").mkdir()
    cfg = load(repo / "docs" / "notes" / "x-v1")
    assert cfg.root == repo.resolve() and cfg.project == "Fleet" and cfg.publish == {"notes": "Fleet/Notes"}


def test_documents_resolve_against_the_root(repo):
    (repo / "docs" / "report.toml").write_text(
        '[[document]]\nsource = "docs/spire.md"\npdf = "docs/Spire.pdf"\npaper = "a4"\ndays = false\n')
    cfg = load(repo)
    d = cfg.document_for(repo / "docs" / "spire.md")
    assert d.pdf == (repo / "docs" / "Spire.pdf").resolve() and d.paper == "a4" and d.days is False


def test_video_tolerance(repo):
    assert load(repo).tolerance == 40
    (repo / "docs" / "report.toml").write_text("[video]\ntolerance = 50\n")
    assert load(repo).tolerance == 50


@pytest.mark.parametrize("body", ['format = "docx"\n', 'paper = "legal"\n', "[[document]]\npdf = 'x.pdf'\n",
                                  "not toml =", '[video]\ntolerance = "high"\n'])
def test_bad_config_is_refused(repo, body):
    (repo / "docs" / "report.toml").write_text(body)
    with pytest.raises(ConfigError):
        load(repo)
