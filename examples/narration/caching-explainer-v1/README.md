# caching-explainer-v1

A short narrated explainer on caching, as a worked example of `publishing narrate` (README "Narration").
The original explainer's sources were not found in the bounded search of `~/Documents` and the rung docs, so this
script is written fresh for the same subject: hit, miss, eviction, time to live.

- `narration.txt`: the script, one `## scene-id` per scene.
- `video.html`: the scenes; start and duration are filled from the narration timings, so any voice fits.
- `build.sh`: narrate, fit, build, mux. Run it with a fresh output directory: `./build.sh /tmp/caching`.
