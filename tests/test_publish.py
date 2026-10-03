import pytest

from publishing.build import Source
from publishing.config import load
from publishing.publish import PublishError, publish


@pytest.fixture
def docs(tmp_path, monkeypatch):
    d = tmp_path / "Documents"
    monkeypatch.setenv("PUBLISHING_DOCUMENTS", str(d))
    return d


def built(repo, name="topic-v1", data=b"%PDF-1.7 one"):
    folder = repo / "docs" / "notes" / name
    folder.mkdir(exist_ok=True)
    (folder.parent / f"{name}.pdf").write_bytes(data)
    return Source("deck", folder, folder.parent / f"{name}.pdf")


def test_copies_then_is_a_noop(repo, docs):
    s = built(repo)
    cfg = load(repo)
    assert publish(s, cfg) == ("published", docs / "Fleet/Notes/topic-v1.pdf")
    assert publish(s, cfg)[0] == "already published"


def test_refuses_to_overwrite_different_bytes(repo, docs):
    s = built(repo)
    cfg = load(repo)
    publish(s, cfg)
    s.pdf.write_bytes(b"%PDF-1.7 two")
    with pytest.raises(PublishError, match="-v2"):
        publish(s, cfg)
    assert (docs / "Fleet/Notes/topic-v1.pdf").read_bytes() == b"%PDF-1.7 one"


@pytest.mark.parametrize("name", ["Topic-v1", "topic", "topic_v1", "topic-v1-final"])
def test_names_are_kebab_case_and_versioned(repo, docs, name):
    with pytest.raises(PublishError, match="kebab-case"):
        publish(built(repo, name), load(repo))


def test_falls_back_to_the_project_folder(repo, docs):
    (repo / "docs" / "report.toml").write_text('project = "Rung"\n')
    assert publish(built(repo), load(repo))[1] == docs / "Rung/topic-v1.pdf"


def test_markdown_repos_refuse_pdfs(repo, docs):
    (repo / "docs" / "report.toml").write_text('project = "Animus"\nformat = "markdown"\n')
    with pytest.raises(PublishError, match="markdown"):
        publish(built(repo), load(repo))
    md = repo / "docs" / "notes" / "plan-v1.md"
    md.write_text("# Plan\n")
    assert publish(Source("memo", md, md.with_suffix(".pdf")), load(repo))[1] == docs / "Animus/plan-v1.md"
