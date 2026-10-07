#!/usr/bin/env bash
# Repeat the caching explainer: speech from the script, the silent video from video.html, one MP4 with both.
# Needs: uv, ffmpeg, and a publishing checkout or tag with the `video` and `narrate` extras (README "Narration").
#   ./build.sh [OUTDIR]     default OUTDIR: ./out (created; nothing in it is overwritten, so use a fresh one)
set -euo pipefail
cd "$(dirname "$0")"
out="${1:-out}"; mkdir -p "$out"
pub=(uvx --from "publishing[video,narrate] @ git+https://github.com/witt3rd/publishing@v0.14.0" publishing)
[ -z "${PUBLISHING_FROM:-}" ] || pub=(uvx --from "publishing[video,narrate] @ $PUBLISHING_FROM" publishing)
"${pub[@]}" setup --video
# The voice: OpenRouter's house voice (elevenlabs/eleven-v4-turbo, Brian) when OPENROUTER_API_KEY is in the environment (run under `doppler run`, or
# export it; the key is read from the environment only), else local, free Kokoro. NARRATE_MODEL=... picks another
# OpenRouter speech model, NARRATE_MODEL=kokoro forces the local voice.
model="${NARRATE_MODEL:-}"
[ -n "$model" ] || { [ -n "${OPENROUTER_API_KEY:-}" ] || model=kokoro; }   # no key: local Kokoro; else the house default
args=(); [ -z "$model" ] || args=(--tts-model "$model")
"${pub[@]}" narrate narration.txt -o "$out" "${args[@]}"   # out/narration.wav and out/narration.json
# Fit the scenes to the speech: fill the template's start and duration from out/narration.json.
mkdir -p "$out/src/caching-explainer-v1"
python3 - "$out/narration.json" video.html "$out/src/caching-explainer-v1/video.html" <<'PY'
import json, sys
t = json.load(open(sys.argv[1])); s = open(sys.argv[2]).read()
s = s.replace("{{duration}}", str(t["duration"]))
for sc in t["scenes"]:
    s = s.replace("{{%s.start}}" % sc["id"], str(sc["start"])).replace("{{%s.duration}}" % sc["id"], str(sc["duration"]))
assert "{{" not in s, "a scene in video.html is not in the script"
open(sys.argv[3], "w").write(s)
PY
"${pub[@]}" build "$out/src/caching-explainer-v1"     # the silent video: out/src/caching-explainer-v1.mp4
ffmpeg -nostdin -loglevel error -i "$out/src/caching-explainer-v1.mp4" -i "$out/narration.wav" \
  -c:v copy -c:a aac -b:a 128k -shortest "$out/caching-explainer-v1.mp4"
echo "$out/caching-explainer-v1.mp4"
