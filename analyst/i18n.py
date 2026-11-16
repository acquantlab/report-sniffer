"""Languages.

Nine languages for the interface and the reports: English, Italian, Spanish, French, German, Portuguese (Brazil),
Russian, Chinese (Simplified) and Japanese. Scripts written right to left or with joined letters (Arabic, Hindi…)
are not among them: the PDF report cannot print them (see typefaces.py).

The code writes every text in Italian and English, t("Ricavi", "Revenue"); the other languages come from the
catalogs in analyst/locales/<lang>.json, keyed by the English text. A text with values is a template,
t("Ricavi {x}", "Revenue {x}", x=…), so that one key serves every value. A text missing from a catalog falls
back to English and is recorded in MISSING (the tests require it to stay empty).

Interface language: the one chosen in the page (a cookie the server reads per request), else the operating
system's language when it is one of these, else English; SNIFFER_LANG=<code> forces it.
Report language: chosen per analysis with `using(lang)`. Both live in context variables, so worker threads
never mix languages.

Numbers, amounts, percentages and dates are written each language's way (fmt_* helpers below and in
financials.py).

Standard library only: the launcher imports this module before the virtual environment exists.
"""
from __future__ import annotations

import contextvars
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Optional

LANGS = ("en", "it", "es", "fr", "de", "pt", "ru", "zh", "ja")
# the name of each language in that language (menus), and in English (the instruction to the AI)
NATIVE = {"en": "English", "it": "Italiano", "es": "Español", "fr": "Français", "de": "Deutsch", "pt": "Português",
          "ru": "Русский", "zh": "中文（简体）", "ja": "日本語"}
ENGLISH_NAME = {"en": "English", "it": "Italian", "es": "Spanish", "fr": "French", "de": "German",
                "pt": "Brazilian Portuguese", "ru": "Russian", "zh": "Simplified Chinese", "ja": "Japanese"}
CJK = ("zh", "ja")                     # no spaces between words: lines may break between any two characters

LOCALES = Path(__file__).resolve().parent / "locales"
_LANG = contextvars.ContextVar("report_lang", default="it")
_UI = contextvars.ContextVar("ui_lang", default="")
_catalogs: dict[str, dict] = {}
MISSING: set = set()                   # (lang, English text) asked for and not in the catalog


def lang() -> str:
    return _LANG.get()


def catalog(code: str) -> dict:
    if code not in _catalogs:
        try:
            _catalogs[code] = json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _catalogs[code] = {}
    return _catalogs[code]


def _pick(code: str, it: str, en: str, kw: dict) -> str:
    if code == "it":
        s = it
    elif code == "en" or code not in LANGS:
        s = en
    else:
        s = catalog(code).get(en)
        if s is None:
            MISSING.add((code, en))
            s = en
    return s.format(**kw) if kw else s


def t(it: str, en: str, **kw) -> str:
    """Text in the report language."""
    return _pick(_LANG.get(), it, en, kw)


def tl(code: str, it: str, en: str, **kw) -> str:
    """Text in a given language."""
    return _pick(code, it, en, kw)


@contextmanager
def using(code: str):
    token = _LANG.set(code if code in LANGS else "en")
    try:
        yield
    finally:
        _LANG.reset(token)


# ---------------------------------------------------------------- interface language

def _mac_lang() -> Optional[str]:
    try:
        out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r'"?([A-Za-z]{2})[-_A-Za-z]*"?', out.replace("(", " "))
    return m.group(1).lower() if m else None


# Windows primary language ids (the low 10 bits of a LANGID)
_WIN_LANGS = {0x09: "en", 0x10: "it", 0x0a: "es", 0x0c: "fr", 0x07: "de", 0x16: "pt", 0x19: "ru", 0x04: "zh", 0x11: "ja"}


def _windows_lang() -> Optional[str]:
    try:
        import ctypes
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except (AttributeError, OSError):
        return None
    return _WIN_LANGS.get(langid & 0x3FF)


def _env_lang() -> Optional[str]:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        v = os.environ.get(var, "")
        if v and v not in ("C", "POSIX") and not v.startswith("C."):
            return v[:2].lower()
    return None


_SYSTEM: Optional[str] = None


def system_lang() -> str:
    """The operating system's language when it is one of LANGS, otherwise 'en' (SNIFFER_LANG forces one)."""
    global _SYSTEM
    forced = os.environ.get("SNIFFER_LANG", "").lower()
    if forced in LANGS:
        return forced
    if _SYSTEM is None:
        if sys.platform == "darwin":
            code = _mac_lang() or _env_lang()
        elif os.name == "nt":
            code = _windows_lang()
        else:
            code = _env_lang()
        _SYSTEM = code if code in LANGS else "en"
    return _SYSTEM


def ui_lang() -> str:
    """The interface language: chosen in the page for this request, else the system's."""
    return _UI.get() or system_lang()


@contextmanager
def using_ui(code: str):
    token = _UI.set(code if code in LANGS else "")
    try:
        yield
    finally:
        _UI.reset(token)


def set_ui(code: str) -> None:
    """For the rest of this request (a server middleware calls it)."""
    _UI.set(code if code in LANGS else "")


def ui(it: str, en: str, **kw) -> str:
    """Text in the interface language (messages shown by the app)."""
    return _pick(ui_lang(), it, en, kw)


# ---------------------------------------------------------------- numbers and dates

# thousands separator, decimal separator
SEPARATORS = {"en": (",", "."), "zh": (",", "."), "ja": (",", "."), "it": (".", ","), "es": (".", ","), "de": (".", ","),
              "pt": (".", ","), "fr": (" ", ","), "ru": (" ", ",")}
PERCENT = {"fr": " %", "de": " %", "ru": " %"}          # "12,5 %"; elsewhere "12.5%"
MONTHS = {
    "en": "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec",
    "it": "gen feb mar apr mag giu lug ago set ott nov dic",
    "es": "ene feb mar abr may jun jul ago sept oct nov dic",
    "fr": "janv. févr. mars avr. mai juin juil. août sept. oct. nov. déc.",
    "de": "Jan. Feb. März Apr. Mai Juni Juli Aug. Sept. Okt. Nov. Dez.",
    "pt": "jan fev mar abr mai jun jul ago set out nov dez",
    "ru": "янв. февр. мар. апр. мая июн. июл. авг. сент. окт. нояб. дек.",
    "zh": "1月 2月 3月 4月 5月 6月 7月 8月 9月 10月 11月 12月",
    "ja": "1月 2月 3月 4月 5月 6月 7月 8月 9月 10月 11月 12月",
}


def months(code: Optional[str] = None) -> list[str]:
    return MONTHS.get(code or lang(), MONTHS["en"]).split()


def num(s: str, code: Optional[str] = None) -> str:
    """A number written the English way ("1,234.5") written the way of the language ("1.234,5", "1 234,5")."""
    thousands, decimal = SEPARATORS.get(code or lang(), (",", "."))
    if (thousands, decimal) == (",", "."):
        return s
    return s.replace(",", "\x00").replace(".", decimal).replace("\x00", thousands)


def pct_sign(code: Optional[str] = None) -> str:
    return PERCENT.get(code or lang(), "%")


def fmt_date(d: date, code: Optional[str] = None) -> str:
    """A day in the language: "Jun 30, 2026", "30 giu 2026", "30. Juni 2026", "2026年6月30日"."""
    code = code or lang()
    m = months(code)[d.month - 1]
    if code == "en":
        return f"{m} {d.day}, {d.year}"
    if code in CJK:
        return f"{d.year}年{d.month}月{d.day}日"
    if code == "de":
        return f"{d.day}. {m} {d.year}"
    return f"{d.day} {m} {d.year}"


def fmt_month(month: int, year: int, code: Optional[str] = None) -> str:
    """A month of a year: "Jun 2026", "giu 2026", "2026年6月"."""
    code = code or lang()
    return f"{year}年{month}月" if code in CJK else f"{months(code)[month - 1]} {year}"
