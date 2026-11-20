"""Optical character recognition (OCR) for PDF pages without real text: scans, and pages whose fonts map their glyphs
to codes that are not letters (the text layer of McDonald's earnings releases). RapidOCR with the PP-OCR models on
ONNX Runtime, on this computer and offline (the models come with the package)."""
import re
import threading

SCALE = 2.0                     # pages are read at 144 dpi: at 72 dpi the models misread small print
MIN_SCORE = 0.5                 # text the models are less sure of is left out

_engine = None
_lock = threading.Lock()


def _get():
    global _engine
    if _engine is None:
        try:
            from rapidocr import RapidOCR
            # upright text only: no angle classifier (about 5% faster)
            _engine = RapidOCR(params={"Global.log_level": "critical", "Global.use_cls": False})
        except Exception:      # not installed, or its native libraries cannot load: pages without text stay unread
            _engine = False
    return _engine


def available() -> bool:
    with _lock:
        return bool(_get())


def read(image, scale: float = SCALE) -> list[dict]:
    """Words on a page image (PIL) as the PDF reader gives them: text and box in PDF points, from the top left.
    The models give one box per run of text; a run is split into its words in proportion to their characters."""
    import numpy as np

    with _lock:
        eng = _get()
        if not eng:
            return []
        r = eng(np.asarray(image.convert("RGB")))
    if r.boxes is None or r.txts is None:
        return []
    words = []
    for box, text, score in zip(r.boxes, r.txts, r.scores):
        text = (text or "").strip()
        if not text or float(score) < MIN_SCORE:
            continue
        xs, ys = [float(p[0]) / scale for p in box], [float(p[1]) / scale for p in box]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        cw = (x1 - x0) / len(text)
        for m in re.finditer(r"\S+", text):
            words.append({"t": m.group(), "x": x0 + m.start() * cw, "y": y0, "w": max((m.end() - m.start()) * cw, 1),
                          "h": max(y1 - y0, 4)})
    return words
