import pytest

from publishing.render import Renderer


@pytest.fixture(scope="session")
def renderer():
    with Renderer() as r:
        yield r


@pytest.fixture
def repo(tmp_path):
    """An empty repo with a docs/report.toml."""
    (tmp_path / "docs" / "notes").mkdir(parents=True)
    (tmp_path / "docs" / "report.toml").write_text('project = "Fleet"\n[publish]\nnotes = "Fleet/Notes"\n')
    return tmp_path
