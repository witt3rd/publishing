"""Tests for word-level forced alignment (publishing.align) and its integration in narrate."""
from __future__ import annotations

import json
import math
import struct

from publishing.align import align_words, syllables, tokenize
from publishing.narrate import SAMPLE_RATE, narrate


def _tone(dur: float, sr: int = SAMPLE_RATE, amp: float = 0.5, freq: float = 220.0) -> list[float]:
    n = round(dur * sr)
    return [amp * math.sin(2.0 * math.pi * freq * i / sr) for i in range(n)]


def _silence(dur: float, sr: int = SAMPLE_RATE) -> list[float]:
    return [0.0] * round(dur * sr)


def _to_i16_array(samples: list[float]):
    import array
    return array.array("h", (max(-32767, min(32767, round(v * 32767))) for v in samples))


def test_syllables_and_tokenize():
    assert syllables("cat") == 1
    assert syllables("computer") == 3
    assert syllables("didn't") == 2
    assert syllables("123") >= 3
    toks = tokenize("Hello, world.\nSecond line!")
    assert [t["word"] for t in toks] == ["Hello,", "world.", "Second", "line!"]
    assert [t["brk"] for t in toks] == [2, 4, 0, 0]


def test_align_tracks_real_pause_between_sentences():
    # Asymmetric lengths: short first sentence (0.4s), 0.7s pause at t=0.6..1.3s, long second sentence (1.4s).
    # Without pause DP, proportional spreading would put the sentence boundary around t=1.1s instead of t=0.6s.
    x = _silence(0.2) + _tone(0.4) + _silence(0.7) + _tone(1.4) + _silence(0.2)
    words = align_words(x, SAMPLE_RATE, "Go now. Second much longer sentence here.")
    assert [w["word"] for w in words] == ["Go", "now.", "Second", "much", "longer", "sentence", "here."]
    assert 0.50 <= words[1]["end"] <= 0.70
    assert 1.20 <= words[2]["start"] <= 1.40
    assert words[2]["start"] - words[1]["end"] >= 0.50
    for w in words:
        assert w["end"] >= w["start"]


def test_align_pure_silence_falls_back_proportionally():
    x = _silence(2.0)
    words = align_words(x, SAMPLE_RATE, "One two three four", offset=5.0)
    assert len(words) == 4
    assert words[0]["start"] == 5.0
    assert 6.95 <= words[-1]["end"] <= 7.05
    for a, b in zip(words, words[1:]):
        assert a["end"] <= b["start"] + 1e-6


def test_narrate_emits_word_timings_with_scene_offset(tmp_path):
    script = tmp_path / "demo.txt"
    script.write_text("## s1\nHello world.\n## s2\nNext scene here.\n")

    def fake_synth(scenes, **_):
        # Scene 1: 1.0s tone; Scene 2: 0.2s silence + 0.5s tone + 0.4s silence + 0.5s tone
        s1 = _to_i16_array(_tone(1.0))
        s2 = _to_i16_array(_silence(0.2) + _tone(0.5) + _silence(0.4) + _tone(0.5))
        return [(scenes[0][0], scenes[0][1], s1), (scenes[1][0], scenes[1][1], s2)]

    _wav, meta_path = narrate(script, gap=0.5, synth=fake_synth)
    meta = json.loads(meta_path.read_text())
    s1_words = meta["scenes"][0]["words"]
    s2_words = meta["scenes"][1]["words"]
    assert [w["word"] for w in s1_words] == ["Hello", "world."]
    assert [w["word"] for w in s2_words] == ["Next", "scene", "here."]
    # Scene 2 starts at 1.0 + 0.5 = 1.5s; its words must be shifted by that offset.
    assert meta["scenes"][1]["start"] == 1.5
    assert s2_words[0]["start"] >= 1.5
    assert s2_words[-1]["end"] <= 1.5 + meta["scenes"][1]["speech"] + 0.05
