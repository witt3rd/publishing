"""The golden update procedure (tests/golden/README.md), exercised end to end on a synthetic profile.

A deliberate profile bump must fail the golden check with the instruction to regenerate, and pass again
once the manifest is regenerated with GOLDEN_UPDATE=1. The real profiles need their own images, so this
drives test_golden's own `_check` with a fake profile whose "toolchain version" is the thing bumped; it
runs anywhere, so a break in the update path itself is caught on every push, not only at the next bump.
"""
import json

import pytest

import test_golden as g


@pytest.fixture
def fake(tmp_path, monkeypatch):
    state = {"version": "1"}
    monkeypatch.setattr(g, "MANIFEST", tmp_path / "manifest.json")
    monkeypatch.setattr(g, "PROFILE", "fake")
    monkeypatch.setattr(g, "UPDATE", False)
    monkeypatch.setattr(g, "_toolchain", lambda p: f"faketool {state['version']}")
    monkeypatch.setattr(g, "_cases", lambda: {"fake": {
        "out.txt": lambda o: o.write_text(f"output of faketool {state['version']}\n")}})
    return state


def run(tmp_path):
    g._check("fake", "out.txt", tmp_path / "work")


def test_bump_fails_then_passes_after_regenerating(fake, tmp_path, monkeypatch):
    (tmp_path / "work").mkdir()
    with pytest.raises(AssertionError, match="no golden entry"):
        run(tmp_path)                                    # nothing committed yet
    monkeypatch.setattr(g, "UPDATE", True)
    run(tmp_path)                                        # first generation
    monkeypatch.setattr(g, "UPDATE", False)
    run(tmp_path)                                        # unchanged profile passes
    first = json.loads(g.MANIFEST.read_text())["fake"]
    assert first["toolchain"] == "faketool 1"

    fake["version"] = "2"                                # the deliberate profile bump
    with pytest.raises(AssertionError) as e:
        run(tmp_path)
    msg = str(e.value)
    assert "changed" in msg and "GOLDEN_UPDATE=1" in msg
    assert "faketool 2" in msg and "faketool 1" in msg   # names the toolchain now and the golden's

    monkeypatch.setattr(g, "UPDATE", True)
    run(tmp_path)                                        # regenerate, as the README says
    monkeypatch.setattr(g, "UPDATE", False)
    run(tmp_path)                                        # and the bump now passes
    second = json.loads(g.MANIFEST.read_text())["fake"]
    assert second["toolchain"] == "faketool 2"
    assert second["outputs"]["out.txt"]["sha256"] != first["outputs"]["out.txt"]["sha256"]


def test_regenerating_rewrites_only_its_own_profile(fake, tmp_path, monkeypatch):
    (tmp_path / "work").mkdir()
    other = {"media": {"toolchain": "x", "outputs": {"a": {"sha256": "0", "bytes": 1}}}}
    g.MANIFEST.write_text(json.dumps(other))
    monkeypatch.setattr(g, "UPDATE", True)
    run(tmp_path)
    m = json.loads(g.MANIFEST.read_text())
    assert m["media"] == other["media"] and "fake" in m


def test_committed_manifest_matches_the_cases_on_any_host():
    """The committed manifest has exactly the cases' names per profile (the in-image test of this is skipped here)."""
    manifest = json.loads(g.MANIFEST.read_text())
    cases = g._cases()
    assert sorted(manifest) == sorted(cases)
    for profile in cases:
        assert sorted(manifest[profile]["outputs"]) == sorted(cases[profile]), profile
