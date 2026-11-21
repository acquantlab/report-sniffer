"""Untagged documents: PDF (KID, prospectus, factsheet, whitepaper, annual report) and plain HTML.

There are no XBRL tags here, so figures are found heuristically: every number on
the page is a candidate, labelled with the words before it on the same line (or
the table row it sits in) and ranked by financial keywords. The pages shown are the
ones densest with figures (and, in HTML, the ones holding the statements).
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from statistics import median
from typing import Optional

from lxml import etree, html as lxml_html

from . import ixbrl
from .i18n import t

KEYWORDS = {
    # weight 3: headline figures
    "ricavi": 3, "fatturato": 3, "revenue": 3, "revenues": 3, "net sales": 3, "utile netto": 3, "net income": 3, "net profit": 3,
    "risultato netto": 3, "ebitda": 3, "ebit": 3, "free cash flow": 3, "eps": 3, "per azione": 3, "per share": 3,
    "indicatore sintetico di rischio": 3, "summary risk indicator": 3, "sri": 3, "spese correnti": 3, "ongoing charges": 3,
    "ter": 3, "costi totali": 3, "total costs": 3, "cedola": 3, "coupon": 3, "rendimento": 3, "yield": 3, "nav": 3,
    "total supply": 3, "max supply": 3, "market cap": 3, "capitalizzazione": 3,
    # weight 2
    "utile": 2, "profit": 2, "margine": 2, "margin": 2, "cassa": 2, "cash": 2, "debito": 2, "debt": 2, "indebitamento": 2,
    "patrimonio": 2, "equity": 2, "dividend": 2, "dividendo": 2, "performance": 2, "return": 2, "scenario": 2, "costi": 2,
    "costs": 2, "commission": 2, "fee": 2, "fees": 2, "volatilit": 2, "rischio": 2, "risk": 2, "scadenza": 2, "maturity": 2,
    "prezzo": 2, "price": 2, "supply": 2, "token": 2, "emission": 2, "crescita": 2, "growth": 2, "perdita": 2, "loss": 2,
    "attivo": 2, "assets": 2, "liabilities": 2, "passivit": 2, "investimenti": 2, "capex": 2, "operating": 2, "operativ": 2,
    # weight 1
    "totale": 1, "total": 1, "anno": 1, "year": 1, "periodo": 1, "period": 1, "netto": 1, "net": 1, "lordo": 1, "gross": 1,
}
NUM_RE = re.compile(r"^[(\-−–+]?(?:[€$£¥]|EUR|USD)?\s?\d[\d.,'’ ]*%?\)?$")
INLINE_NUM = re.compile(r"(?<![\w.,])[(\-−–+]?(?:[€$£¥]\s?)?\d{1,3}(?:[.,'’ ]\d{3})+(?![\d])(?:[.,]\d+)?%?\)?|(?<![\w.,])[(\-−–+]?(?:[€$£¥]\s?)?\d+(?:[.,]\d+)?%?\)?")
MONTH_END = re.compile(r"(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
                       r"|gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\.?\s*$", re.I)
MAX_PAGES_SHOWN = 8
MAX_OCR_PAGES = 400             # pages read with OCR (about 1-2 s each)
MAX_FACTS_PAGE = 400


def parse_loose(t: str, sep: Optional[str] = None) -> Optional[float]:
    """A printed amount as a number; sep, the document's thousands separator when known, settles "5.045" and "5,045"."""
    s = t.strip().replace("−", "-").replace("–", "-").replace("’", "").replace("'", "").replace(" ", "").replace(" ", "")
    neg = s.startswith("(") or s.startswith("-")         # "(2,597)", also when the PDF splits off the ")"
    s = re.sub(r"[^\d.,]", "", s)
    if not s or not any(c.isdigit() for c in s):
        return None
    if sep and ("," in s) != ("." in s):
        mark = "," if "," in s else "."
        if mark != sep:                                   # the decimal mark: "5.045" where thousands are "1,234"
            s = s.replace(mark, ".") if s.count(mark) == 1 else s.replace(mark, "")
        else:
            s = s.replace(mark, "")
        try:
            v = float(s)
        except ValueError:
            return None
        return -v if neg else v
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec == "," else ",", "").replace(",", ".")
    elif "," in s or "." in s:
        sep = "," if "," in s else "."
        parts = s.split(sep)
        if len(parts) > 2 or (len(parts[-1]) == 3 and parts[0] not in ("0", "")):
            s = s.replace(sep, "")
        else:
            s = s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


# words of statement titles and rows that some PDFs print with a space inside ("Balance Shee t", "Comp rehensive")
_VOCAB = ("consolidated", "consolidating", "condensed", "statements", "statement", "balance", "sheets", "sheet", "income", "operations",
          "earnings", "comprehensive", "flows", "equity", "financial", "position", "condition", "shareholders", "stockholders",
          "shareowners", "changes", "revenues", "revenue", "assets", "liabilities", "diluted", "investing", "financing", "operating",
          "activities", "expenses", "provision", "taxes", "equivalents")
_SPLIT = re.compile(r"\b(?:" + "|".join(" ?".join(w) for w in sorted(_VOCAB, key=len, reverse=True)) + r")\b", re.I)


_LIG = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl"}


def ligatures(text: str) -> str:
    """Ligatures as letters: "ﬁ" as "fi", and the "fi"/"fl" some PDFs give as an unknown character ("bene\ufffet",
    "Cash \ufffeows", "\ufffenancing")."""
    if not any(c in text for c in "\ufffe\ufffd\ufb00\ufb01\ufb02\ufb03\ufb04"):
        return text
    for k, v in _LIG.items():
        text = text.replace(k, v)
    text = re.sub(r"[\ufffe\ufffd](?=cien)", "ffi", text)                             # "su\ufffecient"
    text = re.sub(r"[\ufffe\ufffd](?=(ect|ice|er|set|ord|ort))", "ff", text)          # "E\ufffeect of exchange", "o\ufffeset"
    text = re.sub(r"[\ufffe\ufffd](?=(ow|uct|ex|oor|eet|at|ag|ight|y)\w*)", "fl", text)
    return re.sub(r"(?<=\w)[\ufffe\ufffd](?=\w)|[\ufffe\ufffd](?=[a-z])", "fi", text)


def garbled(text: str) -> bool:
    """A text layer that is not text: fonts that map their glyphs to other codes give symbols and control characters
    ("!0+"!\x07b#$\x07"c 3\x07e0'+3'"), with few letters and fewer vowels. On 358 real PDFs a page of text has at
    least 77% letters and 37% vowels among them; such a page (McDonald's) 24% and 12%."""
    s = re.sub(r"\s", "", text)
    if len(s) < 200:
        return False
    ctrl = sum(1 for c in s if ord(c) < 32)
    letters = sum(c.isalpha() for c in s)
    words = re.findall(r"[A-Za-z]{2,}", text)
    total = sum(len(w) for w in words)
    vowels = sum(1 for w in words for c in w.lower() if c in "aeiou") / total if total else 0
    return ctrl > 0.05 * len(s) or (letters < 0.5 * len(s) and vowels < 0.25)


def unsplit(text: str) -> str:
    """Statement words the PDF spaces apart ("Consolidated Balance Shee t", "Statements of Comp rehensive Income")."""
    return _SPLIT.sub(lambda m: m.group().replace(" ", ""), text) if " " in text else text


def is_figure(token: str, allow_digit: bool = False) -> bool:
    t = token.strip()
    if not NUM_RE.match(t) or len(t) > 24:
        return False
    digits = re.sub(r"\D", "", t)
    if not digits:
        return False
    # years (also inside a sentence: "2022," "2021."), footnote marks and lone small integers are rarely the figures we want
    if re.fullmatch(r"(19|20)\d\d[,.;:]?", t):
        return False
    if re.fullmatch(r"\d", t) and not allow_digit:
        return False
    if re.fullmatch(r"\d{1,2}(\.\d{1,2}){2,}\.?", t):
        return False                                    # a note number with dots ("2.1.6", "3.2.17"), not an amount
    return True


def score_label(label: str) -> int:
    lo = " " + label.lower() + " "
    best = 0
    for k, w in KEYWORDS.items():
        if len(k) <= 3:
            if re.search(rf"\b{re.escape(k)}\b", lo):
                best = max(best, w)
        elif k in lo:
            best = max(best, w)
    return best


# ---------------------------------------------------------------- PDF

def _image_page(page, size) -> bool:
    """A page that is mostly a picture: a scan, or a table pasted as an image."""
    import pypdfium2.raw as pdfium_c

    area = 0.0
    try:
        for obj in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=3):
            l, b, r, t = (obj.get_bounds if hasattr(obj, "get_bounds") else obj.get_pos)()     # pypdfium2 5 / 4
            area += max(0.0, r - l) * max(0.0, t - b)
    except Exception:          # an object the library cannot measure: the page keeps its own text
        return False
    return area >= 0.25 * size[0] * size[1]


def needs_ocr(pdf, i: int, text: str, size) -> bool:
    """A page without real text: a text layer of glyph codes, or a picture of the page with (almost) no text."""
    if garbled(text):
        return True
    if len(re.sub(r"\s", "", text)) >= 200:
        return False
    page = pdf[i]
    try:
        return _image_page(page, size)
    finally:
        page.close()


def pdf_document(data: bytes, img_dir: Path, img_url: str, on_ocr=None) -> dict:
    """PDF -> page images + transparent word layer (so the sniffer can find the words).
    Pages without real text (scans, glyph codes) are read with OCR; on_ocr(done, total) follows it."""
    import pypdfium2 as pdfium

    from . import ocr

    pdf = pdfium.PdfDocument(data)
    n = len(pdf)
    if n == 0:
        raise ValueError("PDF senza pagine")
    # 1) choose the pages from plain text (fast); 2) word boxes only for the chosen pages
    sizes, texts = [], []
    for i in range(n):
        page = pdf[i]
        sizes.append(page.get_size())
        tp = page.get_textpage()
        # words some PDFs separate with no-break spaces or bare line feeds ("Consolidated\nStatements\nof\nIncome")
        texts.append(unsplit(ligatures(re.sub(r"(?<!\r)\n|\xa0", " ", tp.get_text_range() or ""))))
        tp.close()
        page.close()
    # pages without real text: a text layer of glyph codes, or a picture of the page with (almost) no text. They are read
    # with OCR; those it cannot read (OCR missing) give no figures, which would be made up of glyph codes
    need = [i for i, txt in enumerate(texts) if needs_ocr(pdf, i, txt, sizes[i])]
    ocr_words = {}
    if need and ocr.available():
        need = need[:MAX_OCR_PAGES]
        for k, i in enumerate(need):
            if on_ocr:
                on_ocr(k, len(need))
            page = pdf[i]
            words = ocr.read(page.render(scale=ocr.SCALE).to_pil(), ocr.SCALE)
            page.close()
            if words:
                ocr_words[i] = words
                texts[i] = unsplit("\r\n".join(" ".join(wd["t"] for wd in ln) for ln in _lines(words)))
    bad = {i for i, t in enumerate(texts) if garbled(t)}
    chosen = [i for i in best_pages([("" if i in bad else t) for i, t in enumerate(texts)]) if i not in bad] or best_pages(texts)[:1]
    pages_words = {}
    for i in chosen:
        if i in ocr_words:
            pages_words[i] = join_groups(ocr_words[i])
            continue
        page = pdf[i]
        tp = page.get_textpage()
        pages_words[i] = join_groups(_words(tp, sizes[i][1]))
        tp.close()
        page.close()

    sep = thousands_sep([w for ws in pages_words.values() for w in ws])
    img_dir.mkdir(parents=True, exist_ok=True)
    out_pages, facts, headings, page_text = [], [], [], []
    for i in chosen:
        w, h = sizes[i]
        scale = 96 / 72
        bmp = pdf[i].render(scale=2.0)
        bmp.to_pil().convert("RGB").save(img_dir / f"p{i + 1}.jpg", quality=88)   # JPEG: ~50x faster than PNG
        words = pages_words[i]
        figs = {} if i in bad else {id(f["word"]): f for f in _label_figures(words, sep)}
        keep = sorted(figs.values(), key=lambda f: -f["score"])[:MAX_FACTS_PAGE]
        keep_ids = {id(f["word"]) for f in keep}
        hsize = median([wd["h"] for wd in words]) if words else 10
        spans = []
        line_heads = _heading_lines(words, hsize)
        for wd in words:
            style = (f"left:{wd['x'] * scale:.1f}px;top:{wd['y'] * scale:.1f}px;width:{wd['w'] * scale:.1f}px;"
                     f"height:{wd['h'] * scale:.1f}px;font-size:{wd['h'] * scale * 0.92:.1f}px")
            attrs = ""
            if id(wd) in keep_ids:
                f = figs[id(wd)]
                fid = len(facts)
                facts.append({"id": fid, "label": f["label"] or t("Cifra", "Figure"), "value": f["value"], "display": wd["t"], "page": i + 1,
                              "kind": "num", "col": "Valore", "key": f["score"] >= 2, "score": f["score"], "inline": f["inline"],
                              "x1": round(wd["x"] + wd["w"], 1), "y": round(wd["y"] + wd["h"] / 2, 1)})
                attrs = f' class="w xf" data-f="{fid}"'
            elif id(wd) in line_heads:
                hid = len(headings)
                headings.append({"id": hid, "text": line_heads[id(wd)], "page": i + 1})
                attrs = f' class="w" data-h="{hid}"'
            else:
                attrs = ' class="w"'
            spans.append(f'<span{attrs} style="{style}">{html.escape(wd["t"])}</span>')
        out_pages.append({
            "n": i + 1,
            "html": (f'<div class="pdfpage" style="width:{w * scale:.0f}px;height:{h * scale:.0f}px">'
                     f'<img src="{img_url}/p{i + 1}.jpg" alt="">{"".join(spans)}</div>'),
        })
        page_text.append(unsplit(" ".join(wd["t"] for wd in words)))
    meta = clean_title((pdf.get_metadata_dict().get("Title") or "").strip())
    if re.search(r"_|\d[\d.-]{3,}|^exhibit|^ex-?\d", meta, re.I):
        meta = company_line(texts[:2]) or meta                   # "Q1 23_EarningsRelease", "Exhibit 99.1 - 6.30.2023"
    title = cover_name(texts[:3]) or meta or company_line(texts[:2])
    pdf.close()
    return {"pages": out_pages, "facts": facts, "headings": headings, "page_text": page_text, "all_text": texts,
            "total_pages": n, "title": title, "css": PDF_CSS, "ocr": sorted(i + 1 for i in ocr_words),
            "garbled": len(bad) >= max(1, len([t for t in texts if t.strip()]) // 2)}


def cover_name(texts: list[str]) -> str:
    """The registrant's name on an SEC cover page: the line above "(Exact name of registrant as specified in its charter)"."""
    for txt in texts:
        lines = [ln.strip() for ln in re.split(r"[\r\n]+", txt) if ln.strip()]
        for i, ln in enumerate(lines):
            if re.search(r"exact name of (the )?registrants?", ln, re.I) and i > 0:
                # the nearest line above that reads like a name (not "Commission File Number", "____", a date…)
                for name in reversed(lines[max(0, i - 4):i]):
                    name = re.sub(r"[_\s]+", " ", name).strip(" ,:")
                    if not re.search(r"(\b\w{1,4}|\.\w+)\.$", name):
                        name = name.rstrip(".")                # a sentence's full stop, not "Inc." / "Corp." / "N.V."
                    if re.search(r"commission|file number|transition period|registrant|incorporation|identification|^\(?\d|^form\b|"
                                 r"securities|exchange act|fiscal year|quarterly period", name, re.I):
                        continue
                    if 3 <= len(name) <= 90 and sum(c.isalpha() for c in name) >= 3:
                        return name.title() if name.isupper() else name
                    break
    return ""


COMPANY_LINE = re.compile(r"^([A-Z][A-Za-z&.,'’ -]{1,60}?\s(Inc\.?|Incorporated|Corporation|Corp\.?|Company|Co\.|plc|PLC|N\.V\.|S\.p\.A\.|SpA|"
                          r"AG|SE|S\.A\.|SA|Ltd\.?|Limited|LLC|L\.P\.|Group|Holdings?))(?![A-Za-z])")


def company_line(texts: list[str]) -> str:
    """A company name standing on its own line near the top ("Intel Corporation", "Amcor plc")."""
    for txt in texts:
        for ln in [ln.strip() for ln in re.split(r"[\r\n]+", txt) if ln.strip()][:40]:
            m = COMPANY_LINE.match(ln)
            if m and len(ln) <= len(m.group(1)) + 40:
                return m.group(1).strip(" ,")
    return ""


def clean_title(title: str) -> str:
    """PDF metadata titles that are not titles: accession numbers, "UNITED STATES", word-processor names."""
    title = title.strip()
    m = re.fullmatch(r"form \S+ for (.+?) filed .*", title, re.I)       # EDGAR printouts: "Form 10-Q for FOOT LOCKER INC filed …"
    if m:
        name = m.group(1).title() if m.group(1).isupper() else m.group(1)
        return re.sub(r"\b(INC|CORP|CO)\b\.?$", lambda x: x.group(1).title() + ".", name)
    if re.fullmatch(r"[\d-]{10,}|untitled|united states|microsoft word.*|document\d*|.*\.(docx?|pdf|htm)|form \S+|exhibit [\d.]+( - [\d./]+)?",
                    title, re.I):
        return ""
    return title


def best_pages(texts: list[str], n: int = MAX_PAGES_SHOWN) -> list[int]:
    """The first page and the pages that look like they hold the figures that matter (0-based)."""
    from . import statements
    first = next((i for i, t in enumerate(texts) if t.strip()), 0)
    keep = {first} | set(statements.statement_pages(texts))          # the statements themselves, always
    cand = sorted(((_score_text(txt), i) for i, txt in enumerate(texts) if i not in keep), reverse=True)
    return sorted(keep | {i for sc, i in cand[:max(0, n - len(keep))] if sc > 0})


def _score_text(text: str) -> float:
    """How much a page looks like it holds the figures that matter (plain text, no layout)."""
    from . import statements
    score, nfig = 0.0, 0
    for line in text.splitlines():
        label: list[str] = []
        row_figs = 0
        for tok in line.split():
            if is_figure(tok, allow_digit=True):
                sc = score_label(" ".join(label[-9:]))
                if re.fullmatch(r"\d", tok) and sc < 3:
                    continue
                score += sc + (0.5 if tok.endswith("%") else 0)
                nfig += 1
                row_figs += 1
            elif not re.fullmatch(r"[\W\d]+", tok):
                label.append(tok)
        if row_figs and label and statements.match(" ".join(label)):
            score += 2                                     # a financial statement row
    if statements.title_match(text):
        score += 30                                        # a page titled as a statement
    return score + 0.1 * nfig


def _words(tp, page_h: float) -> list[dict]:
    n = tp.count_chars()
    if n <= 0:
        return []
    text = tp.get_text_range(0, n)
    per_char = len(text) != n
    words, cur, box = [], [], None

    def flush():
        nonlocal cur, box
        if cur and box:
            t = ligatures("".join(cur).strip())
            if t:
                x0, y0, x1, y1 = box
                words.append({"t": t, "x": x0, "y": page_h - y1, "w": max(x1 - x0, 1), "h": max(y1 - y0, 4)})
        cur, box = [], None

    for i in range(n):
        ch = tp.get_text_range(i, 1) if per_char else text[i]
        if not ch or ch.isspace() or ch in "\r\n\x02":
            flush()
            continue
        l, b, r, t = tp.get_charbox(i, loose=True)
        if r - l <= 0 and t - b <= 0:
            continue
        if box:
            bh = max(box[3] - box[1], t - b, 1)
            cy = (b + t) / 2
            if l - box[2] > 0.8 * bh or not (box[1] - 1 <= cy <= box[3] + 1):
                flush()
        cur.append(ch)
        box = [l, b, r, t] if box is None else [min(box[0], l), min(box[1], b), max(box[2], r), max(box[3], t)]
    flush()
    return words


def join_groups(words: list[dict]) -> list[dict]:
    """Amounts whose thousands are set apart by a (thin) space, as European reports print them ("9 118", "(197 034)",
    "1 234 567,8"), as one word: two words on a line, the first of one to three digits (or a group already joined), the
    second of three digits, closer than a word space. Columns of amounts lie much further apart."""
    out: list[dict] = []
    for wd in words:
        if out:
            a = out[-1]
            gap = wd["x"] - (a["x"] + a["w"])
            same_line = abs((a["y"] + a["h"] / 2) - (wd["y"] + wd["h"] / 2)) < 0.4 * min(a["h"], wd["h"])
            h = max(a["h"], wd["h"])
            joined = None
            if same_line and -1.5 <= gap <= 0.12 * h and re.fullmatch(r"[(\-−–€$£\d][\d,.]*", a["t"]) and re.fullmatch(r"[\d,.][\d,.]*\)?%?", wd["t"]) \
                    and AMOUNT.fullmatch(a["t"] + wd["t"]) and (_open(a["t"]) or re.match(r"[,.]", wd["t"]) or wd["t"].count(")") > wd["t"].count("(")):
                joined = a["t"] + wd["t"]                 # one amount the PDF breaks into touching pieces ("23,4" "79")
            elif same_line and -1 <= gap <= 0.33 * h and re.fullmatch(r"[(\-−–]?[€$£]?\d{1,3}( \d{3})*", a["t"]) \
                    and re.fullmatch(r"\d{3}([.,]\d+)?\)?%?", wd["t"]):
                joined = a["t"] + " " + wd["t"]
            if joined:
                out[-1] = {**a, "t": joined, "w": wd["x"] + wd["w"] - a["x"],
                           "y": min(a["y"], wd["y"]), "h": max(a["y"] + a["h"], wd["y"] + wd["h"]) - min(a["y"], wd["y"])}
                continue
        out.append(wd)
    return out


def _open(t: str) -> bool:
    """The first piece of a broken amount: "23,4", "94,", "(77" — not a whole number ("12" before "1,234")."""
    return bool(re.search(r"[,.]\d{0,2}$", t)) or t.count("(") > t.count(")")


AMOUNT = re.compile(r"[(\-−–]?[€$£]?(\d{1,3}(,\d{3})+|\d{1,3}(\.\d{3})+|\d+)([.,]\d+)?\)?%?")


def thousands_sep(words: list[dict]) -> Optional[str]:
    """How a document groups thousands: "," (1,234.5), "." (1.234,5) or " " (1 234,5), when most of its amounts say
    so (five to one); then "5.045" is 5.045 in the first and "5,045" is 5.045 in the others."""
    n = {",": 0, ".": 0, " ": 0}
    for w in words:
        t = w["t"].strip("()-−–$€£%")
        if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", t):
            n[","] += 1
        elif re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", t):
            n["."] += 1
        elif re.fullmatch(r"\d{1,3}( \d{3})+([.,]\d+)?", t):
            n[" "] += 1
    best = max(n, key=n.get)
    others = sum(v for k, v in n.items() if k != best)
    return best if n[best] >= 8 and n[best] >= 5 * others else None


def _lines(words: list[dict]) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for wd in sorted(words, key=lambda w: (round(w["y"] + w["h"] / 2), w["x"])):
        cy = wd["y"] + wd["h"] / 2
        for ln in lines[-4:]:
            ref = ln[0]
            if abs(ref["y"] + ref["h"] / 2 - cy) < 0.5 * min(ref["h"], wd["h"]):
                ln.append(wd)
                break
        else:
            lines.append([wd])
    for ln in lines:
        ln.sort(key=lambda w: w["x"])
    return lines


def _label_figures(words: list[dict], sep: Optional[str] = None) -> list[dict]:
    out = []
    lines = _lines(words)
    # the page's columns of amounts: where the formatted amounts end (their right edges, a ")" aside)
    def edge(w):
        return w["x"] + w["w"] - (3.5 if w["t"].endswith(")") else 0)

    groups: list[list[float]] = []
    for e in sorted(edge(w) for ln in lines for w in ln if is_figure(w["t"]) and re.search(r"\d[., ]\d", w["t"])):
        if groups and e - groups[-1][-1] <= 8:
            groups[-1].append(e)
        else:
            groups.append([e])
    columns = [sorted(g)[len(g) // 2] for g in groups if len(g) >= 3]

    def in_column(w):
        return any(abs(edge(w) - c) <= 8 for c in columns)

    for li, ln in enumerate(lines):
        # a 1-2 digit number in front of a row of formatted amounts is a note reference, not a figure;
        # between the amounts it is one ("Net income  $ (6,841)  $ 78  $ (5,865)"), and so it is in the column of
        # the amounts ("Net increase in cash  62  2,962  (3,241)", "… on cash  9  (52)  (51)")
        amount_x = [w["x"] for w in ln if is_figure(w["t"]) and re.search(r"\d[., ]\d", w["t"])]
        for k, wd in enumerate(ln):
            if not is_figure(wd["t"], allow_digit=True):
                continue
            if len(amount_x) >= 2 and re.fullmatch(r"\d{1,2}", wd["t"]) and wd["x"] < min(amount_x) and not in_column(wd):
                continue
            prev_w = ln[k - 1]["t"] if k > 0 else ""
            if re.fullmatch(r"\d{1,2},?", wd["t"]) and MONTH_END.search(prev_w):
                continue                                  # "June 30": a date, not a figure
            if re.fullmatch(r"(rule|item|items|section|note|notes|page|no\.?|§|form|exhibit|schedule|article|regulation|nota|art\.?)", prev_w, re.I):
                continue                                  # "Rule 405", "Item 7", "Note 13"
            if re.fullmatch(r"\d{1,2},", wd["t"]) or (wd["t"].endswith(")") and not wd["t"].startswith("(")):
                continue                                  # "13," in "Items 13, 14", "13)"
            next_w = ln[k + 1]["t"] if k + 1 < len(ln) else ""
            if wd["t"].startswith("(") and not wd["t"].endswith(")") and next_w[:1].isalpha():
                continue                                  # "(17 CFR 240.14d-2(b))"
            if re.fullmatch(r"\(\d\)", wd["t"]) and re.search(r"[A-Za-z]$", prev_w) and (next_w in ("$", "€", "£") or re.search(r"\d[,.]\d", next_w)):
                continue                                  # a footnote mark after the label: "Basic earnings per share (2)  $ 20.68"
            start = 0
            for j in range(k - 1, -1, -1):
                # two tables side by side: the label of this one starts after the other's figures ("Cash … 277 125
                # 157 | Total equity and liabilities 6,838 …")
                if is_figure(ln[j]["t"]) and any(re.search(r"[A-Za-z]{2,}", w["t"]) for w in ln[j + 1:k]):
                    start = j + 1
                    break
            label_words = [w["t"] for w in ln[start:k] if not is_figure(w["t"]) and not re.fullmatch(r"[\W\d]+", w["t"])][-24:]
            label = unsplit(" ".join(label_words))
            if not label and li > 0:
                label = _section_total(lines, li) or " ".join(w["t"] for w in lines[li - 1] if not is_figure(w["t"]))[:80]
            elif li > 0 and (label[:1].islower() or WRAPS.search(" ".join(w["t"] for w in lines[li - 1]))) \
                    and not any(is_figure(w["t"]) and not _in_text(lines[li - 1], j) for j, w in enumerate(lines[li - 1])):
                # a row label wrapped onto two lines: "Effect of exchange" / "rate fluctuations on cash … (6)",
                # "… BEFORE TAXES AND EQUITY IN EARNINGS OF" / "AFFILIATES 1,029", "… net of $53, $123 and $48, respectively,
                # of non-cash capital" / "expenditures (819)"
                # … or onto several, in a narrow label column ("Equity in" / "earnings of" / "affiliated" / "companies (299)")
                parts = []
                for j in range(li - 1, max(-1, li - 6), -1):
                    prev_ln = lines[j]
                    if any(is_figure(w["t"]) and not _in_text(prev_ln, k) for k, w in enumerate(prev_ln)):
                        break
                    parts.insert(0, " ".join(w["t"] for w in prev_ln))
                    if parts[0][:1].isupper() or len(" ".join(parts)) > 140:
                        break
                head = " ".join(parts)
                if parts and len(head) <= 140 and head[:1].isupper():
                    label = unsplit(head + " " + label)
            v = parse_loose(wd["t"], sep)
            if v is None:
                continue
            sc = score_label(label)
            if re.fullmatch(r"\d", wd["t"]) and sc < 3 and not (in_column(wd) and any(is_figure(w["t"]) for w in ln if w is not wd)):
                continue
            if wd["t"].endswith("%"):
                sc += 0.5
            # a number in a sentence, not a table cell: "net of $35, $46 and $32, respectively", "2022, $1; 2021, $2"
            inline = _in_text(ln, k)
            out.append({"word": wd, "label": label[:120], "value": v, "score": sc, "inline": inline})
    return out


WRAPS = re.compile(r"\b(of|and|to|for|in|on|from|before|by|with|at|the|or|net|less|including|excluding)\s*$", re.I)


def _in_text(ln: list[dict], k: int) -> bool:
    """The number at position k of a line sits in a sentence ("net of $53, $123 and $48, respectively"), not a column."""
    t = ln[k]["t"]
    nxt = ln[k + 1]["t"] if k + 1 < len(ln) else ""
    prv = ln[k - 1]["t"] if k > 0 else ""
    return bool(re.search(r"[,;]$", t) or nxt[:1].islower() or re.fullmatch(r"(19|20)\d\d[,:;]?", prv))


def _section_total(lines: list[list[dict]], li: int) -> str:
    """A line of amounts without a label right under a row of a statement is the total of the section it closes:
    "Total current assets" under "Current assets:", "Total assets" under "ASSETS" when the sections in between have
    their own totals ("Total other assets" … "$ 45,692,206"). Not when the section's total is printed further down
    (an unlabeled subtotal before "Less: treasury stock"), nor a page number."""
    def figs(ln):
        # amounts in columns: not footnote marks, not numbers inside a wrapped label ("included $7,709 and $8,265 at …")
        return [w for k, w in enumerate(ln) if is_figure(w["t"]) and not re.fullmatch(r"\(\d\)", w["t"]) and not _in_text(ln, k)]

    def text(ln):
        return re.sub(r"\s+", " ", " ".join(w["t"] for w in ln if not is_figure(w["t"]))).strip(" :")

    if len(figs(lines[li])) < 2 or not figs(lines[li - 1]) or not text(lines[li - 1]):
        return ""                                       # under a label line: a row wrapped onto two lines
    closed, less = set(), False
    for j in range(li - 1, max(0, li - 60) - 1, -1):
        ln = lines[j]
        t, has_fig = text(ln), bool(figs(ln))
        m = re.match(r"total (.+)", t, re.I)
        if has_fig and m:
            closed.add(m.group(1).lower())
            continue
        if has_fig and not t:
            above = _section_total(lines, j)            # another unlabeled total: the section it closes is closed
            if above.startswith("Gross ") and less:
                return "Net " + above[6:]               # "… / Less: Promotional allowances / 9,455,123": net revenues
            if above:
                closed.add(above.split(" ", 1)[1].lower())
            continue
        if has_fig and re.match(r"less\b", t, re.I):
            less = True
        if has_fig or not t:
            continue
        if len(t) > 60 or t.endswith(".") or not t[:1].isupper() or re.search(r"\d", t):
            continue                                    # a sentence or a note, not a section heading
        if t.lower() in closed:
            continue                                    # a section with its own total line
        if any(text(nx).lower() == "total " + t.lower() for nx in lines[li + 1:li + 30]):
            return ""                                   # the section's total comes later: this is a subtotal
        name = t.lower() if t.isupper() else t[:1].lower() + t[1:]
        if li + 1 < len(lines) and re.match(r"less\b", text(lines[li + 1]), re.I):
            return "Gross " + name                      # amounts deducted from it follow
        return "Total " + name
    return ""


def _heading_lines(words: list[dict], hsize: float) -> dict[int, str]:
    out = {}
    for ln in _lines(words):
        t = " ".join(w["t"] for w in ln)
        if ln[0]["h"] >= hsize * 1.35 and 4 <= len(t) <= 90 and sum(c.isalpha() for c in t) >= 0.6 * len(t):
            out[id(ln[0])] = t
        if len(out) >= 6:
            break
    return out


PDF_CSS = """
.pdfpage{position:relative;background:#fff;margin:0 auto}
.pdfpage img{position:absolute;left:0;top:0;width:100%;height:100%;user-select:none;pointer-events:none}
.pdfpage .w{position:absolute;color:transparent;white-space:pre;line-height:1;font-family:sans-serif;overflow:hidden}
"""


# ---------------------------------------------------------------- HTML (no XBRL tags)

def html_document(data: bytes, base_url: Optional[str]) -> dict:
    """Plain HTML: pages, the figures on the pages shown, and the statement tables read with their periods.
    The pages holding the headline figures are always among the pages shown."""
    from . import tables
    from .i18n import lang, t
    doc = ixbrl.parse(data, base_url)          # sanitises and splits pages; no facts in plain HTML
    frags = [lxml_html.fragment_fromstring(page or "<div></div>", create_parent="div") for page in doc.pages]
    tbls = [tb for pi, fr in enumerate(frags, start=1) for tb in tables.page_tables(fr, pi)]
    fin = tables.extract(tbls, lang())

    key_pages: list[int] = []
    for k in ("revenue", "net_income", "cfo", "total_assets", "eps_diluted", "cash", "operating_income"):
        mm = fin["metrics"].get(k)
        if mm and mm["cur"]["page"] - 1 not in key_pages:
            key_pages.append(mm["cur"]["page"] - 1)
    picked = best_pages(doc.page_text)
    shown = list(dict.fromkeys(key_pages[:4] + sorted(picked)))[:MAX_PAGES_SHOWN + 2]
    chosen = sorted({p + 1 for p in shown if 0 <= p < len(frags)})

    cell_of = {}                               # td -> (table, column) of the tables on the pages shown
    for tb in tbls:
        if tb.page in chosen:
            for r in tb.rows:
                for c, cl in r.cells.items():
                    cell_of[id(cl.el)] = (tb, tb.columns.get(c), r.label)
    facts, pages_out = [], []
    for pi in chosen:
        frag = frags[pi - 1]
        figs = _wrap_numbers(frag)
        figs.sort(key=lambda f: -f["score"])
        keep = figs[:MAX_FACTS_PAGE]
        keep_el = {id(f["el"]) for f in keep}
        for f in figs:
            el = f["el"]
            if id(el) not in keep_el:
                _unwrap(el)
                continue
            fid = len(facts)
            el.set("data-f", str(fid))
            td = next((a for a in el.iterancestors() if isinstance(a.tag, str) and a.tag.lower() in ("td", "th")), None)
            tb, col, row_label = cell_of.get(id(td), (None, None, ""))
            pct = bool(tb and (tb.percent or f["text"].endswith("%")))
            period = tables.period_label(col.months if not col.instant else None, col.end, lang()) if col and col.end and not col.skip else ""
            label = row_label or f["label"] or t("Cifra", "Figure")
            facts.append({"id": fid, "label": label + (t(" (% dei ricavi)", " (% of revenue)") if tb and tb.percent else ""),
                          "value": f["value"], "display": f["text"], "page": pi, "period": period, "pct": pct,
                          "kind": "num", "col": "Valore", "key": f["score"] >= 2 and not (tb and tb.percent), "score": f["score"]})
        inner = "".join(etree.tostring(c, method="html", encoding="unicode", with_tail=True) for c in frag)
        pages_out.append({"n": pi, "html": (frag.text and html.escape(frag.text) or "") + inner})

    # the statement figures become facts the sniffer reads: link each table cell to its figure
    for mm in fin["metrics"].values():
        for which in ("cur", "prev"):
            o = mm.get(which)
            if not o:
                continue
            el = o.pop("el", None)
            span = next((x for x in el.iter() if isinstance(x.tag, str) and x.get("data-f") is not None), None) if el is not None else None
            o.update(id=int(span.get("data-f")) if span is not None and o["page"] in chosen else None, concept="", unit="")
    used = set(re.findall(r'class="([^"]+)"', "".join(p["html"] for p in pages_out)))
    used = {c for cl in used for c in cl.split()}
    headings = [h for h in doc.headings if h["page"] in chosen]
    return {"pages": pages_out, "facts": facts, "headings": headings,
            "page_text": [doc.page_text[p["n"] - 1] for p in pages_out], "all_text": doc.page_text, "total_pages": len(doc.pages),
            "title": "", "css": ixbrl.filter_css(doc.css, used), "info": doc.info, "fin": fin,
            "page_labels": {i + 1: lb for i, lb in enumerate(doc.page_labels) if lb}}


def _unwrap(el):
    parent = el.getparent()
    text = (el.text or "") + (el.tail or "")
    prev = el.getprevious()
    if prev is not None:
        prev.tail = (prev.tail or "") + text
    else:
        parent.text = (parent.text or "") + text
    parent.remove(el)


def _before(s: str, a: int, el, where: str) -> str:
    """Up to 30 characters printed just before a number (text nodes split by layout included)."""
    ctx = s[:a]
    if not ctx.strip():
        if where == "tail":
            ctx = "".join(el.itertext())
        else:
            prev = el.getprevious()
            ctx = "".join(prev.itertext()) + (prev.tail or "") if prev is not None else (el.getparent().text or "" if el.getparent() is not None else "")
    return ctx[-30:]


def _noise(s: str, a: int, b: int, tok: str, el, where: str) -> bool:
    """Numbers that are not figures: days of a date, footnote marks, par values."""
    before = _before(s, a, el, where)
    if re.fullmatch(r"\d{1,2},?", tok) and MONTH_END.search(before):
        return True                                       # "June 30"
    if re.fullmatch(r"\(\d{1,2}\)", tok):
        if before[-1:].isalnum() or before[-1:] in (")", "’", "'", "%"):
            return True                                   # "Net loss(2)"
        cell = next((x for x in [el] + list(el.iterancestors()) if isinstance(x.tag, str) and x.tag.lower() in ("td", "th")), None)
        if cell is None or re.sub(r"[\s$€£\xa0]", "", "".join(cell.itertext())) != tok:
            return True                                   # "(1)" in running text is a note, in a cell alone it is −1
    if re.search(r"par value( of)?\s*$", before, re.I) or re.match(r"\s*par value", s[b:b + 14], re.I):
        return True
    if tok.endswith(")") and not tok.startswith("(") or re.search(r"\b(note|nota|item|section|rule|page)\s*$", before, re.I):
        return True                                       # "(Note 13)", "Item 7"
    if re.fullmatch(r"\(\d{3}\)", tok) and re.match(r"\s?\d{3}[-.\s]\d{4}", s[b:b + 10]):
        return True                                       # phone number "(650) 555-0100"
    in_cell = any(isinstance(x.tag, str) and x.tag.lower() in ("td", "th") for x in [el] + list(el.iterancestors()))
    if not in_cell and re.fullmatch(r"\d{5,}", tok):
        return True                                       # ZIP codes, registration numbers: figures carry separators
    return False


def _wrap_numbers(root) -> list[dict]:
    """Wrap every figure in a text node with <span class="xf">; return them with a label."""
    figs = []
    targets = []
    for el in root.iter():
        if not isinstance(el.tag, str) or el.tag in ("style", "script", "svg"):
            continue
        if el.text and re.search(r"\d", el.text):
            targets.append((el, "text"))
        if el.tail and re.search(r"\d", el.tail) and el is not root:
            targets.append((el, "tail"))
    for el, where in targets:
        s = el.text if where == "text" else el.tail
        pieces, last = [], 0
        for m in INLINE_NUM.finditer(s):
            tok = m.group().strip()
            if not is_figure(tok) or _noise(s, m.start(), m.end(), tok, el, where):
                continue
            pieces.append((m.start(), m.end(), tok))
        if not pieces:
            continue
        spans = []
        before = s[:pieces[0][0]]
        for k, (a, b, tok) in enumerate(pieces):
            sp = etree.Element("span")
            sp.set("class", "xf")
            sp.text = s[a:b]
            nxt = pieces[k + 1][0] if k + 1 < len(pieces) else len(s)
            sp.tail = s[b:nxt]
            spans.append((sp, s[:a], tok))
        if where == "text":
            el.text = before
            for idx, (sp, _, _) in enumerate(spans):
                el.insert(idx, sp)
        else:
            parent = el.getparent()
            el.tail = before
            pos = parent.index(el)
            for idx, (sp, _, _) in enumerate(spans):
                parent.insert(pos + 1 + idx, sp)
        for sp, pre, tok in spans:
            label = ixbrl._row_label(sp)
            if not label:
                words = re.findall(r"[^\W\d_][\w'’%-]*", pre)[-9:]
                label = " ".join(words)
            v = parse_loose(tok)
            if v is None:
                _unwrap(sp)
                continue
            sc = score_label(label) + (0.5 if tok.endswith("%") else 0)
            figs.append({"el": sp, "label": label[:90], "value": v, "text": tok, "score": sc})
    return figs
