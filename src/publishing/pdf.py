"""Read a PDF back: its words (for the rebuild check and the scan), page count, page images."""
from pathlib import Path

from pypdf import PdfReader


def pages(pdf: Path) -> int:
    return len(PdfReader(str(pdf)).pages)


def text(pdf: Path) -> str:
    """The words, whitespace-normalised: line wrapping is not content."""
    reader = PdfReader(str(pdf))
    return " ".join(" ".join(p.extract_text() or "" for p in reader.pages).split())


def fonts(pdf: Path) -> set[str]:
    """The base names of every font the PDF embeds (subset prefixes dropped)."""
    names = set()
    for page in PdfReader(str(pdf)).pages:
        res = page.get("/Resources")
        res = res.get_object() if res is not None else {}
        for f in (res.get("/Font") or {}).values():
            f = f.get_object()
            desc = f.get("/FontDescriptor")
            base = f.get("/BaseFont") or (desc.get_object().get("/FontName") if desc else None) or f.get("/Name", "?")
            names.add(str(base).lstrip("/").split("+", 1)[-1])
    return names


def is_pdf(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def same(a: Path, b: Path) -> bool:
    """True when two PDFs carry the same words on the same number of pages (bytes differ run to run)."""
    return is_pdf(a) and is_pdf(b) and pages(a) == pages(b) and text(a) == text(b)


def png(pdf: Path, out_dir: Path, *, width: int = 1400) -> list[Path]:
    """One PNG per page, `width` pixels wide, for review by eye."""
    import pypdfium2 as pdfium

    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(str(pdf))
    paths = []
    try:
        for i in range(len(doc)):
            page = doc[i]
            scale = width / page.get_width()
            img = page.render(scale=scale).to_pil()
            p = out_dir / f"p{i + 1:03d}.png"
            img.save(p)
            paths.append(p)
            page.close()
    finally:
        doc.close()
    return paths
