"""How well untagged European annual reports are read: ESEF reports (filings.xbrl.org) printed to PDF without their
XBRL tags are read by rules like any uploaded PDF, and every statement figure read is compared with the value the
same report tags (its xBRL-JSON). English-language reports only: the statement lines are recognised by rule in
English and Italian.

    .venv/bin/python bench/esef.py [N per country] [YYYY-MM-DD period end]     (default: 4, 2023-12-31)

Needs Node with Playwright and Chromium (bench/print_pdf.js prints the reports). Cache in bench/.cache/esef/.
"""
import json
import os
import re
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import accuracy as A  # noqa: E402

API = "https://filings.xbrl.org"
DIR = A.CACHE / "esef"
COUNTRIES = ["IT", "DE", "FR", "ES", "NL", "BE", "AT", "PT", "IE", "LU", "FI", "SE", "DK", "NO", "PL", "GR"]
MAX_MB = 40                     # larger reports (image-heavy) take minutes to print


def _get(url: str, path: Path) -> bytes:
    if path.exists() and path.stat().st_size:
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    r = httpx.get(url, timeout=300, follow_redirects=True)
    r.raise_for_status()
    path.write_bytes(r.content)
    return r.content


def select(per: int, end: str) -> list[dict]:
    out = []
    for c in COUNTRIES:
        q = json.dumps([{"name": "period_end", "op": "eq", "val": end}, {"name": "country", "op": "eq", "val": c}])
        data = json.loads(_get(f"{API}/api/filings?filter={q}&page[size]=200", DIR / f"list-{c}-{end}.json"))["data"]
        seen = set()
        for f in data:
            a = f["attributes"]
            lei = a["report_url"].split("/")[1] if a.get("report_url") else ""
            if not a.get("json_url") or not re.search(r"-en\.x?html?$", a["report_url"] or "") or lei in seen:
                continue
            seen.add(lei)
            out.append({"doc": f"ESEF_{c}_{lei}_{end}", "report": API + a["report_url"], "json": API + a["json_url"], "end": end})
            if len(seen) >= per:
                break
    return out


def to_pdf(f: dict) -> Path:
    pdf = A.CACHE / f"{f['doc']}.pdf"
    if pdf.exists():
        return pdf
    src = DIR / (f["doc"] + Path(f["report"]).suffix)
    if not src.exists():
        size = int(httpx.head(f["report"], timeout=60, follow_redirects=True).headers.get("content-length") or 0)
        if size > MAX_MB * 2 ** 20:
            raise RuntimeError(f"report of {size >> 20} MB")
    _get(f["report"], src)
    import subprocess
    subprocess.run(["node", str(Path(__file__).with_name("print_pdf.js")), str(src.resolve()), str(pdf)], check=True, timeout=1800,
                   capture_output=True)
    return pdf


def _day(s: str) -> date:
    """An OIM date: "2024-01-01T00:00:00" is the end of December 31, 2023."""
    d = date.fromisoformat(s[:10])
    return d - timedelta(days=1) if s[10:].startswith("T00:00:00") else d


def truth(f: dict) -> dict:
    from analyst import financials as F
    facts = json.loads(_get(f["json"], DIR / (f["doc"] + ".json")))["facts"].values()
    end = date.fromisoformat(f["end"])
    by = defaultdict(list)
    for x in facts:
        dims = x.get("dimensions", {})
        if set(dims) - {"concept", "entity", "period", "unit", "language"} or x.get("value") in (None, ""):
            continue                                       # a breakdown (segment, component of equity): not the total
        try:
            v = float(x["value"])
        except ValueError:
            continue
        by[dims["concept"].split(":")[-1]].append((dims.get("period", ""), v))
    gt = {"_end": f["end"]}
    for key, spec in F.METRICS.items():
        vals = {"cur": defaultdict(list), "prev": defaultdict(list)}
        for c in A.concepts(F, key):
            for per, v in by.get(c, []):
                if "/" in per:
                    if spec[2] == "stock":
                        continue
                    s, e = (_day(p) for p in per.split("/"))
                    s += timedelta(days=1)
                    if not 340 <= (e - s).days <= 380:
                        continue
                elif spec[2] != "stock":
                    continue
                else:
                    e = _day(per)
                w = "cur" if abs((e - end).days) <= 7 else "prev" if 350 <= (end - e).days <= 380 else None
                if w:
                    vals[w][c].append(v)
        if any(vals.values()):
            gt[key] = {w: {c: sorted(set(v)) for c, v in vals[w].items()} for w in ("cur", "prev")}
            gt[key]["alt"] = {"cur": {}, "prev": {}}
    return gt


def run(f: dict) -> dict:
    try:
        to_pdf(f)
        r = A.read(f["doc"])
        gt = truth(f)
    except Exception as e:  # noqa: BLE001
        return {"doc": f["doc"], "error": f"{type(e).__name__}: {e}"}
    res = []
    for key in sorted(set(r["metrics"]) | {k for k in gt if not k.startswith("_")}):
        for w in ("cur", "prev"):
            o = (r["metrics"].get(key) or {}).get(w)
            cands = (gt.get(key) or {}).get(w, {})
            st = A.judge(key, o, cands)
            if st == "none":
                if not cands:
                    continue
                st = "missed" if key in r["printed"] else "absent"
            res.append({"key": key, "w": w, "status": st, "app": o, "gt": cands})
    return {"doc": f["doc"], "pages": r["pages"], "total_pages": r["total_pages"], "secs": r["secs"], "periods": r["periods"],
            "report": f["report"], "res": res}


def main():
    per = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    end = sys.argv[2] if len(sys.argv) > 2 else "2023-12-31"
    sel = select(per, end)
    print(len(sel), "reports")
    with ProcessPoolExecutor(int(os.environ.get("JOBS", "4"))) as ex:
        out = list(ex.map(run, sel))
    (A.CACHE / f"result-esef-{os.environ.get('TAG', 'run')}.json").write_text(json.dumps(out, indent=1, default=str))
    A.report(out)


if __name__ == "__main__":
    main()
