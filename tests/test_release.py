"""tools/release.sh against scratch repos with a local bare 'origin' (dry run: no gh, no network)."""
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "release.sh"
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t", "DRY_RUN": "1"}


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout


def bump(repo, py, pkg):
    (repo / "src/publishing").mkdir(parents=True, exist_ok=True)
    (repo / "pyproject.toml").write_text(f'[project]\nversion = "{py}"\n')
    (repo / "src/publishing/__init__.py").write_text(f'__version__ = "{pkg}"\n')
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"bump {py}")


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "--bare", "origin.git")
    r = tmp_path / "w"
    r.mkdir()
    git(r, "init", "-q")
    git(r, "remote", "add", "origin", str(tmp_path / "origin.git"))
    return r


def run(r):
    return subprocess.run([str(SCRIPT)], capture_output=True, text=True, env={**ENV, "RELEASE_REPO": str(r)})


def test_untagged_bump_would_be_released(repo):
    bump(repo, "1.0.0", "1.0.0")
    p = run(repo)
    assert p.returncode == 0 and "would tag v1.0.0" in p.stdout


def test_mismatch_fails_loudly(repo):
    bump(repo, "1.0.1", "1.0.0")
    p = run(repo)
    assert p.returncode == 1 and "VERSION MISMATCH" in p.stderr


def test_tag_on_origin_is_a_noop_even_if_not_local(repo):
    bump(repo, "1.0.0", "1.0.0")
    git(repo, "tag", "v1.0.0")
    git(repo, "push", "-q", "origin", "v1.0.0")
    git(repo, "tag", "-d", "v1.0.0")
    p = run(repo)
    assert p.returncode == 0 and "already on origin" in p.stdout


def test_tags_the_bump_commit_not_head(repo):
    bump(repo, "1.0.0", "1.0.0")
    first = git(repo, "rev-parse", "--short", "HEAD").strip()
    (repo / "x").write_text("x")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "later")
    p = run(repo)
    assert f"at {first}" in p.stdout
