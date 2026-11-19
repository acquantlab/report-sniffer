"""Tagged facts -> headline figures, ratios, arithmetic checks and findings.

Deterministic: every number comes from a tagged fact (or arithmetic on tagged facts)
and carries the page it was read on.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Optional

from .i18n import lang, num, pct_sign, t
from .ixbrl import Fact, IxDoc

# key -> (it, en, kind, candidate concepts by local name, tried in order)
# kind: "flow" (duration) | "stock" (instant) | "ps" (per share, duration)
METRICS: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    # the total among these (see extract): a bank's revenue net of interest expense is more than its fees from contracts
    "revenue": ("Ricavi", "Revenue", "flow", (
        "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet", "Revenue", "RevenueFromContractsWithCustomers", "RevenuesNetOfInterestExpense", "InsuranceRevenue",
        "RegulatedAndUnregulatedOperatingRevenue")),
    "cost_of_revenue": ("Costo del venduto", "Cost of revenue", "flow", ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfSales")),
    "gross_profit": ("Margine lordo", "Gross profit", "flow", ("GrossProfit",)),
    "rnd": ("Ricerca e sviluppo", "R&D", "flow", ("ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost")),
    "operating_income": ("Utile operativo", "Operating income", "flow", ("OperatingIncomeLoss", "ProfitLossFromOperatingActivities")),
    # not "…BeforeIncomeTaxesDomestic": the domestic part only (McDonald's: 1,845.6 of 7,825.4); a total tagged with a
    # company's own concept is found by its row label instead
    "pretax_income": ("Utile ante imposte", "Pre-tax income", "flow", (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "ProfitLossBeforeTax")),
    "income_tax": ("Imposte", "Income taxes", "flow", ("IncomeTaxExpenseBenefit", "IncomeTaxExpenseContinuingOperations")),
    "net_income": ("Utile netto", "Net income", "flow", (
        "NetIncomeLoss", "ProfitLossAttributableToOwnersOfParent", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss")),
    "profit_total": ("Utile netto (incl. terzi)", "Profit incl. NCI", "flow", ("ProfitLoss",)),
    "eps_diluted": ("EPS diluito", "Diluted EPS", "ps", (
        "EarningsPerShareDiluted", "DilutedEarningsLossPerShare", "EarningsPerShareBasicAndDiluted",
        "DilutedEarningsLossPerShareFromContinuingOperations", "BasicAndDilutedEarningsLossPerShare")),
    "diluted_shares": ("Azioni diluite (media)", "Diluted shares", "shares", (
        "WeightedAverageNumberOfDilutedSharesOutstanding", "AdjustedWeightedAverageShares", "WeightedAverageNumberOfShareOutstandingBasicAndDiluted")),
    # not "InterestPaidNet": interest paid in cash is not the expense of the year
    "interest_expense": ("Interessi passivi", "Interest expense", "flow", (
        "InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt", "InterestExpenseBorrowings", "FinanceCosts")),
    "cash": ("Cassa e equivalenti", "Cash & equivalents", "stock", (
        "CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalents",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "Cash")),
    "current_assets": ("Attivo corrente", "Current assets", "stock", ("AssetsCurrent", "CurrentAssets")),
    "total_assets": ("Totale attivo", "Total assets", "stock", ("Assets",)),
    "current_liabilities": ("Passivo corrente", "Current liabilities", "stock", ("LiabilitiesCurrent", "CurrentLiabilities")),
    "total_liabilities": ("Totale passivo", "Total liabilities", "stock", ("Liabilities",)),
    "equity": ("Patrimonio netto", "Equity", "stock", (
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "Equity", "StockholdersEquity", "EquityAttributableToOwnersOfParent")),
    "liab_and_equity": ("Passivo e patrimonio netto", "Liabilities & equity", "stock", ("LiabilitiesAndStockholdersEquity", "EquityAndLiabilities")),
    "debt_total": ("Debito finanziario", "Debt", "stock", ("LongTermDebt", "DebtLongtermAndShorttermCombinedAmount", "Borrowings", "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities")),
    "debt_noncurrent": ("Debito a lungo termine", "Long-term debt", "stock", (
        "LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations", "NoncurrentPortionOfNoncurrentBorrowings", "LongtermBorrowings", "NoncurrentBorrowings")),
    "debt_current": ("Debito in scadenza entro 12 mesi", "Debt due within 12 months", "stock", (
        "LongTermDebtCurrent", "DebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent",
        "CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings", "CurrentPortionOfLongtermBorrowings", "ShorttermBorrowings")),
    "cfo": ("Flusso di cassa operativo", "Operating cash flow", "flow", (
        "NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        "CashFlowsFromUsedInOperatingActivities", "CashFlowsFromUsedInOperatingActivitiesContinuingOperations")),
    "capex": ("Investimenti (capex)", "Capex", "flow", (
        "PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
        "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", "PurchaseOfPropertyPlantAndEquipment",
        "PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets")),
    "buybacks": ("Riacquisto azioni", "Buybacks", "flow", ("PaymentsForRepurchaseOfCommonStock", "PaymentsForRepurchaseOfEquity", "PaymentsToAcquireOrRedeemEntitysShares")),
    "dividends": ("Dividendi pagati", "Dividends paid", "flow", (
        "PaymentsOfDividends", "PaymentsOfDividendsCommonStock", "DividendsPaidClassifiedAsFinancingActivities",
        "DividendsPaidToEquityHoldersOfParentClassifiedAsFinancingActivities", "DividendsPaid")),
    "sbc": ("Compensi in azioni", "Stock-based comp.", "flow", ("ShareBasedCompensation", "AllocatedShareBasedCompensationExpense", "AdjustmentsForSharebasedPayments")),
    "opex_total": ("Totale costi operativi", "Total operating expenses", "flow", ("OperatingExpenses", "CostsAndExpenses")),
    "temp_equity": ("Azioni privilegiate riscattabili", "Redeemable preferred stock", "stock", (
        "TemporaryEquityCarryingAmountAttributableToParent", "TemporaryEquityCarryingAmountIncludingPortionAttributableToNoncontrollingInterests")),
    "cfi": ("Flusso di cassa da investimenti", "Investing cash flow", "flow", (
        "NetCashProvidedByUsedInInvestingActivities", "CashFlowsFromUsedInInvestingActivities")),
    "cff": ("Flusso di cassa da finanziamenti", "Financing cash flow", "flow", (
        "NetCashProvidedByUsedInFinancingActivities", "CashFlowsFromUsedInFinancingActivities")),
    "fx_effect": ("Effetto cambi sulla cassa", "Exchange-rate effect on cash", "flow", (
        "EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "EffectOfExchangeRateOnCashAndCashEquivalents",
        "EffectOfExchangeRateChangesOnCashAndCashEquivalents")),
    "cash_hfs": ("Cassa in attività destinate alla vendita", "Cash in assets held for sale", "flow", ()),
    "cash_change": ("Variazione della cassa", "Change in cash", "flow", (
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        "CashAndCashEquivalentsPeriodIncreaseDecrease", "IncreaseDecreaseInCashAndCashEquivalents",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseExcludingExchangeRateEffect")),
}

ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "40-F", "ESEF"}


def _d(s: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


class Periods:
    """Current and comparative periods of the document."""

    def __init__(self, doc: IxDoc):
        self.doc = doc
        ctxs = [c for c in doc.contexts.values() if not c.dimensional]
        dur = [c for c in ctxs if c.start and c.end]
        used = Counter(f.context for f in doc.facts)

        main = doc.contexts.get(doc.info_ctx.get("DocumentPeriodEndDate", ""))
        if main is None or not (main.start and main.end):
            # most used non-dimensional duration among the latest end dates, preferring a full year
            cands = [c for c in dur if used[c.id]]
            cands.sort(key=lambda c: (c.end, 330 <= (c.days or 0) <= 380, used[c.id]), reverse=True)
            main = cands[0] if cands else None
        self.end = _d(main.period_end) if main else None
        self.days = main.days if main and main.days else 365
        self.cur_dur, self.prev_dur = set(), set()
        self.cur_inst, self.prev_inst = set(), set()
        self.prev_inst_end = None
        if not self.end:
            return
        for c in dur:
            e, n = _d(c.end), c.days or 0
            if not e or abs(n - self.days) > 20:
                continue
            if abs((e - self.end).days) <= 3:
                self.cur_dur.add(c.id)
            elif 350 <= (self.end - e).days <= 380:
                self.prev_dur.add(c.id)
        inst = [c for c in ctxs if c.instant]
        for c in inst:
            if abs((_d(c.instant) - self.end).days) <= 3:
                self.cur_inst.add(c.id)
        # comparative balance sheet: about a year earlier (annual) or the last fiscal year end (interim)
        prev_ends = sorted({_d(c.instant) for c in inst if _d(c.instant) and 60 <= (self.end - _d(c.instant)).days <= 400}, reverse=True)
        stock_used = Counter(_d(doc.contexts[f.context].instant) for f in doc.facts
                             if f.context in doc.contexts and doc.contexts[f.context].instant and not doc.contexts[f.context].dimensional)
        if prev_ends:
            annual = [e for e in prev_ends if 350 <= (self.end - e).days <= 380]
            pe = annual[0] if annual else max(prev_ends, key=lambda e: stock_used[e])
            self.prev_inst = {c.id for c in inst if _d(c.instant) == pe}
            self.prev_inst_end = pe

    def role(self, f: Fact) -> Optional[str]:
        c = f.context
        if c in self.cur_dur or c in self.cur_inst:
            return "cur"
        if c in self.prev_dur or c in self.prev_inst:
            return "prev"
        return None


def _pick(cands: list[Fact], page_weight: list[int]) -> Optional[Fact]:
    """Same value printed several times: use the occurrence on the page with most figures (the statements)."""
    if not cands:
        return None
    return max(cands, key=lambda f: (page_weight[f.page - 1] if f.page else -1, -f.page))


def _fact_dict(f: Fact, units: dict[str, str]) -> dict:
    return {"id": f.id, "value": f.value, "display": f.display, "page": f.page, "concept": f.concept, "unit": units.get(f.unit or "", f.unit or "")}


def extract(doc: IxDoc) -> dict:
    per = Periods(doc)
    by_local: dict[str, list[Fact]] = {}
    for f in doc.facts:
        if f.value is None or f.context not in doc.contexts or doc.contexts[f.context].dimensional:
            continue
        by_local.setdefault(f.local, []).append(f)

    metrics = {}
    for key, (it, en, kind, concepts) in METRICS.items():
        found = []
        for concept in concepts:
            facts = by_local.get(concept, [])
            cur = _pick([f for f in facts if per.role(f) == "cur"], doc.page_fact_count)
            if cur is None:
                continue
            prev = _pick([f for f in facts if per.role(f) == "prev"], doc.page_fact_count)
            found.append((cur, prev))
            if key != "revenue":
                break
        if found:
            # revenue: the total of the concepts the filing tags (American Express: revenues net of interest expense,
            # 52.9bn, beside revenue from contracts with customers, 34.2bn)
            cur, prev = max(found, key=lambda cp: cp[0].value or 0) if key == "revenue" else found[0]
            metrics[key] = {"key": key, "it": it, "en": en, "kind": kind,
                            "cur": _fact_dict(cur, doc.units), "prev": _fact_dict(prev, doc.units) if prev else None}
    # extension concepts (a bank's "isp:GrossIncome"): recognise the line by the label of its table row
    from . import statements
    missing = set(METRICS) - set(metrics)
    if missing:
        by_label: dict[str, dict] = {}
        for f in doc.facts:
            if f.value is None or f.context not in doc.contexts or doc.contexts[f.context].dimensional or not (f.row_label or "Exchange" in f.local):
                continue
            key = statements.match(f.row_label)
            if key is None and "EffectOfExchangeRate" in f.local and "Cash" in f.local:
                key = "fx_effect"                      # "eni:EffectOfExchangeRateChangesAndOtherChangesOnCash…", unlabelled
            role = per.role(f)
            if key in missing and role and (METRICS[key][2] == "stock") == bool(doc.contexts[f.context].instant):
                by_label.setdefault(key, {}).setdefault(role, []).append(f)
        for key, roles in by_label.items():
            cur = _pick(roles.get("cur", []), doc.page_fact_count)
            if cur is None:
                continue
            prev = _pick(roles.get("prev", []), doc.page_fact_count)
            it, en, kind, _ = METRICS[key]
            metrics[key] = {"key": key, "it": it, "en": en, "kind": kind,
                            "cur": _fact_dict(cur, doc.units), "prev": _fact_dict(prev, doc.units) if prev else None}
    currency = next((m["cur"]["unit"] for m in metrics.values() if m["kind"] in ("flow", "stock") and m["cur"]["unit"]), "")
    return {"periods": per, "metrics": metrics, "currency": currency}


def _v(m: dict, key: str, which: str = "cur") -> Optional[float]:
    x = m.get(key)
    if not x or not x.get(which):
        return None
    return x[which]["value"]


def _pages(m: dict, *keys: str, which: str = "cur") -> list[int]:
    out = []
    for k in keys:
        x = m.get(k)
        if x and x.get(which) and x[which]["page"] and x[which]["page"] not in out:
            out.append(x[which]["page"])
    return out


def _div(a, b):
    return a / b if a is not None and b not in (None, 0) else None


def _growth(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / abs(prev)


# a bank's or an insurer's operating cash flow moves with deposits, loans and policies: free cash flow means nothing there
FINANCIAL_HINTS = ("Deposits", "DepositsFromCustomers", "LoansAndAdvancesToCustomers", "InterestRevenueCalculatedUsingEffectiveInterestMethod",
                   "FeeAndCommissionIncome", "InterestAndDividendIncomeOperating", "LoansAndLeasesReceivableNetReportedAmount",
                   "InsuranceContractsIssuedThatAreLiabilities", "PolicyholderFunds", "NoninterestIncome")


def is_financial(doc: IxDoc) -> bool:
    names = {f.local for f in doc.facts}
    return sum(1 for h in FINANCIAL_HINTS if h in names) >= 2


def derive(m: dict) -> dict:
    """Ratios and derived figures for current and previous period."""
    out = {}
    for which in ("cur", "prev"):
        g = lambda k: _v(m, k, which)
        rev, cfo, capex = g("revenue"), g("cfo"), g("capex")
        liab = g("total_liabilities")
        if liab is None and g("liab_and_equity") is not None and g("equity") is not None:
            liab = g("liab_and_equity") - g("equity") - (g("temp_equity") or 0)
        debt = g("debt_total")
        if debt is None and (g("debt_noncurrent") is not None or g("debt_current") is not None):
            debt = (g("debt_noncurrent") or 0) + (g("debt_current") or 0)
        gross = g("gross_profit")
        if gross is None and rev is not None and g("cost_of_revenue") is not None:
            gross = rev - g("cost_of_revenue")
        fcf = cfo - capex if cfo is not None and capex is not None else None
        ret = None
        if g("buybacks") is not None or g("dividends") is not None:
            ret = (g("buybacks") or 0) + (g("dividends") or 0)
        pre, ie = g("pretax_income"), g("interest_expense")
        out[which] = {
            "fcf": fcf,
            "gross_profit": gross,
            "total_liabilities": liab,
            "debt": debt,
            "gross_margin": _div(gross, rev),
            "operating_margin": _div(g("operating_income"), rev),
            "net_margin": _div(g("net_income"), rev),
            "fcf_margin": _div(fcf, rev),
            "rnd_ratio": _div(g("rnd"), rev),
            "tax_rate": _div(g("income_tax"), pre) if pre and pre > 0 else None,
            "interest_coverage": _div(pre + ie, ie) if pre is not None and ie else None,
            "debt_to_assets": _div(debt, g("total_assets")),
            "equity_multiplier": _div(g("total_assets"), g("equity")) if (g("equity") or 0) > 0 else None,
            "current_ratio": _div(g("current_assets"), g("current_liabilities")),
            "shareholder_return": ret,
            "return_pct_fcf": _div(ret, fcf) if fcf and fcf > 0 and ret else None,
            "sbc_pct_fcf": _div(g("sbc"), fcf) if fcf and fcf > 0 else None,
            "cash_vs_debt_due": _div(g("cash"), g("debt_current")),
        }
    out["growth"] = {
        "revenue": _growth(_v(m, "revenue"), _v(m, "revenue", "prev")),
        "net_income": _growth(_v(m, "net_income"), _v(m, "net_income", "prev")),
        "eps_diluted": _growth(_v(m, "eps_diluted"), _v(m, "eps_diluted", "prev")),
        "operating_income": _growth(_v(m, "operating_income"), _v(m, "operating_income", "prev")),
        "fcf": _growth(out["cur"]["fcf"], out["prev"]["fcf"]),
        "cfo": _growth(_v(m, "cfo"), _v(m, "cfo", "prev")),
    }
    return out


def checks(m: dict) -> list[dict]:
    """Arithmetic cross-checks between figures read in the document (current period)."""
    out = []
    ok = t("quadra", "balances")

    cur = next((x["cur"].get("unit") for x in m.values() if x.get("cur") and x["cur"].get("unit") and len(x["cur"]["unit"]) == 3), "")

    def add(name, lhs, rhs, tol, pages, between=False, why=None):
        """between: other lines may sit between the figures (amortisation, equity-method income…); why: the reason, translated."""
        if lhs is None or rhs is None or (lhs == 0 and rhs == 0):
            return
        diff = abs(lhs - rhs) / max(abs(rhs), abs(lhs), 1e-9)
        if diff <= tol:
            detail = ok
        elif between:
            detail = t("differenza di {d}: {why}", "differs by {d}: {why}", d=fmt_money(abs(lhs - rhs), cur),
                       why=why or t("altre voci tra le due cifre", "other lines sit between the figures"))
        else:
            detail = t("scarto del {p}", "off by {p}", p=fmt_num(diff * 100, 1) + pct_sign())
        out.append({"name": name, "ok": diff <= tol, "diff_pct": round(diff * 100, 2), "pages": pages, "detail": detail})

    v = lambda k: _v(m, k)
    rev, cost, gross = v("revenue"), v("cost_of_revenue"), v("gross_profit")
    if None not in (rev, cost, gross):
        add(t("Margine lordo = ricavi − costo del venduto", "Gross profit = revenue − cost of revenue"), gross, rev - cost, 0.005,
            _pages(m, "revenue", "gross_profit"), between=True)
    opex, oi = v("opex_total"), v("operating_income")
    if None not in (rev, opex, oi):
        # total operating expenses either include the cost of revenue or come after gross profit
        lhs = rev - opex
        if cost is not None and abs(rev - cost - opex - oi) < abs(lhs - oi):
            lhs = rev - cost - opex
        add(t("Ricavi − costi operativi = risultato operativo", "Revenue − operating expenses = operating income"), lhs, oi, 0.01,
            _pages(m, "revenue", "opex_total", "operating_income"), between=True)
    pre, tax = v("pretax_income"), v("income_tax")
    ni = v("profit_total") if v("profit_total") is not None else v("net_income")
    if None not in (pre, tax, ni):
        # a tax benefit adds to the result: the sign printed varies, so both readings are tried
        lhs = pre - tax if abs(pre - tax - ni) <= abs(pre + tax - ni) else pre + tax
        add(t("Risultato ante imposte − imposte = risultato netto", "Pre-tax income − taxes = net income"), lhs, ni, 0.02,
            _pages(m, "pretax_income", "income_tax", "net_income"), between=True)
    a, l, e, te = v("total_assets"), v("total_liabilities"), v("equity"), v("temp_equity")
    if None not in (a, l, e):
        name = t("Attivo = passivo + privilegiate riscattabili + patrimonio netto", "Assets = liabilities + redeemable preferred + equity") \
            if te is not None else t("Attivo = passivo + patrimonio netto", "Assets = liabilities + equity")
        add(name, a, l + e + (te or 0), 0.01, _pages(m, "total_assets", "total_liabilities", "temp_equity", "equity"))
    elif a is not None and v("liab_and_equity") is not None:
        add(t("Attivo = passivo e patrimonio netto", "Assets = liabilities and equity"), a, v("liab_and_equity"), 0.001, _pages(m, "total_assets", "liab_and_equity"))
    eps, sh, nip = v("eps_diluted"), v("diluted_shares"), v("net_income")
    if None not in (eps, sh, nip) and sh > 0 and nip:
        # share counts are sometimes printed in thousands or millions
        prod = min((eps * sh * k for k in (1, 1e3, 1e6)), key=lambda x: abs(x - nip))
        add(t("EPS diluito × azioni diluite ≈ risultato netto", "Diluted EPS × diluted shares ≈ net income"), prod, nip, 0.03,
            _pages(m, "eps_diluted", "diluted_shares", "net_income"))
    cfo, cfi, cff, dc = v("cfo"), v("cfi"), v("cff"), v("cash_change")
    if None not in (cfo, cfi, cff, dc):
        # the change in cash is printed before or after the exchange-rate effect: either way must balance
        fx = v("fx_effect")
        lhs = cfo + cfi + cff
        if fx is not None and abs(lhs + fx - dc) < abs(lhs - dc):
            lhs += fx
        hfs = v("cash_hfs")                               # cash moved to (or back from) assets held for sale
        if hfs is not None and abs(lhs + hfs - dc) < abs(lhs - dc):
            lhs += hfs
        # no exchange-rate line read and a gap that is small next to the flows: a line the reader did not find
        small = fx is None and abs(lhs - dc) <= 0.01 * max(abs(cfo), abs(cfi), abs(cff))
        add(t("Flussi operativo + investimenti + finanziamenti (+ cambi) ≈ variazione della cassa",
              "Operating + investing + financing cash flows (+ exchange rates) ≈ change in cash"), lhs, dc, 0.01 if fx is not None else 0.02,
            _pages(m, "cfo", "cfi", "cff", "cash_change"), between=small,
            why=t("probabilmente effetto cambi o perimetro, voce non letta", "likely exchange-rate or scope effects, a line not read"))
    return out


# ---------------------------------------------------------------- formatting (report language)

def label(key: str) -> str:
    it, en = METRICS[key][0], METRICS[key][1]
    return t(it, en)


SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CHF": "CHF ", "CAD": "C$", "SEK": "SEK ", "DKK": "DKK ", "NOK": "NOK "}


# large amounts in each language: "$16.3B", "$16,3 mld", "16,3 Mrd.", "$163亿" (Chinese and Japanese count in 10^4 and 10^8)
NB = "\u00a0"
UNITS = {
    "en": ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")),
    "it": ((1e12, " bln"), (1e9, " mld"), (1e6, " mln"), (1e3, " mila")),
    "es": ((1e12, " bill."), (1e9, " mil M"), (1e6, " M"), (1e3, " mil")),
    "fr": ((1e9, NB + "Md"), (1e6, NB + "M"), (1e3, NB + "k")),
    "de": ((1e12, " Bio."), (1e9, " Mrd."), (1e6, " Mio."), (1e3, " Tsd.")),
    "pt": ((1e12, " tri"), (1e9, " bi"), (1e6, " mi"), (1e3, " mil")),
    "ru": ((1e12, " трлн"), (1e9, " млрд"), (1e6, " млн"), (1e3, " тыс.")),
    "zh": ((1e12, "万亿"), (1e8, "亿"), (1e4, "万")),
    "ja": ((1e12, "兆"), (1e8, "億"), (1e4, "万")),
}


def fmt_money(v: Optional[float], cur: str = "") -> str:
    if v is None:
        return "—"
    sym = SYMBOLS.get(cur.upper(), (cur + " ") if cur else "")
    a, sign = abs(v), "−" if v < 0 else ""
    for div, suf in UNITS.get(lang(), UNITS["en"]):
        if a >= div:
            n = a / div
            s = f"{n:,.1f}" if n < 100 else f"{n:,.0f}"
            return f"{sign}{sym}{_it(s)}{suf}"
    return f"{sign}{sym}{_it(f'{a:,.2f}')}"


def fmt_num(v: Optional[float], dec: int = 2) -> str:
    return "—" if v is None else _it(f"{v:,.{dec}f}")


def fmt_pct(v: Optional[float], dec: int = 1, signed: bool = False) -> str:
    if v is None:
        return "—"
    if abs(v) >= 10:                       # +1,300% rather than +1300.4%
        dec = 0
    s = f"{v * 100:+,.{dec}f}" if signed else f"{v * 100:,.{dec}f}"
    return (_it(s) + pct_sign()).replace("-", "−")


def art(s: str, prep: bool = True) -> str:
    """Italian article before a number: "del 20%", "dell'11%", "il 39%", "l'8%"."""
    digits = "".join(ch for ch in s.split(",")[0] if ch.isdigit())
    elide = digits.startswith("8") or digits in ("1", "11")
    if prep:
        return ("dell'" if elide else "del ") + s
    return ("l'" if elide else "il ") + s


def _it(s: str) -> str:
    """A number written the report language's way: 1,234.5 in English, 1.234,5 in Italian, 1 234,5 in French."""
    return num(s)


def fmt_value(key: str, v: Optional[float], cur: str) -> str:
    kind = METRICS.get(key, ("", "", "flow", ()))[2]
    if kind == "ps":
        return "—" if v is None else _ps(v, cur)
    if kind == "shares":
        return fmt_money(v, "").strip() if v is not None else "—"
    return fmt_money(v, cur)


def _ps(v: float, cur: str) -> str:
    sym = {"USD": "$", "EUR": "€", "GBP": "£"}.get(cur.upper(), (cur + " ") if cur else "")
    return ("−" if v < 0 else "") + sym + _it(f"{abs(v):,.2f}")


# ---------------------------------------------------------------- findings

def findings(m: dict, d: dict, cur: str, period: str = "", vs: str = "") -> list[dict]:
    """Observations ranked by how much they say; each cites the page(s) it rests on.
    period / vs: the periods compared ("H1 2026" / "H1 2025"), when they are not plain years."""
    c, p, g = d["cur"], d["prev"], d["growth"]
    out: list[tuple[float, dict]] = []
    pct, money = fmt_pct, fmt_money

    def add(score, text, pages, keys):
        out.append((score, {"text": text, "pages": [x for x in pages if x], "keys": keys}))

    if g["revenue"] is not None:
        rv, rp, gr = money(_v(m, "revenue"), cur), money(_v(m, "revenue", "prev"), cur), pct(abs(g["revenue"]))
        kw = dict(g=gr, art_g=art(gr), v=rv, p=rp, when=t(" ({a} vs {b})", " ({a} vs {b})", a=period, b=vs) if period and vs else "")
        add(1 + abs(g["revenue"]) * 4,
            t("Ricavi in crescita {art_g} a {v} (da {p}){when}.", "Revenue up {g} to {v} (from {p}){when}.", **kw) if g["revenue"] >= 0 else
            t("Ricavi in calo {art_g} a {v} (da {p}){when}.", "Revenue down {g} to {v} (from {p}){when}.", **kw), _pages(m, "revenue"), ["revenue"])
    ni_c, ni_p = _v(m, "net_income"), _v(m, "net_income", "prev")
    if ni_c is not None and ni_p is not None and (ni_c < 0 or ni_p < 0):
        # losses: say what happened to the loss instead of a growth rate of a negative number
        kw = dict(a=money(ni_p, cur), b=money(ni_c, cur))
        if ni_c < 0 and ni_p < 0:
            txt = t("Perdita netta ampliata da {a} a {b}.", "Net loss widened from {a} to {b}.", **kw) if ni_c < ni_p else \
                t("Perdita netta ridotta da {a} a {b}.", "Net loss narrowed from {a} to {b}.", **kw)
        elif ni_c < 0:
            txt = t("Da un utile netto di {a} a una perdita di {b}.", "From net income of {a} to a net loss of {b}.", **kw)
        else:
            txt = t("Da una perdita di {a} a un utile netto di {b}.", "From a net loss of {a} to net income of {b}.", **kw)
        add(1.6, txt, _pages(m, "net_income"), ["net_income"])
    elif g["revenue"] is not None and g["net_income"] is not None and abs(g["net_income"] - g["revenue"]) > 0.03:
        kw = dict(ni=pct(g["net_income"], signed=True), rv=pct(g["revenue"], signed=True))
        add(1.2 + abs(g["net_income"] - g["revenue"]) * 3,
            t("L'utile netto ({ni}) cresce più dei ricavi ({rv}): i margini si stanno allargando.",
              "Net income ({ni}) is growing faster than revenue ({rv}): margins are widening.", **kw) if g["net_income"] > g["revenue"] else
            t("L'utile netto ({ni}) cresce meno dei ricavi ({rv}): i margini si stanno restringendo.",
              "Net income ({ni}) is growing slower than revenue ({rv}): margins are narrowing.", **kw),
            _pages(m, "net_income", "revenue"), ["net_income", "revenue"])
    if c["operating_margin"] is not None:
        om = pct(c["operating_margin"])
        if p["operating_margin"] is not None:
            delta = (c["operating_margin"] - p["operating_margin"]) * 100
            txt = t("Margine operativo {art_m} ({d} punti rispetto al periodo di confronto).", "Operating margin of {m} ({d} points on the comparative period).",
                    m=om, art_m=art(om), d=f"{'+' if delta >= 0 else '−'}{_it(f'{abs(delta):.1f}')}")
        else:
            txt = t("Margine operativo {art_m}.", "Operating margin of {m}.", m=om, art_m=art(om))
        add(1 + abs(c["operating_margin"]) + (abs(c["operating_margin"] - p["operating_margin"]) * 10 if p["operating_margin"] is not None else 0),
            txt, _pages(m, "operating_income"), ["operating_income"])
    if c["fcf"] is not None:
        txt = t("Free cash flow di {v}", "Free cash flow of {v}", v=money(c["fcf"], cur))
        if g["fcf"] is not None and (d["prev"]["fcf"] or 0) > 0 and c["fcf"] > 0:
            txt += t(" ({g} sull'anno)", " ({g} year on year)", g=pct(g["fcf"], signed=True))
        elif d["prev"]["fcf"] is not None:
            txt += t(" (era {v})", " (was {v})", v=money(d["prev"]["fcf"], cur))
        if c["return_pct_fcf"]:
            rp = pct(c["return_pct_fcf"], 0)
            txt += t("; {art_p} è tornato agli azionisti tra riacquisti e dividendi", "; {p} went back to shareholders through buybacks and dividends",
                     p=rp, art_p=art(rp, False))
        add(1.5 + (abs(g["fcf"]) if g["fcf"] is not None else 0), txt + t(".", "."), _pages(m, "cfo", "capex", "buybacks", "dividends"), ["cfo", "capex"])
    if c["fcf"] is not None and _v(m, "net_income") and _v(m, "net_income") > 0:
        conv = c["fcf"] / _v(m, "net_income")
        if conv < 0.7 or conv > 1.3:
            cv = _it(f"{conv:.2f}")
            add(1.3 + abs(conv - 1),
                t("Il free cash flow vale {x} volte l'utile netto: la cassa generata supera gli utili contabili.",
                  "Free cash flow is {x} times net income: cash generation exceeds reported earnings.", x=cv) if conv > 1 else
                t("Il free cash flow vale {x} volte l'utile netto: gli utili si convertono in cassa solo in parte.",
                  "Free cash flow is {x} times net income: only part of the earnings turns into cash.", x=cv),
                _pages(m, "cfo", "net_income"), ["cfo", "net_income"])
    if c["sbc_pct_fcf"] is not None and c["sbc_pct_fcf"] > 0.15:
        sv, sp = money(_v(m, "sbc"), cur), pct(c["sbc_pct_fcf"], 0)
        add(1 + c["sbc_pct_fcf"] * 2,
            t("I compensi in azioni ({v}) valgono {art_p} del free cash flow.", "Stock-based compensation ({v}) equals {p} of free cash flow.",
              v=sv, p=sp, art_p=art(sp, False)), _pages(m, "sbc"), ["sbc"])
    if c["interest_coverage"] is not None:
        ic = c["interest_coverage"]
        iv = _it(f"{ic:.1f}")
        add(0.8 + (1.5 if ic < 3 else 0),
            t("Gli utili ante interessi coprono gli interessi passivi {x} volte — copertura stretta.",
              "Earnings before interest cover interest expense {x} times — thin coverage.", x=iv) if ic < 3 else
            t("Gli utili ante interessi coprono gli interessi passivi {x} volte.", "Earnings before interest cover interest expense {x} times.", x=iv),
            _pages(m, "interest_expense", "pretax_income"), ["interest_expense"])
    if _v(m, "debt_current") is not None and _v(m, "cash") is not None:
        r = c["cash_vs_debt_due"]
        short = r is not None and r < 1
        kw = dict(d=money(_v(m, "debt_current"), cur), c=money(_v(m, "cash"), cur))
        add(0.9 + (1.5 if short else 0),
            t("Debito in scadenza entro 12 mesi: {d}, contro una cassa di {c} — la cassa non basta a coprirlo.",
              "Debt due within 12 months: {d}, against cash of {c} — cash does not cover it.", **kw) if short else
            t("Debito in scadenza entro 12 mesi: {d}, contro una cassa di {c}.", "Debt due within 12 months: {d}, against cash of {c}.", **kw),
            _pages(m, "debt_current", "cash"), ["debt_current", "cash"])
    if c["current_ratio"] is not None:
        cr = c["current_ratio"]
        crv = _it(f"{cr:.2f}")
        add(0.6 + (1.2 if cr < 1 else 0),
            t("Current ratio di {x}: l'attivo corrente copre il passivo corrente.", "Current ratio of {x}: current assets cover current liabilities.", x=crv)
            if cr >= 1 else
            t("Current ratio di {x}: l'attivo corrente non copre il passivo corrente.", "Current ratio of {x}: current assets do not cover current liabilities.", x=crv),
            _pages(m, "current_assets", "current_liabilities"), ["current_assets", "current_liabilities"])
    if c["equity_multiplier"] is not None:
        em = c["equity_multiplier"]
        ev = _it(f"{em:.1f}")
        add(0.5 + (1 if em > 4 else 0),
            t("Moltiplicatore del capitale di {x}x (attivo / patrimonio netto): bilancio molto a leva.",
              "Equity multiplier of {x}x (assets / equity): a highly leveraged balance sheet.", x=ev) if em > 4 else
            t("Moltiplicatore del capitale di {x}x (attivo / patrimonio netto).", "Equity multiplier of {x}x (assets / equity).", x=ev),
            _pages(m, "total_assets", "equity"), ["total_assets", "equity"])
    if c["rnd_ratio"] is not None and c["rnd_ratio"] > 0.05:
        rr, rv = pct(c["rnd_ratio"]), money(_v(m, "rnd"), cur)
        add(0.7 + c["rnd_ratio"],
            t("Spende {art_p} dei ricavi in ricerca e sviluppo ({v}).", "Spends {p} of revenue on research and development ({v}).", p=rr, art_p=art(rr, False), v=rv),
            _pages(m, "rnd"), ["rnd"])
    if g["eps_diluted"] is not None and (_v(m, "eps_diluted") or 0) > 0 and (_v(m, "eps_diluted", "prev") or 0) > 0:
        add(0.9 + abs(g["eps_diluted"]) * 2, t("EPS diluito a {v} ({g}).", "Diluted EPS of {v} ({g}).", v=_ps(_v(m, "eps_diluted"), cur), g=pct(g["eps_diluted"], signed=True)),
            _pages(m, "eps_diluted"), ["eps_diluted"])
    out.sort(key=lambda x: -x[0])
    return [f for _, f in out]


# ---------------------------------------------------------------- card

def card(m: dict, d: dict, cur: str, vs: str = "") -> list[dict]:
    """Four headline tiles; vs = the comparison period ("H1 2025"), shown next to the change."""
    tiles = []
    for key in ("revenue", "net_income", "eps_diluted", "fcf"):
        note = ""
        if key == "fcf":
            v, pv = d["cur"]["fcf"], d["prev"]["fcf"]
            pages = _pages(m, "cfo", "capex")
            it, en = "Free cash flow", "Free cash flow"
            disp = fmt_money(v, cur)
            if v is not None:
                note = t("calcolato: flusso operativo − capex", "computed: operating cash flow − capex")
        else:
            v, pv = _v(m, key), _v(m, key, "prev")
            pages = _pages(m, key)
            it, en = METRICS[key][0], METRICS[key][1]
            if key == "net_income" and v is not None and v < 0:
                it, en = "Perdita netta", "Net loss"
            if key == "eps_diluted" and v is not None and v < 0:
                it, en = "Perdita per azione diluita", "Diluted loss per share"
            disp = fmt_value(key, v, cur)
        gr = _growth(v, pv)
        prev_display = ""
        if gr is not None and (v < 0 or pv < 0):
            # a growth rate between negative numbers misleads: show the comparative value instead
            gr = None
            prev_display = fmt_ps(pv, cur) if key == "eps_diluted" else fmt_money(pv, cur)
        tiles.append({"key": key, "it": it, "en": en, "label": t(it, en), "value": v, "display": disp, "exact": fmt_exact(v, cur) if key != "eps_diluted" else "",
                      "yoy": gr, "yoy_display": fmt_pct(gr, signed=True) if gr is not None else "", "prev_display": prev_display,
                      "vs": vs if (gr is not None or prev_display) else "", "note": note, "pages": pages})
    return tiles


def fmt_exact(v: Optional[float], cur: str) -> str:
    """The amount in millions as statements print it: "$16,286 million" / "$16.286 mln"."""
    if v is None or abs(v) < 1e7:
        return ""
    sym = SYMBOLS.get(cur.upper(), (cur + " ") if cur else "")
    n = _it(f"{abs(v) / 1e6:,.0f}")
    return ("−" if v < 0 else "") + sym + n + t(" mln", " million")


def fmt_ps(v: Optional[float], cur: str) -> str:
    return "—" if v is None else _ps(v, cur)
