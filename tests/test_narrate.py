"""publishing narrate: the script format, the timing table, the refusals, and the OpenRouter request.

Nothing here needs a model, a key or the network: speech is faked (silence of a known length) and the HTTP
call is replaced. Real Kokoro synthesis is exercised by hand and by examples/narration/*/build.sh.
"""
import io
import json
import wave
from pathlib import Path


import pytest

np = pytest.importorskip("numpy")  # the narrate extra

from publishing import narrate as nr

SCRIPT = """# a comment
## intro
Hello there.
Second line.

## outro
Bye.
"""


def fake_synth(scenes, **kw):  # one second of speech per word
    return [(sid, text, np.zeros(nr.SAMPLE_RATE * len(text.split()), dtype="<i2")) for sid, text in scenes]


def test_parse_headings():
    assert nr.parse_script(SCRIPT) == [("intro", "Hello there. Second line."), ("outro", "Bye.")]


def test_parse_paragraphs_without_headings():
    assert nr.parse_script("One.\nTwo.\n\nThree.\n") == [("scene-1", "One. Two."), ("scene-2", "Three.")]


@pytest.mark.parametrize("text", ["", "# only a comment\n", "## a\n\n## b\nx\n", "## a\nx\n## a\ny\n"])
def test_parse_refuses(text):
    with pytest.raises(nr.Usage):
        nr.parse_script(text)


def test_lay_out_tiles_the_wav():
    spoken = fake_synth([("a", "one two"), ("b", "three")])
    frames, table = nr.lay_out(spoken, 0.5, "v")
    assert [(s["id"], s["start"], s["speech"], s["duration"]) for s in table["scenes"]] == [
        ("a", 0.0, 2.0, 2.5), ("b", 2.5, 1.0, 1.5)]
    assert table["duration"] == 4.0 and len(frames) == 2 * int(4.0 * nr.SAMPLE_RATE)


def test_narrate_writes_wav_and_json_and_never_overwrites(tmp_path):
    script = tmp_path / "s.txt"
    script.write_text(SCRIPT)
    wav, js = nr.narrate(script, tmp_path / "out", gap=0.25, synth=fake_synth)
    with wave.open(str(wav)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, nr.SAMPLE_RATE)
        assert w.getnframes() / nr.SAMPLE_RATE == json.loads(js.read_text())["duration"] == 5.5
    with pytest.raises(nr.Usage, match="never overwrite"):
        nr.narrate(script, tmp_path / "out", synth=fake_synth)


def test_missing_script(tmp_path):
    with pytest.raises(nr.Usage):
        nr.narrate(tmp_path / "nope.txt", synth=fake_synth)


def test_openrouter_needs_a_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    script = tmp_path / "s.txt"
    script.write_text(SCRIPT)
    with pytest.raises(nr.Usage, match="OPENROUTER_API_KEY"):
        nr.narrate(script, tmp_path / "o", model="fish-audio/s2.1-pro")


def test_openrouter_request(monkeypatch):
    seen = {}

    class Resp(io.BytesIO):
        headers = {"X-Generation-Id": "gen-1"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def urlopen(req, timeout):
        seen["body"] = json.loads(req.data)
        seen["auth"] = req.get_header("Authorization")
        return Resp(b"mp3")

    monkeypatch.setattr(nr.urllib.request, "urlopen", urlopen)
    assert nr.speak_openrouter("Hi.", "microsoft/mai-voice-2.1-flash", "en-US-Sage:MAI-Voice-2.1-Flash", key="k") == (b"mp3", "gen-1")
    assert seen["body"] == {"model": "microsoft/mai-voice-2.1-flash", "input": "Hi.", "response_format": "mp3",
                            "voice": "en-US-Sage:MAI-Voice-2.1-Flash"}
    assert seen["auth"] == "Bearer k"
    nr.speak_openrouter("Hi.", "bytedance-seed/seed-audio-1-0", "", key="k")
    assert seen["body"]["input"].endswith("Hi.") and "voice" not in seen["body"]


def test_explicit_tts_model_and_voice_reach_the_request_and_the_json(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = []

    def speak(text, model, voice, speed=1.0, key=None, **kw):
        seen.append((model, voice))
        return b"mp3", "gen"

    monkeypatch.setattr(nr, "speak_openrouter", speak)
    monkeypatch.setattr(nr, "_decode", lambda mp3: np.zeros(2400, dtype="<i2"))
    script = tmp_path / "s.txt"
    script.write_text(SCRIPT)
    _, js = nr.narrate(script, tmp_path / "o", model="elevenlabs/eleven-v4-turbo", voice="Rachel")
    assert set(seen) == {("elevenlabs/eleven-v4-turbo", "Rachel")}
    meta = json.loads(js.read_text())
    assert (meta["tts_model"], meta["tts_voice"]) == ("elevenlabs/eleven-v4-turbo", "Rachel")


def test_json_names_the_tts_model_and_voice(tmp_path):
    script = tmp_path / "s.txt"
    script.write_text(SCRIPT)
    _, js = nr.narrate(script, tmp_path / "o", synth=fake_synth)
    meta = json.loads(js.read_text())
    assert meta["tts_model"] is None and meta["tts_voice"] is None


def test_report_toml_narrate_defaults_and_flags_win(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "report.toml").write_text('[narrate]\ntts_model = "fish-audio/s2.1-pro"\nvoice = "v1"\n')
    (tmp_path / "docs" / "s.txt").write_text(SCRIPT)
    assert nr.config_defaults(tmp_path / "docs" / "s.txt") == ("fish-audio/s2.1-pro", "v1")
    assert nr.config_defaults(tmp_path.parent / "nowhere.txt") == (None, None)
    p = nr.argparse.ArgumentParser()
    nr.add_arguments(p)
    a = p.parse_args(["x.txt", "--tts-model", "elevenlabs/eleven-v4-turbo", "--voice", "Rachel"])
    assert (a.model, a.voice) == ("elevenlabs/eleven-v4-turbo", "Rachel")
    assert p.parse_args(["x.txt", "--model", "m"]).model == "m"  # the old name still works


def test_house_default_is_brian_on_eleven_v4_turbo_and_explicit_wins():
    assert nr.resolve(None, None) == ("elevenlabs/eleven-v4-turbo", "Brian")
    assert nr.resolve(None, "Rachel") == ("elevenlabs/eleven-v4-turbo", "Rachel")
    assert nr.resolve("fish-audio/s2.1-pro", None) == ("fish-audio/s2.1-pro", None)
    assert nr.resolve("elevenlabs/eleven-v4-turbo", "Rachel") == ("elevenlabs/eleven-v4-turbo", "Rachel")
    assert nr.resolve("kokoro", None) == (None, None) and nr.resolve("local", "af_sky") == (None, "af_sky")
    assert nr.resolve(None, None, ("fish-audio/s2.1-pro", "v1")) == ("fish-audio/s2.1-pro", "v1")  # report.toml beats the house default
    assert nr.resolve(None, None, ("fish-audio/s2.1-pro", None)) == ("fish-audio/s2.1-pro", None)
