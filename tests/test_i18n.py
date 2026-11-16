"""Every language is complete: each text the code can show has a translation that keeps its placeholders, and
documents read and exported (PDF, PowerPoint, Excel) in each language use no text the catalog lacks."""
import json
import re
import shutil
import string
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import i18n_tools  # noqa: E402
from analyst import i18n  # noqa: E402

NEW = [c for c in i18n.LANGS if c not in ("it", "en")]


def fields(s: str) -> set:
    return {f for _, f, _, _ in string.Formatter().parse(s) if f}


@pytest.fixture(scope="module")
def static():
    return i18n_tools.static_keys()


@pytest.mark.parametrize("lang", NEW)
def test_catalog_is_complete_and_keeps_placeholders(lang, static):
    cat = json.loads((i18n.LOCALES / f"{lang}.json").read_text(encoding="utf-8"))
    missing = sorted(k for k in static if k not in cat)
    assert not missing, f"{lang}: {len(missing)} texts not translated, e.g. {missing[:5]}"
    for en, tr in cat.items():
        assert isinstance(tr, str) and tr.strip() or en.strip() == "", (lang, en)
        assert fields(tr) == fields(en), f"{lang}: placeholders differ in {en!r} -> {tr!r}"
        # a piece added after other text keeps its leading space (Chinese and Japanese use none)
        assert not en.startswith(" ") or tr.startswith(" ") or lang in i18n.CJK, f"{lang}: leading space lost in {en!r}"


@pytest.mark.parametrize("lang", NEW)
def test_documents_and_exports_use_only_translated_texts(lang, tmp_path):
    i18n.MISSING.clear()
    i18n_tools.exercise(lang, tmp_path)
    missing = sorted(en for code, en in i18n.MISSING if code == lang)
    assert not missing, f"{lang}: {missing[:10]}"


def test_numbers_and_dates_in_each_language():
    from datetime import date
    from analyst import financials as F, tables
    d = date(2026, 6, 30)
    expect = {"en": ("$16.3B", "+12.5%", "Jun 30, 2026", "H1 2026"), "it": ("$16,3 mld", "+12,5%", "30 giu 2026", "1° sem. 2026"),
              "de": ("$16,3 Mrd.", "+12,5 %", "30. Juni 2026", None), "fr": ("$16,3 Md", "+12,5 %", "30 juin 2026", None),
              "zh": ("$163亿", "+12.5%", "2026年6月30日", None), "ja": ("$163億", "+12.5%", "2026年6月30日", None),
              "ru": ("$16,3 млрд", "+12,5 %", "30 июн. 2026", None), "pt": ("$16,3 bi", "+12,5%", "30 jun 2026", None),
              "es": ("$16,3 mil M", "+12,5%", "30 jun 2026", "1.er sem. 2026")}
    for lang, (money, pct, day, half) in expect.items():
        with i18n.using(lang):
            assert F.fmt_money(16.286e9, "USD") == money, lang
            assert F.fmt_pct(0.125, signed=True) == pct, lang
            assert i18n.fmt_date(d) == day, lang
            if half:
                assert tables.period_label(6, d, lang) == half, lang
    with i18n.using("fr"):
        assert F.fmt_num(1234567.891) == "1 234 567,89"


def test_interface_language_follows_the_page(monkeypatch):
    from fastapi.testclient import TestClient
    import server
    c = TestClient(server.app, base_url="http://127.0.0.1:8765")
    c.cookies.set("sniffer_ui", "es")
    assert c.get("/api/status").json()["ui_lang"] == "es"
    assert c.post("/api/relang", json={"id": "x", "lang": "es"}).json()["detail"] == "solicitud no válida"
    assert '<html lang="es">' in c.get("/").text
    c.cookies.set("sniffer_ui", "xx")                       # unknown: the system's language
    assert c.get("/api/status").json()["ui_lang"] == i18n.system_lang()
    assert [x["code"] for x in c.get("/api/status").json()["langs"]] == list(i18n.LANGS)


def test_web_interface_has_every_language():
    js = (HERE.parent / "web" / "i18n.js").read_text(encoding="utf-8")
    assert re.search(r'LANGS = \[([^\]]+)\]', js).group(1).replace('"', "").replace(" ", "").split(",") == list(i18n.LANGS)
    for lang in i18n.LANGS:
        assert len(re.findall(rf"^  {lang}: \{{", js, re.M)) == 2, lang          # interface and report wording
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed: the keys of each language are not compared")
    check = """
      import { UI, REPORT, LANGS } from "%s";
      const bad = [];
      for (const [name, D] of [["UI", UI], ["REPORT", REPORT]])
        for (const l of LANGS)
          for (const k of Object.keys(D.en))
            if (typeof D[l][k] !== typeof D.en[k]) bad.push(`${name}.${l}.${k}`);
      console.log(JSON.stringify(bad));
    """ % (HERE.parent / "web" / "i18n.js").as_uri()
    out = subprocess.run([node, "--input-type=module", "-e", check], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == []


def test_ai_summary_is_checked_sentence_by_sentence_in_every_script():
    # a sentence with a number the pages do not print is dropped, the others stay (also without Latin capitals)
    from analyst import reader
    pages = {1: "Revenue 1,234 Net loss (56)"}
    for summary, kept in (("Выручка составила 1,234. Убыток составил 999.", "Выручка составила 1,234."),
                          ("营收为1,234。亏损为999。", "营收为1,234。"),
                          ("Revenue was 1,234. Loss was 999.", "Revenue was 1,234."),
                          ("营收为1,234。亏损为56。", "营收为1,234。亏损为56。")):
        res = {"summary": summary, "sections": [], "figures": [], "findings": []}
        assert reader.validate(res, pages, {})["summary"] == kept, summary
