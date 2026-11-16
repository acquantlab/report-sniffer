"""Fonts of the PDF report, so that a name in Greek, Russian, Japanese, Chinese or Korean is printed, not lost.

The standard PDF fonts (Helvetica) cover Western European letters only. The report uses Liberation Sans instead:
the same metrics as Helvetica, so the layout does not change, plus Greek and Cyrillic. Text in other scripts is
split into runs, and each run is drawn with the first font that has its characters: Droid Sans Fallback (Chinese,
Japanese), then Nanum Gothic (Korean). Those two are loaded only when a report needs them. Fonts are embedded as
subsets, so a report carries only the glyphs it uses. Files and licenses: analyst/fonts/.

Not covered: scripts written right to left or with joined letters (Arabic, Hebrew, Devanagari, Thai), which need
shaping that reportlab does not do.
"""
from __future__ import annotations

import threading
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.fonts import addMapping
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

DIR = Path(__file__).resolve().parent / "fonts"
SANS, SANS_B, SANS_I = "RS-Sans", "RS-Sans-Bold", "RS-Sans-Italic"
BASE = {SANS: "LiberationSans-Regular.ttf", SANS_B: "LiberationSans-Bold.ttf", SANS_I: "LiberationSans-Italic.ttf"}
FALLBACKS = {"RS-CJK": "DroidSansFallbackFull.ttf", "RS-Hangul": "NanumGothic.ttf"}      # tried in this order

_lock = threading.Lock()
_base: set = set()                     # code points of the main font
_fallbacks: list = []                  # [(name, code points)] once loaded


def _family(normal: str, bold: str, italic: str) -> None:
    """What <b> and <i> pick inside a paragraph (no bold italic: bold)."""
    for b, i, face in ((0, 0, normal), (1, 0, bold), (0, 1, italic), (1, 1, bold)):
        addMapping(normal, b, i, face)


def _load(name: str, file: str) -> set:
    font = TTFont(name, str(DIR / file))
    pdfmetrics.registerFont(font)
    return set(font.face.charToGlyph)


def register() -> None:
    """The main font family (cheap); called before drawing."""
    with _lock:
        if not _base:
            cps = {name: _load(name, file) for name, file in BASE.items()}
            _family(SANS, SANS_B, SANS_I)
            _base.update(cps[SANS] & cps[SANS_B])


def _load_fallbacks() -> list:
    with _lock:
        if not _fallbacks:
            for name, file in FALLBACKS.items():
                cps = _load(name, file)
                _family(name, name, name)          # one style only
                _fallbacks.append((name, cps))
        return _fallbacks


def runs(text: str) -> list[tuple[str, str]]:
    """[(font, or "" for the main font; piece of text)]. A space stays in the run it is in when that font has it."""
    register()
    out: list[list] = []
    for ch in text:
        cp = ord(ch)
        if ch.isspace() and out and (not out[-1][0] or cp in dict(_fallbacks).get(out[-1][0], ())):
            font = out[-1][0]
        elif cp in _base or ch.isspace():
            font = ""
        else:
            font = next((name for name, cps in _load_fallbacks() if cp in cps), "")
        if out and out[-1][0] == font:
            out[-1][1] += ch
        else:
            out.append([font, ch])
    return [(f, s) for f, s in out]


def markup(text: str) -> str:
    """Escaped paragraph markup; runs the main font lacks are wrapped in the font that has them."""
    return "".join(escape(s) if not f else f'<font name="{f}">{escape(s)}</font>' for f, s in runs(text))


def width(text: str, font: str, size: float) -> float:
    return sum(pdfmetrics.stringWidth(s, f or font, size) for f, s in runs(text))


def draw(c, x: float, y: float, text: str, font: str, size: float, anchor: str = "left") -> None:
    """canvas.drawString with fallback fonts; anchor "left", "right" or "center"."""
    pieces = runs(text)
    w = sum(pdfmetrics.stringWidth(s, f or font, size) for f, s in pieces)
    x -= w if anchor == "right" else w / 2 if anchor == "center" else 0
    for f, s in pieces:
        c.setFont(f or font, size)
        c.drawString(x, y, s)
        x += pdfmetrics.stringWidth(s, f or font, size)
