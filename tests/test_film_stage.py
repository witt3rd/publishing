"""Tests for --format film scaffold and the continuous-stage JS runtime (theme/stage.js)."""
from __future__ import annotations

import json
import subprocess
from importlib import resources
from pathlib import Path

from publishing import cli, video


def _run_node(code: str) -> str:
    r = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True)
    return r.stdout.strip()


def test_new_film_scaffolds_and_stages(tmp_path):
    target = tmp_path / "docs" / "film" / "demo-v1"
    rc = cli.main(["new", str(target), "--format", "film"])
    assert rc == 0
    src = target / "video.html"
    assert src.is_file()
    text = src.read_text()
    assert "_publishing/stage.js" in text
    assert "PublishingStage" in text
    assert "{name}" not in text

    staged = video.stage(target, tmp_path / "staged")
    assert staged.is_file()
    assert (staged.parent / video.STAGE_THEME / "stage.js").is_file()


def test_stage_js_cues_math_and_seek_hook():
    stage_js = Path(str(resources.files("publishing").joinpath("theme", "stage.js")))
    out = _run_node(f"""
const fs = require("fs");
const vm = require("vm");
const sandbox = {{
  window: {{}},
  document: {{
    readyState: "complete",
    getElementById: () => ({{ dataset: {{ duration: "6", fps: "30" }} }}),
    addEventListener: () => {{}},
  }},
}};
sandbox.globalThis = sandbox;
vm.runInNewContext(fs.readFileSync({json.dumps(str(stage_js))}, "utf8"), sandbox);
const S = sandbox.window.PublishingStage;

// 1. Word cue lookup (global, scene-scoped, occurrence, missing throws)
const meta = {{
  scenes: [
    {{ id: "s01", start: 0, words: [
      {{ word: "First,", start: 0.2, end: 0.5 }},
      {{ word: "the", start: 0.5, end: 0.7 }},
      {{ word: "corner.", start: 0.7, end: 1.1 }},
      {{ word: "the", start: 1.5, end: 1.7 }},
      {{ word: "corner!", start: 1.7, end: 2.1 }},
    ]}},
    {{ id: "s02", start: 3.0, words: [
      {{ word: "Next", start: 3.2, end: 3.6 }},
      {{ word: "corner", start: 3.6, end: 4.1 }},
    ]}},
  ],
}};
const {{ cue }} = S.makeCues(meta);
let missingThrew = false;
try {{ cue("not there"); }} catch (e) {{ missingThrew = /not found/.test(e.message); }}

// 2. Deterministic PRNG
const r1 = S.rng(42), r2 = S.rng(42);
const sameRng = r1() === r2() && r1() === r2();

// 3. HyperFrames __hf.seek hook (must survive HyperFrames' bridge overwriting __hf.seek after mount)
const seen = [];
let bridgeCalled = 0;
S.mount({{ canvas: null, duration: 6, fps: 30, paint: ({{ t, frame }}) => seen.push([t, frame]) }});
sandbox.window.__hf.seek = (t) => {{ bridgeCalled++; }};
sandbox.window.__hf.seek(2.5);
sandbox.window.__hf.seek(9.0); // clamped to duration=6

console.log(JSON.stringify({{
  c1: cue("the corner"),
  c2: cue("the corner", "s01", 2),
  c3: cue("next corner", "s02"),
  missingThrew,
  sameRng,
  sstepMid: S.sstep(0, 1, 0.5),
  seen,
  bridgeCalled,
}}));
""")
    res = json.loads(out)
    assert res["c1"] == 0.5
    assert res["c2"] == 1.5
    assert res["c3"] == 3.2
    assert res["missingThrew"] is True
    assert res["sameRng"] is True
    assert res["sstepMid"] == 0.5
    assert res["seen"] == [[0, 0], [2.5, 75], [6, 180]]
    assert res["bridgeCalled"] == 2
