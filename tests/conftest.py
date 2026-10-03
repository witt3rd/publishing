import resource

import pytest


@pytest.fixture
def no_core_dump():
    """A `preexec_fn` for a test that makes a process fail on purpose: RLIMIT_CORE 1 makes the kernel skip
    the core dump, the pipe to systemd-coredump included, so the failure leaves no core and no desktop
    "Process crashed" notice. 0 is not enough: systemd-coredump still journals the crash, and the
    notifier reads the journal (docs/user-content.md, "Testing")."""
    return lambda: resource.setrlimit(resource.RLIMIT_CORE, (1, 1))


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
