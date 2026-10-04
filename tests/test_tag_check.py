"""tools/tag-check.sh against scratch repos: what it accepts, and the messages that say what to do."""
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "tag-check.sh"
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout


def bump(r, py, pkg=None):
    (r / "src/publishing").mkdir(parents=True, exist_ok=True)
    (r / "pyproject.toml").write_text(f'[project]\nversion = "{py}"\n')
    (r / "src/publishing/__init__.py").write_text(f'__version__ = "{pkg or py}"\n')
    git(r, "add", "-A")
    git(r, "commit", "-qm", f"bump {py}")


def check(r):
    return subprocess.run([str(SCRIPT)], capture_output=True, text=True, env={**ENV, "TAG_CHECK_REPO": str(r)})


def new(tmp_path):
    git(tmp_path, "init", "-q")
    return tmp_path


def test_tagged_versions_pass(tmp_path):
    r = new(tmp_path)
    bump(r, "1.0.0")
    git(r, "tag", "v1.0.0")
    assert check(r).returncode == 0


def test_missing_tag_names_the_fix(tmp_path):
    r = new(tmp_path)
    bump(r, "1.0.0")
    p = check(r)
    assert p.returncode == 1 and "MISSING TAG: v1.0.0" in p.stderr and "Fix:" in p.stderr


def test_package_version_disagreement_fails(tmp_path):
    r = new(tmp_path)
    bump(r, "1.0.0", "0.9.0")
    git(r, "tag", "v1.0.0")
    p = check(r)
    assert p.returncode == 1 and "VERSION MISMATCH" in p.stderr


def test_tag_on_wrong_commit_fails(tmp_path):
    r = new(tmp_path)
    bump(r, "1.0.0")
    git(r, "tag", "v1.0.0")
    bump(r, "1.1.0")
    git(r, "tag", "v1.1.0", "HEAD~1")
    p = check(r)
    assert p.returncode == 1 and "WRONG TAG: v1.1.0" in p.stderr
