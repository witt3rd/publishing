#!/usr/bin/env python3
"""Explainer script -> narration script and HyperFrames composition (standard library only).

  explain.py narration script.md             > narration.txt    (feed it to `publishing narrate`)
  explain.py compose script.md narration.json > video.html     (scene start/duration from the narration timings)

The script is README.md's "Explainer template" convention: `# name`, optional `kicker: text`, then one
`## scene-id` per scene holding one `@component a | b | c` line (what is on screen) and the narration lines.
"""
import html
import json
import sys

COMPONENTS = ("title", "number", "stack", "bars", "points")
CSS = """
  .num { font-size: 260px; font-weight: 800; color: var(--accent); line-height: 1; margin-top: 40px; }
  .numl { font-size: 40px; color: var(--ink2); margin-top: 18px; }
  .blocks { width: 760px; margin: 20px auto 0; } .blocks .card { padding: 26px; text-align: center; margin-top: 16px; }
  .blocks .card h3 { font-size: 36px; margin: 0; }
  .blocks .hot { background: var(--accent-soft); border-color: var(--accent); } .blocks .hot h3 { color: var(--accent); }
  .bar { display: flex; align-items: center; margin-top: 34px; }
  .bar .lbl { width: 260px; font-size: 34px; color: var(--ink2); }
  .bar .fill { height: 70px; border-radius: 10px; background: var(--ink2); } .bar .fill.hot { background: var(--accent); }
  .bar .val { font-size: 34px; font-weight: 700; margin-left: 22px; }
  .pts { font-size: 38px; line-height: 1.5; margin-top: 40px; max-width: 1500px; }
"""


def parse(text):
    """(name, kicker, [(scene id, component, args, narration)])."""
    name, kicker, scenes = "explainer", "Explainer", []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            scenes.append([line[3:].strip(), None, [], []])
        elif line.startswith("# ") and not scenes:
            name = line[2:].strip()
        elif line.startswith("kicker:") and not scenes:
            kicker = line[7:].strip()
        elif line.startswith("@") and scenes:
            kind, _, rest = line[1:].partition(" ")
            if kind not in COMPONENTS or scenes[-1][1]:
                sys.exit(f"{scenes[-1][0]}: one @component of {', '.join(COMPONENTS)} per scene, got {line!r}")
            scenes[-1][1], scenes[-1][2] = kind, [a.strip() for a in rest.split("|")]
        elif line and scenes and not line.startswith("<!--"):
            scenes[-1][3].append(line)
    for sid, kind, _, words in scenes:
        if not (kind and words):
            sys.exit(f"{sid}: needs one @component line and narration text")
    return name, kicker, [tuple(s[:3]) + (" ".join(s[3]),) for s in scenes]


def narration(text):
    name, _, scenes = parse(text)
    return f"# Narration for {name}. One `## scene-id` per scene of video.html.\n" + "".join(
        f"\n## {sid}\n{words}\n" for sid, _, _, words in scenes)


def e(s):
    return html.escape(s)


def body(kind, a, kicker):
    """The scene's inside: the reusable components."""
    if kind == "title":  # @title Headline | subline
        return (f'<div class="kicker">{e(kicker)}</div><h1 class="rise" style="--at: .2s">{e(a[0])}</h1>'
                f'<h2 class="rise" style="--at: .8s">{e(a[1] if len(a) > 1 else "")}</h2>')
    head = f'<div class="kicker">{e(kicker)}</div><h1>{e(a[0])}</h1>'
    if kind == "number":  # @number Heading | 90 ms | what it measures
        return (head + f'<div class="body middle"><div class="num pop" style="--at: .5s">{e(a[1])}</div>'
                f'<div class="numl rise" style="--at: 1.2s">{e(a[2])}</div></div>')
    if kind == "stack":  # @stack Heading | top block | *highlighted block | bottom block
        cards = "".join(
            f'<div class="card pop{" hot" if b.startswith("*") else ""}" style="--at: {.4 + .5 * i:g}s">'
            f'<h3>{e(b.lstrip("*"))}</h3></div>' for i, b in enumerate(a[1:]))
        return head + f'<div class="body middle"><div class="blocks">{cards}</div></div>'
    if kind == "bars":  # @bars Heading | unit | Before=90 | *After=2   (widths scale to the largest)
        rows = [(b.lstrip("*"), b.startswith("*")) for b in a[2:]]
        pairs = [(r.partition("=")[0], float(r.partition("=")[2]), hot) for r, hot in rows]
        top = max(v for _, v, _ in pairs)
        out = "".join(
            f'<div class="bar"><div class="lbl">{e(n)}</div><div class="fill grow{" hot" if hot else ""}" '
            f'style="--at: {.4 + .6 * i:g}s; width: {max(v / top * 1000, 8):.0f}px"></div>'
            f'<div class="val rise" style="--at: {.9 + .6 * i:g}s">{v:g} {e(a[1])}</div></div>'
            for i, (n, v, hot) in enumerate(pairs))
        return head + f'<div class="body middle">{out}</div>'
    pts = "".join(f'<p class="rise" style="--at: {.5 + 1.2 * i:g}s">{e(p)}</p>' for i, p in enumerate(a[1:]))
    return head + f'<div class="body middle"><div class="pts">{pts}</div></div>'  # @points Heading | a | b


def compose(text, timings):
    name, kicker, scenes = parse(text)
    t = {s["id"]: s for s in timings["scenes"]}
    missing = [sid for sid, *_ in scenes if sid not in t]
    if missing:
        sys.exit(f"not in the narration timings: {', '.join(missing)}")
    secs = []
    for i, (sid, kind, a, _) in enumerate(scenes, 1):
        cls = "slide title clip" if kind == "title" else "slide clip"
        foot = "" if kind == "title" else f'<div class="rule"></div><div class="foot"><span>{e(name)}</span><span>{i} / {len(scenes)}</span></div>'
        secs.append(f'  <section id="{sid}" class="{cls}" data-start="{t[sid]["start"]}" data-duration="{t[sid]["duration"]}" '
                    f'data-track-index="0">\n    {body(kind, a, kicker)}\n    {foot}\n  </section>')
    return (f'<!doctype html>\n<!-- Generated by explain.py from script.md; edit the script, not this file. -->\n'
            f'<html lang="en">\n<head><meta charset="utf-8"><title>{e(name)}</title>\n<style>{CSS}</style></head>\n<body>\n'
            f'<div id="root" data-composition-id="root" data-no-timeline data-width="1920" data-height="1080"\n'
            f'     data-fps="30" data-start="0" data-duration="{timings["duration"]}">\n\n' + "\n\n".join(secs) +
            "\n</div>\n</body>\n</html>\n")


def main(argv):
    if len(argv) == 2 and argv[0] == "narration":
        sys.stdout.write(narration(open(argv[1]).read()))
    elif len(argv) == 3 and argv[0] == "compose":
        sys.stdout.write(compose(open(argv[1]).read(), json.load(open(argv[2]))))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
