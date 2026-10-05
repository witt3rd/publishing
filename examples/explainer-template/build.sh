#!/usr/bin/env bash
# Narrated explainer from a script.md: narration, fitted composition, silent video, one MP4 with both.
# Needs: uv, ffmpeg, python3, and publishing with the `video` and `narrate` extras (README "Explainer template").
#   ./build.sh SCRIPT_DIR [OUTDIR]   SCRIPT_DIR holds script.md; OUTDIR default ./out, use a fresh one
#   NARRATE_MODEL=kokoro|<OpenRouter model>; OPENROUTER_API_KEY (environment only) picks MAI-Voice by default.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"; src="$(cd "${1:?usage: build.sh SCRIPT_DIR [OUTDIR]}" && pwd)"
out="${2:-out}"; mkdir -p "$out"; out="$(cd "$out" && pwd)"; name="$(basename "$src")"
pub=(uvx --from "publishing[video,narrate] @ git+https://github.com/witt3rd/publishing@v0.12.0" publishing)
[ -z "${PUBLISHING_FROM:-}" ] || pub=(uvx --from "publishing[video,narrate] @ $PUBLISHING_FROM" publishing)
"${pub[@]}" setup --video
model="${NARRATE_MODEL:-}"
[ -n "$model" ] || { [ -z "${OPENROUTER_API_KEY:-}" ] || model=microsoft/mai-voice-2.1-flash; }
args=(); [ -z "$model" ] || [ "$model" = kokoro ] || args=(--model "$model")
python3 "$here/explain.py" narration "$src/script.md" > "$out/narration.txt"
"${pub[@]}" narrate "$out/narration.txt" -o "$out" "${args[@]}"   # out/narration.wav and out/narration.json
mkdir -p "$out/src/$name"
python3 "$here/explain.py" compose "$src/script.md" "$out/narration.json" > "$out/src/$name/video.html"
"${pub[@]}" build "$out/src/$name"                                # the silent video: out/src/NAME.mp4
ffmpeg -nostdin -loglevel error -i "$out/src/$name.mp4" -i "$out/narration.wav" \
  -c:v copy -c:a aac -b:a 128k -shortest "$out/$name.mp4"
echo "$out/$name.mp4"
