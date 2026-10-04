"""Accessibility check of a PDF: is it tagged, titled, in a language, and are its fonts embedded?

`publishing a11y FILE.pdf` reads the PDF back with pypdf (the render profile's pin; no Chromium, no
network) and reports each failed requirement, named after the PDF/UA rule it approximates. It checks
what the house renderer controls (Chromium `tagged=True`, `<html lang>`, `<title>`, the outline of a
memo or document); it is not a PDF/UA validator, and the house build does not produce PDF/A (README "Accessibility")."""
from pathlib import Path

from pypdf import PdfReader

MAX_NODES = 200_000  # a structure tree is walked at most this far: a hostile PDF cannot run it away


def _walk(node, seen: set[int], figures: list[bool], budget: list[int]) -> None:
    """Collect, for every /Figure element, whether it has alternate text."""
    node = node.get_object() if hasattr(node, "get_object") else node
    if not hasattr(node, "get") or id(node) in seen or budget[0] <= 0:
        return
    seen.add(id(node))
    budget[0] -= 1
    if node.get("/S") == "/Figure":
        figures.append(bool(str(node.get("/Alt") or "").strip()))
    kids = node.get("/K")
    if kids is None:
        return
    kids = kids.get_object() if hasattr(kids, "get_object") else kids
    for k in kids if isinstance(kids, list) else [kids]:
        _walk(k, seen, figures, budget)


def check(pdf: Path, *, kind: str | None = None) -> tuple[list[str], list[str]]:
    """(problems, advice). Problems fail the check; empty is clean. `kind` "memo" or "document" also
    requires an outline. Advice does not fail it: figures without alternate text (Chromium tags an inline
    SVG as a /Figure and writes no /Alt for it)."""
    advice: list[str] = []
    reader = PdfReader(str(pdf))
    root = reader.trailer["/Root"]
    problems = []
    mark = root.get("/MarkInfo")
    if not (mark and bool(mark.get_object().get("/Marked"))):
        problems.append("not tagged: /MarkInfo /Marked is not true (render with tagged=True)")
    tree = root.get("/StructTreeRoot")
    if tree is None:
        problems.append("no structure tree: /StructTreeRoot is missing")
    else:
        figures: list[bool] = []
        _walk(tree, set(), figures, [MAX_NODES])
        if figures.count(False):
            advice.append(f"{figures.count(False)} of {len(figures)} figures have no alternate text (/Alt)")
    if not str(root.get("/Lang") or "").strip():
        problems.append("no document language: /Lang is missing (set <html lang>)")
    meta = reader.metadata
    if not str((meta.title if meta else "") or "").strip():
        problems.append("no title: /Title is empty (set <title>)")
    vp = root.get("/ViewerPreferences")
    if not (vp and bool(vp.get_object().get("/DisplayDocTitle"))):
        problems.append("the viewer is not told to show the title: /DisplayDocTitle is not true")
    if kind in ("memo", "document") and len(reader.pages) > 1 and not reader.outline:
        problems.append(f"no bookmarks: a {kind} needs an outline")
    unembedded = _unembedded(reader)
    if unembedded:
        problems.append("fonts not embedded: " + ", ".join(sorted(unembedded)))
    return problems, advice


def _unembedded(reader: PdfReader) -> set[str]:
    names = set()
    for page in reader.pages:
        res = page.get("/Resources")
        res = res.get_object() if res is not None else {}
        fonts = res.get("/Font")
        for f in (fonts.get_object() if fonts is not None else {}).values():
            f = f.get_object()
            if f.get("/Subtype") == "/Type3":
                continue  # drawn glyphs, nothing to embed
            desc = f.get("/FontDescriptor")
            if desc is None and f.get("/DescendantFonts"):
                desc = f["/DescendantFonts"][0].get_object().get("/FontDescriptor")
            desc = desc.get_object() if desc is not None else {}
            if not any(k in desc for k in ("/FontFile", "/FontFile2", "/FontFile3")):
                names.add(str(f.get("/BaseFont", "?")).lstrip("/").split("+", 1)[-1])
    return names
