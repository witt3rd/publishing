"""The text scan run on every built PDF: generic secrets, host details, stale day words,
glyphs outside the vendored fonts, and the repo's own words from docs/report.toml."""
import re
from functools import lru_cache
from importlib import resources

SECRETS = re.compile(
    r"\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}|\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}"
    r"|\bAKIA[0-9A-Z]{16}\b|\bxox[abpors]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\bdp\.(?:st|pt|ct|sa|scim|audit)\.[A-Za-z0-9_.-]{20,}|\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}"
    r"|\bglpat-[A-Za-z0-9_-]{20}|\bAIza[0-9A-Za-z_-]{35}")
HOST = re.compile(r"/home/[\w.-]+|/Users/[\w.-]+|\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b|\blocalhost:\d+")
DAYS = re.compile(r"\b(?:today|tomorrow|yesterday|tonight|this (?:morning|afternoon|evening|week))\b", re.I)


@lru_cache(maxsize=1)
def coverage() -> list[tuple[int, int]]:
    raw = resources.files("publishing").joinpath("theme/fonts/coverage.txt").read_text()
    return [tuple(int(x, 16) for x in line.split("-")) for line in raw.split()]


def uncovered(text: str) -> list[str]:
    import bisect

    spans = coverage()
    starts = [a for a, _ in spans]
    out = set()
    for ch in set(text):
        c = ord(ch)
        if c < 0x20 or ch.isspace():
            continue
        i = bisect.bisect_right(starts, c) - 1
        if i < 0 or c > spans[i][1]:
            out.add(ch)
    return sorted(out)


def scan(text: str, *, words=(), allow=(), days=True) -> list[str]:
    """Problems found in `text`; empty means clean. `allow` exempts exact strings."""
    allowed = {a.lower() for a in allow}
    hits = {}
    checks = [("secret", SECRETS), ("host detail", HOST)]
    if days:
        checks.append(("relative day word", DAYS))
    if words:
        checks.append(("project word", re.compile("|".join(f"(?:{w})" for w in words), re.I)))
    for label, rx in checks:
        for m in rx.finditer(text):
            if m.group(0).lower() not in allowed:
                hits.setdefault(label, set()).add(m.group(0))
    problems = [f"{label}: {', '.join(sorted(v))}" for label, v in hits.items()]
    missing = [c for c in uncovered(text) if c not in allow]
    if missing:
        problems.append("glyph outside the vendored fonts (would use a host font): "
                        + ", ".join(f"{c!r} U+{ord(c):04X}" for c in missing))
    return problems
