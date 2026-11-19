"""Accuracy benchmark: how many of the figures Report Sniffer reads from untagged PDFs are right.

The documents are the 10-K PDFs of FinanceBench (github.com/patronus-ai/financebench: 269 annual reports of 32 US
companies, 2015-2023), read by rules, with no AI. Each figure the app reads from the statements (revenue, net
income, total assets, cash flows, EPS, … for the current and the prior year) is compared with the value the company
filed in XBRL with the SEC for the same period, in the same 10-K (data.sec.gov companyfacts).

    ok          equal to a filed value, within the rounding of the page ("12,345" in millions)
    wrong       different from every value filed for that line and period
    unverified  the 10-K itself is not in the SEC data: only later (possibly restated) filings report the period
    explained   a line the document prints differently from the filed total (listed in EXPLAINED, checked by hand)
    missed      filed, but not read from the document
    precision = ok / (ok + wrong)        recall = ok / (ok + wrong + missed)

usage:  .venv/bin/python bench/accuracy.py [latest | YEAR ... | DOC_NAME ...]
        (default: the latest 10-K of each company; e.g. 2019 2020, or APPLE_2022_10K). JOBS=4 processes.
Needs the network (raw.githubusercontent.com, data.sec.gov); files are cached in bench/.cache. SEC asks for a
User-Agent naming you: set SNIFFER_SEC_UA="Your Name you@example.com" (as for the app).
"""
import json
import math
import os
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CACHE = HERE / ".cache"
FB = "https://raw.githubusercontent.com/patronus-ai/financebench/main/"
RAW = FB + "pdfs/{}.pdf"
sys.path.insert(0, str(REPO))


def _ua() -> dict:
    from analyst import sources
    return {"User-Agent": sources.sec_user_agent()}

CIK = {"3M": 66740, "AES Corporation": 874761, "AMD": 2488, "Activision Blizzard": 718877, "Adobe": 796343,
       "Amazon": 1018724, "Amcor": 1748790, "American Express": 4962, "American Water Works": 1410636, "Apple": 320193,
       "Best Buy": 764478, "Block": 1512673, "Boeing": 12927, "CVS Health": 64803, "Coca-Cola": 21344, "Corning": 24741,
       "Costco": 909832, "FedEx": 1048911, "Foot Locker": 850209, "General Mills": 40704, "Intel": 50863,
       "JPMorgan": 19617, "Johnson & Johnson": 200406, "Kraft Heinz": 1637459, "Lockheed Martin": 936468,
       "MGM Resorts": 789570, "McDonalds": 63908, "Microsoft": 789019, "Netflix": 1065280, "Nike": 320187,
       "Oracle": 1341439, "PG&E Corporation": 1004980, "Paypal": 1633917, "PepsiCo": 77476, "Pfizer": 78003,
       "Salesforce": 1108524, "Ulta Beauty": 1403568, "Verizon": 732712, "Walmart": 104169, "eBay": 1065088}

# metric -> concepts accepted as the same line (the app's own lists plus common alternatives)
EXTRA = {
    "revenue": ["SalesRevenueGoodsNet", "SalesRevenueServicesNet", "RevenuesNetOfInterestExpense", "RegulatedAndUnregulatedOperatingRevenue",
                "ElectricUtilityRevenue", "RevenueFromContractWithCustomerIncludingAssessedTax", "Revenues", "OperatingLeasesIncomeStatementLeaseRevenue",
                "RevenueMineralSales", "SalesRevenueNet", "RevenuesExcludingInterestAndDividends", "InterestAndDividendIncomeOperating"],
    "cost_of_revenue": ["CostOfGoodsSold", "CostOfServices", "CostOfGoodsAndServicesSoldExcludingDepreciationDepletionAndAmortization",
                        "CostOfGoodsSoldExcludingDepreciationDepletionAndAmortization", "CostOfRevenue", "CostOfGoodsAndServicesSold"],
    "operating_income": ["OperatingIncomeLoss"],
    "pretax_income": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic", "IncomeLossBeforeIncomeTaxes"],
    "net_income": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "NetIncomeLossAttributableToParent",
                   "IncomeLossFromContinuingOperations"],
    "eps_diluted": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "IncomeLossFromContinuingOperationsPerDilutedShare"],
    "income_tax": ["IncomeTaxExpenseBenefit", "IncomeTaxExpenseBenefitContinuingOperations"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashAndDueFromBanks", "Cash", "CashCashEquivalentsAndShortTermInvestments",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "CashAndCashEquivalentsAtCarryingValueIncludingDiscontinuedOperations"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "liab_and_equity": ["LiabilitiesAndStockholdersEquity"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets", "PaymentsForCapitalImprovements",
              "PaymentsToAcquireOtherPropertyPlantAndEquipment", "PaymentsToAcquireAndDevelopRealEstate"],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock", "PaymentsForRepurchaseOfEquity"],
    "dividends": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock", "PaymentsOfOrdinaryDividends"],
    "sbc": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    "opex_total": ["OperatingExpenses", "CostsAndExpenses", "BenefitsLossesAndExpenses", "OperatingCostsAndExpenses", "NoninterestExpense"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt", "InterestAndDebtExpense", "InterestExpenseNet"],
    "cash_change": ["CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
                    "CashAndCashEquivalentsPeriodIncreaseDecrease",
                    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseExcludingExchangeRateEffect"],
    "diluted_shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "fx_effect": ["EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "EffectOfExchangeRateOnCashAndCashEquivalents"],
}
ABS = {"capex", "buybacks", "dividends", "cost_of_revenue", "rnd", "interest_expense"}
CORE = ["revenue", "operating_income", "pretax_income", "income_tax", "net_income", "eps_diluted", "cash", "current_assets", "total_assets",
        "current_liabilities", "total_liabilities", "equity", "cfo", "cfi", "cff", "capex"]


def get(url, path: Path, timeout=120):
    if path.exists() and path.stat().st_size:
        return path.read_bytes()
    CACHE.mkdir(exist_ok=True)
    for i in range(4):
        try:
            r = httpx.get(url, headers=_ua(), timeout=timeout, follow_redirects=True)
            r.raise_for_status()
            path.write_bytes(r.content)
            return r.content
        except httpx.HTTPError:
            time.sleep(2 * (i + 1))
    raise RuntimeError("download failed: " + url)


def concepts(F, key):
    return list(dict.fromkeys(list(F.METRICS.get(key, ("", "", "", ()))[3]) + EXTRA.get(key, [])))


def _d(s):
    return date.fromisoformat(s)


def _end_of(mine):
    durs = [r["end"] for c, u, r in mine if r.get("start") and 340 <= (_d(r["end"]) - _d(r["start"])).days <= 380]
    return max(durs) if durs else None


def truth(cik: int, fy: int, F, cover_end=None) -> dict:
    """{metric: {"cur": {concept: [values]}, "prev": ...}} from the 10-K for the fiscal year ended cover_end (else fy)."""
    cf = json.loads(get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", CACHE / f"cf{cik}.json"))
    gaap = cf["facts"].get("us-gaap", {})
    rows = [(c, u, r) for c, d in gaap.items() for u, rs in d["units"].items() for r in rs]
    byacc = defaultdict(list)
    for c, u, r in rows:
        if r.get("form") in ("10-K", "10-KT", "10-K/A"):
            byacc[r["accn"]].append((c, u, r))
    accn = None
    if cover_end:
        cands = [(a, len(v), v[0][2]["form"]) for a, v in byacc.items() if _end_of(v) and abs((_d(_end_of(v)) - cover_end).days) <= 10]
        if cands:
            accn = max(cands, key=lambda x: (x[2] == "10-K", x[1]))[0]
        else:
            # this 10-K is not in the data: the same periods as later 10-Ks report them (all as alternates)
            ce = cover_end
            out = {"_accn": None, "_end": str(cover_end)}
            allf = [x for v in byacc.values() for x in v]
            for key, spec in F.METRICS.items():
                alt = _vals(F, key, spec[2], allf, ce)
                if any(alt.values()):
                    out[key] = {"cur": {}, "prev": {}, "alt": alt}
            return out
    if not accn:
        tenk = Counter(r["accn"] for c, u, r in rows if r.get("form") in ("10-K", "10-KT") and r.get("fy") == fy)
        if not tenk:
            return {}
        accn = tenk.most_common(1)[0][0]
    mine = byacc[accn]
    cur_end = _end_of(mine)
    if not cur_end:
        return {}
    ce = _d(cur_end)
    out = {"_accn": accn, "_end": cur_end}
    others = [x for a, v in byacc.items() if a != accn for x in v]
    for key, spec in F.METRICS.items():
        own = _vals(F, key, spec[2], mine, ce)
        alt = _vals(F, key, spec[2], others, ce)
        if any(own.values()) or any(alt.values()):
            out[key] = {w: own[w] for w in ("cur", "prev")}
            out[key]["alt"] = {w: alt[w] for w in ("cur", "prev")}
    return out


def _vals(F, key, kind, mine, ce):
        cs = [c for c in concepts(F, key) if c != "InterestPaidNet"]       # interest paid in cash is not the expense
        if key == "pretax_income":
            cs = [c for c in cs if c != "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic"]
        vals = {"cur": defaultdict(list), "prev": defaultdict(list)}
        parts = {"cur": defaultdict(dict), "prev": defaultdict(dict)}
        for c, u, r in mine:
            if key == "pretax_income" and c.startswith("IncomeLossFromContinuingOperationsBeforeIncomeTaxes") and c.endswith(("Domestic", "Foreign")) \
                    and r.get("start") and 340 <= (_d(r["end"]) - _d(r["start"])).days <= 380:
                e = _d(r["end"])
                w = "cur" if abs((e - ce).days) <= 7 else "prev" if 350 <= (ce - e).days <= 380 else None
                if w:
                    parts[w][r["accn"]][c[-7:]] = r["val"]
        for w in ("cur", "prev"):
            for acc, pr in parts[w].items():
                if len(pr) == 2:
                    vals[w]["Domestic+Foreign"].append(sum(pr.values()))
        for c, u, r in mine:
            if c not in cs:
                continue
            e = _d(r["end"])
            if kind == "stock":
                if r.get("start"):
                    continue
            else:
                if not r.get("start") or not 340 <= (e - _d(r["start"])).days <= 380:
                    continue
            if abs((e - ce).days) <= 7:
                vals["cur"][c].append(r["val"])
            elif 350 <= (ce - e).days <= 380:
                vals["prev"][c].append(r["val"])
        return {w: {c: sorted(set(v)) for c, v in vals[w].items()} for w in ("cur", "prev")}


def read(doc: str):
    from analyst import generic, pipeline
    data = get(RAW.format(doc), CACHE / f"{doc}.pdf")
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        g = generic.pdf_document(data, Path(tmp), "/x")
    fin = g.get("fin") or {}
    if fin and pipeline._enough(fin["metrics"]):
        x = {"metrics": fin["metrics"], "periods": fin.get("periods")}
    else:
        x = pipeline._statement_metrics(g) or {"metrics": {}}
    m = {k: {w: ({"value": v[w]["value"], "display": v[w]["display"], "page": v[w]["page"]} if v.get(w) else None)
             for w in ("cur", "prev")} for k, v in x["metrics"].items()}
    cover = None
    mm = re.search(r"fiscal\s+year\s+ended:?\s+([A-Z][a-z]+)\.?\s+(\d{1,2})\s*,\s*((?:19|20)\d\d)", " ".join(g["all_text"][:3]), re.I)
    if mm:
        from datetime import datetime
        try:
            cover = datetime.strptime(f"{mm.group(1)[:3]} {mm.group(2)} {mm.group(3)}", "%b %d %Y").date()
        except ValueError:
            cover = None
    return {"metrics": m, "pages": [p["n"] for p in g["pages"]], "periods": x.get("periods"), "secs": round(time.time() - t0, 1),
            "total_pages": g["total_pages"], "cover": cover}


def close(a: float, g: float, display: str, key: str) -> bool:
    if key == "eps_diluted":
        return abs(a - g) <= 0.0051
    num = re.sub(r"[^\d.]", "", display or "")
    try:
        shown = float(num) if num else 0
    except ValueError:
        shown = 0
    scale = abs(a) / shown if shown else 1
    unit = 10 ** round(math.log10(scale)) if scale > 0 else 1
    return abs(a - g) <= max(0.51 * unit, 0.0005 * abs(g), 0.5)


# a document line that differs from the tagged total, by the document's own layout (checked by hand)
EXPLAINED = {("AMD_2022_10K", "cost_of_revenue", "cur"): "the statement prints amortisation of acquired intangibles (1,448) on its own line; "
                                                          "the tagged CostOfGoodsAndServicesSold includes it"}


def judge(key, o, cands, alt=None) -> str:
    if not o:
        return "none"
    allv = [v for vs in cands.values() for v in vs]
    altv = [v for vs in (alt or {}).values() for v in vs]
    if not allv and not altv:
        return "nogt"
    only_alt = not allv
    allv += altv
    a = o["value"]
    for v in allv:
        if close(abs(a) if key in ABS else a, abs(v) if key in ABS else v, o["display"], key):
            return "ok"
    return "unverified" if only_alt else "wrong"           # only later (possibly restated) filings report it


def run_doc(args):
    doc, company, fy = args
    from analyst import financials as F
    try:
        r = read(doc)
        gt = truth(CIK[company], fy, F, r["cover"])
    except Exception as e:  # noqa: BLE001
        return {"doc": doc, "error": f"{type(e).__name__}: {e}"}
    res = []
    for key in sorted(set(r["metrics"]) | {k for k in gt if not k.startswith("_")}):
        for w in ("cur", "prev"):
            o = (r["metrics"].get(key) or {}).get(w)
            cands = (gt.get(key) or {}).get(w, {})
            alt = ((gt.get(key) or {}).get("alt") or {}).get(w, {})
            st = judge(key, o, cands, alt)
            if st == "wrong" and (doc, key, w) in EXPLAINED:
                st = "explained"
            if st == "none" and not cands and alt:
                continue                                   # only a later filing has it: not counted as missed
            if st == "none" and not cands:
                continue
            if st == "none":
                st = "missed"
            res.append({"key": key, "w": w, "status": st, "app": o, "gt": cands, "alt": alt})
    return {"doc": doc, "company": company, "fy": fy, "pages": r["pages"], "total_pages": r["total_pages"], "secs": r["secs"],
            "periods": r["periods"], "cover": str(r["cover"]), "gt_end": gt.get("_end"), "accn": gt.get("_accn"), "res": res}


def main():
    meta_file = CACHE / "financebench_document_information.jsonl"
    docs = [json.loads(line) for line in get(FB + "data/financebench_document_information.jsonl", meta_file).decode().splitlines() if line]
    sel = sys.argv[1:]
    if not sel or sel == ["latest"]:
        last = {}
        for d in docs:
            if d["doc_type"] == "10k":
                last[d["company"]] = max(last.get(d["company"], ""), d["doc_name"], key=lambda n: (re.search(r"_(\d{4})_", n) or [0, "0"])[1])
        sel = sorted(last.values())
    elif sel[0].isdigit():
        sel = sorted(d["doc_name"] for d in docs if d["doc_type"] == "10k" and str(d["doc_period"]) in sel)
    meta = {d["doc_name"]: d for d in docs}
    jobs = [(n, meta[n]["company"], meta[n]["doc_period"]) for n in sel]
    with ProcessPoolExecutor(int(os.environ.get("JOBS", "4"))) as ex:
        out = list(ex.map(run_doc, jobs))
    tag = os.environ.get("TAG", "run")
    (CACHE / f"result-{tag}.json").write_text(json.dumps(out, indent=1, default=str))
    report(out)


def report(out):
    tot = Counter()
    for d in out:
        if "error" in d:
            print("ERROR", d["doc"], d["error"])
            continue
        c = Counter(x["status"] for x in d["res"])
        core = Counter(x["status"] for x in d["res"] if x["key"] in CORE)
        tot.update(c)
        bad = [f"{x['key']}.{x['w']}" for x in d["res"] if x["status"] == "wrong"]
        miss = [f"{x['key']}.{x['w']}" for x in d["res"] if x["status"] == "missed" and x["key"] in CORE]
        print(f"{d['doc']:<32} ok {c['ok']:>3} wrong {c['wrong']:>2} expl {c['explained']} unver {c['unverified']} nogt {c['nogt']:>2} missed-core {core['missed']:>2}  "
              f"{' '.join(bad)} | miss: {' '.join(miss)}")
    n = tot["ok"] + tot["wrong"]
    core_tot = Counter(x["status"] for d in out if "res" in d for x in d["res"] if x["key"] in CORE)
    print(f"CORE ok {core_tot['ok']} wrong {core_tot['wrong']} missed {core_tot['missed']} -> core recall "
          f"{core_tot['ok'] / max(1, core_tot['ok'] + core_tot['wrong'] + core_tot['missed']):.4f}")
    print(f"\nTOTAL ok {tot['ok']} wrong {tot['wrong']} explained {tot['explained']} unverified {tot['unverified']} -> precision {tot['ok'] / max(1, n):.4f}; nogt {tot['nogt']}; "
          f"missed {tot['missed']} -> recall {tot['ok'] / max(1, tot['ok'] + tot['wrong'] + tot['missed']):.4f}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--report"]:
        report(json.loads(Path(sys.argv[2]).read_text()))
    else:
        main()
