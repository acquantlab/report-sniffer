"""The PDF report prints names in Greek, Cyrillic, Chinese, Japanese and Korean instead of dropping them."""
import json
import sys
from pathlib import Path

import pypdfium2 as pdfium
import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import make_s1  # noqa: E402
from analyst import ai, pdfreport, pipeline, typefaces  # noqa: E402

NAMES = {"greek": "Ελληνικά Πετρέλαια", "cyrillic": "Газпром нефть", "japanese": "日本電産株式会社",
         "chinese": "贵州茅台 台積電", "korean": "삼성전자", "latin": "Škoda Łódź & Ørsted"}


@pytest.fixture(scope="module")
def analysis(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setattr(pipeline, "DOCS", tmp_path_factory.mktemp("docs"))
    mp.setattr(ai, "active", lambda: None)
    a = json.loads(json.dumps(pipeline.run({"kind": "upload", "data": make_s1.s1().encode(), "name": "s1.htm", "lang": "en"}, lambda *_: None)))
    mp.undo()
    return a


def pdf_text(data: bytes) -> str:
    pdf = pdfium.PdfDocument(data)
    return "\n".join(pdf[i].get_textpage().get_text_range() for i in range(len(pdf)))


@pytest.mark.parametrize("script", list(NAMES))
def test_names_in_every_script_are_printed(analysis, script):
    a = dict(analysis, title=NAMES[script], findings=[{"text": f"{NAMES[script]}: revenue up.", "pages": [1]}] + analysis["findings"])
    text = pdf_text(pdfreport.build(a))
    assert text.count(NAMES[script]) >= 3, script          # title, finding, footer of every page
    assert "&amp;" not in text                               # the footer is plain text, not markup


def test_runs_pick_the_font_that_has_the_characters():
    assert typefaces.runs("Revenue Ελληνικά") == [("", "Revenue Ελληνικά")]
    assert typefaces.runs("Nidec 日本電産 (6594)") == [("", "Nidec "), ("RS-CJK", "日本電産 "), ("", "(6594)")]
    assert [f for f, _ in typefaces.runs("삼성전자 Samsung")] == ["RS-Hangul", ""]
    assert typefaces.markup("A&B <日本>") == 'A&amp;B &lt;<font name="RS-CJK">日本</font>&gt;'


def test_layout_and_size_unchanged_for_latin_documents(analysis):
    # Liberation Sans has Helvetica's metrics; only the glyphs used are embedded
    data = pdfreport.build(analysis)
    assert len(data) < 400_000
    assert b"DroidSansFallback" not in data and b"NanumGothic" not in data
    data = pdfreport.build(dict(analysis, title=NAMES["japanese"]))
    assert b"DroidSansFallback" in data and len(data) < 600_000           # a subset, not the 4 MB font


def drawn_without_glyph(data: bytes) -> list[str]:
    """Characters printed in a font that has no glyph for them (empty boxes). reportlab gives them no text mapping,
    so the PDF's text layer has nothing there: pdfium reads them as empty strings."""
    import ctypes
    import pypdfium2.raw as R
    bad = []
    pdf = pdfium.PdfDocument(data)
    buf = ctypes.create_string_buffer(256)
    for i in range(len(pdf)):
        tp = pdf[i].get_textpage()
        for k in range(tp.count_chars()):
            if tp.get_text_range(k, 1) == "":
                R.FPDFText_GetFontInfo(tp.raw, k, buf, 256, None)
                bad.append(f"page {i + 1}, char {k}, font {buf.value.decode(errors='replace')}")
    return bad


@pytest.mark.parametrize("lang", ["zh", "ja", "ru", "de", "fr"])
def test_every_character_has_a_glyph(analysis, lang, tmp_path):
    # the whole report written in each language, plus document names in other scripts: nothing printed as an empty box
    mp = pytest.MonkeyPatch()
    mp.setattr(pipeline, "DOCS", tmp_path)
    mp.setattr(ai, "active", lambda: None)
    import synth
    from analyst import sources
    mp.setattr(sources, "price_history", lambda s: synth.series())
    try:
        docs = [pipeline.run({"kind": "upload", "data": make_s1.s1().encode(), "name": "s1.htm", "lang": lang}, lambda *_: None),
                pipeline.run({"kind": "market", "symbol": "TEST-USD", "lang": lang}, lambda *_: None)]
    finally:
        mp.undo()
    for a in docs:
        a = json.loads(json.dumps(a))
        a["title"] = "日本電産 · Ελληνικά · 삼성전자"
        assert drawn_without_glyph(pdfreport.build(a)) == [], a["kind"]
