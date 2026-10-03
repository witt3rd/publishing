"""Re-vendor the house fonts into src/publishing/theme/fonts/ (WOFF2, unsubsetted).

  uv run --with fonttools==4.66.1 --with brotli==1.2.0 python tools/vendor-fonts.py [SRC_DIR]

SRC_DIR holds the Noto TTFs (default /usr/share/fonts/noto, Arch `noto-fonts`; the
upstream is https://github.com/notofonts). All faces are SIL OFL 1.1 (fonts/OFL.txt).
The faces are renamed "Publishing ..." (a Modified Version under the OFL; Noto reserves no
font name), so a PDF's font list proves that only vendored faces were embedded: any other
name is a host font. Copyright and licence records are kept.
Besides the WOFF2 files it writes coverage.txt: the code points the vendored faces
cover, which the build uses to flag a glyph that would fall back to a host font.
Changing a font changes rendering: that is a minor version bump.
"""
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

FACES = [
    "NotoSans-Regular", "NotoSans-Italic", "NotoSans-SemiBold", "NotoSans-Bold", "NotoSans-BoldItalic",
    "NotoSerif-Regular", "NotoSerif-Italic", "NotoSerif-Bold", "NotoSerif-BoldItalic",
    "NotoSansMono-Regular", "NotoSansMono-Bold",
    "NotoSansSymbols-Regular", "NotoSansSymbols2-Regular", "NotoSansMath-Regular",
]


RENAME = [("Noto Sans Symbols 2", "Publishing Symbols 2"), ("Noto Sans Symbols2", "Publishing Symbols2"),
          ("NotoSansSymbols2", "PublishingSymbols2"), ("Noto Sans Symbols", "Publishing Symbols"),
          ("NotoSansSymbols", "PublishingSymbols"), ("Noto Sans Math", "Publishing Math"),
          ("NotoSansMath", "PublishingMath"), ("Noto Sans Mono", "Publishing Mono"), ("NotoSansMono", "PublishingMono"),
          ("Noto Serif", "Publishing Serif"), ("NotoSerif", "PublishingSerif"), ("Noto Sans", "Publishing Sans"),
          ("NotoSans", "PublishingSans")]
KEEP = {0, 7, 8, 9, 10, 11, 12, 13, 14}  # copyright, trademark, vendor, designer, description, URLs, licence


def rename(font):
    for rec in font["name"].names:
        if rec.nameID in KEEP:
            continue
        text = rec.toUnicode()
        for old, new in RENAME:
            if old in text:
                text = text.replace(old, new)
                break
        rec.string = text


def ranges(cps):
    out, start, prev = [], None, None
    for c in sorted(cps):
        if start is None:
            start = prev = c
        elif c == prev + 1:
            prev = c
        else:
            out.append((start, prev))
            start = prev = c
    if start is not None:
        out.append((start, prev))
    return out


def main():
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "/usr/share/fonts/noto")
    dst = Path(__file__).resolve().parent.parent / "src/publishing/theme/fonts"
    dst.mkdir(parents=True, exist_ok=True)
    covered = set()
    for face in FACES:
        font = TTFont(src / f"{face}.ttf")
        covered |= set(font.getBestCmap())
        rename(font)
        font.flavor = "woff2"
        font.save(dst / f"{face}.woff2")
        print(face, (dst / f"{face}.woff2").stat().st_size)
    lines = [f"{a:X}-{b:X}" for a, b in ranges(covered)]
    (dst / "coverage.txt").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
