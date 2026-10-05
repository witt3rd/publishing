"""The explainer template (examples/explainer-template): script.md to a narration script and a composition that builds."""
import importlib.util
import json
from pathlib import Path

from publishing import narrate
from publishing.build import build, resolve
from publishing.config import load

ROOT = Path(__file__).resolve().parent.parent / "examples" / "explainer-template"
spec = importlib.util.spec_from_file_location("explain", ROOT / "explain.py")
explain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(explain)
SCRIPT = (ROOT / "hello-explainer-v1" / "script.md").read_text()


def timings(seconds=1):  # a stand-in for narration.json: one second a scene
    ids = [s[0] for s in explain.parse(SCRIPT)[2]]
    return {"duration": seconds * len(ids), "scenes": [
        {"id": sid, "start": i * seconds, "duration": seconds} for i, sid in enumerate(ids)]}


def test_narration_is_a_valid_narrate_script_with_the_scene_ids():
    scenes = narrate.parse_script(explain.narration(SCRIPT))
    assert [s for s, _ in scenes] == ["scene-title", "scene-stack", "scene-number", "scene-bars", "scene-close"]
    assert "@" not in "".join(w for _, w in scenes)


def test_compose_fills_every_scene_from_the_timings():
    out = explain.compose(SCRIPT, timings(2))
    assert out.count("<section") == 5 and 'data-duration="10"' in out and 'data-start="6"' in out
    assert "{{" not in out and "45x" in out and "Hit" in out


def test_the_composition_builds_to_an_mp4(repo, renderer):
    folder = repo / "docs" / "notes" / "hello-explainer-v1"
    folder.mkdir()
    (folder / "video.html").write_text(explain.compose(SCRIPT, timings()))
    cfg = load(folder)
    assert build(resolve(folder, cfg), cfg, renderer) == "built"
    assert (repo / "docs" / "notes" / "hello-explainer-v1.mp4").stat().st_size > 0
