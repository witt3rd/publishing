import pytest


@pytest.fixture(scope="session")
def renderer():
    from publishing.render import Renderer  # the render profile; the convert tests run without it

    with Renderer() as r:
        yield r


@pytest.fixture
def repo(tmp_path):
    """An empty repo with a docs/report.toml."""
    (tmp_path / "docs" / "notes").mkdir(parents=True)
    (tmp_path / "docs" / "report.toml").write_text('project = "Fleet"\n[publish]\nnotes = "Fleet/Notes"\n')
    return tmp_path
