"""Helpers for the translation catalogs: which English texts the code can show, found two ways.

- statically: every t() / ui() / tl() / _msg() call written with literal texts;
- at run time: documents of every kind read and exported (PDF, PowerPoint, Excel) in a language, recording the
  texts its catalog lacks (i18n.MISSING) — this also finds texts passed as variables, t(*pair).
"""
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))


def static_keys() -> dict:
    """English text -> Italian text, for every call with literal texts."""
    out = {}
    for p in [ROOT / "server.py"] + sorted((ROOT / "analyst").glob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            args = node.args[1:] if name == "tl" else node.args
            if name not in ("t", "ui", "tl", "_msg") or len(args) < 2:
                continue
            it, en = args[0], args[1]
            if isinstance(it, ast.Constant) and isinstance(en, ast.Constant) and isinstance(en.value, str):
                out[en.value] = it.value
    return out


def exercise(lang: str, tmp: Path) -> None:
    """Read and export documents of every kind in `lang` (no network, no AI); global state is restored after."""
    from analyst import ai, pipeline, sources
    saved = pipeline.DOCS, ai.active, sources.price_history
    pipeline.DOCS, ai.active = tmp, (lambda: None)
    try:
        _exercise(lang)
    finally:
        pipeline.DOCS, ai.active, sources.price_history = saved


def _exercise(lang: str) -> None:
    import make_fixtures
    import make_s1
    import synth
    from analyst import market, pdfreport, pipeline, pptx_report, xlsx_export, financials as F, sources
    from analyst.i18n import using
    docs = [("upload", make_s1.s1().encode(), "s1.htm"), ("upload", make_fixtures.sec().encode(), "10k.htm"),
            ("upload", make_fixtures.esef().encode(), "esef.xhtml")]
    (HERE / "fixtures").mkdir(exist_ok=True)
    import make_pdf  # noqa: F401  (writes fixtures/kid.pdf)
    import make_pdf_en  # noqa: F401  (writes fixtures/annual_en.pdf)
    for f in ("kid.pdf", "annual_en.pdf"):
        docs.append(("upload", (HERE / "fixtures" / f).read_bytes(), f))
    analyses = []
    for kind, data, name in docs:
        analyses.append(pipeline.run({"kind": kind, "data": data, "name": name, "lang": lang}, lambda *_: None))
    with using(lang):
        a = market.build(synth.series())
    sources.price_history = lambda s: synth.series()
    analyses.append(pipeline.run({"kind": "market", "symbol": "TEST-USD", "lang": lang}, lambda *_: None))
    for a in analyses:
        a = json.loads(json.dumps(a))
        pdfreport.build(a)
        pptx_report.build(a)
        xlsx_export.build(a)
    # every metric label, every check and message reachable only with other data
    with using(lang):
        for k in F.METRICS:
            F.label(k)
