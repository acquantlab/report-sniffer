"""The AI context, with a simulated model: what is kept, what is dropped, how it reaches the report."""
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
FIX = HERE / "fixtures"

from analyst import ai, pdfreport, pipeline, reader  # noqa: E402

BREAK = '<hr style="page-break-after:always">'
S1 = ("<html><body>"
      "<div><h1>Lumen Labs, Inc.</h1><p>Prospectus. 10,000,000 shares of Class A common stock. "
      "Initial public offering price $21.00 per share.</p></div>" + BREAK +
      "<div><h2>Prospectus summary</h2><p>We sell access to our models to 1,200 enterprise customers.</p></div>" + BREAK +
      "<div><h2>Summary consolidated financial data</h2><p>(in millions)</p><table>"
      "<tr><td></td><td>2025</td><td>2024</td></tr>"
      "<tr><td>Model access sales</td><td>3,400</td><td>1,100</td></tr>"
      "<tr><td>Result of the business</td><td>(2,100)</td><td>(2,600)</td></tr>"
      "<tr><td>Result for the year</td><td>(1,900)</td><td>(2,500)</td></tr></table></div>"
      "</body></html>").encode()


NEWS = [{"title": "Lumen Labs prices its IPO at $21.00", "source": "Example Wire", "url": "https://news.example.com/lumen-ipo",
         "date": "2026-11-02", "summary": "Demand was strong; the shares rose 35% on the first day."},
        {"title": "No address", "source": "x", "url": "news.example.com/x", "date": "", "summary": ""},
        {"title": "Not from the search", "source": "x", "url": "https://elsewhere.example.org/y", "date": "", "summary": ""}]
ANSWER = {
    "doc_type": "S-1 registration statement",
    "summary": "Lumen Labs sells access to AI models. Revenue was 3,400 million in 2025. It is worth 77 billion.",
    "sections": [{"title": "In context", "points": [
        {"text": "10,000,000 shares at $21.00 each.", "pages": [1], "news": []},
        {"text": "The shares rose 35% after the listing.", "pages": [], "news": [0]},
        {"text": "The shares rose 35% after the listing, says nobody.", "pages": [], "news": []},
        {"text": "A valuation of $500 billion.", "pages": [1], "news": [0]}]}],
    "news": NEWS,
}


@pytest.fixture
def fake_ai(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "DOCS", tmp_path / "docs")
    monkeypatch.setattr(ai, "active", lambda: ("anthropic", "sk-test", "claude-test"))
    prompts = []

    def install(answer):
        def call(prompt, schema, max_tokens=16000, web=False):
            prompts.append((prompt, web))
            out = answer(prompt) if callable(answer) else json.loads(json.dumps(answer))
            return {**out, "_search_urls": [NEWS[0]["url"], NEWS[1]["url"]]} if web else out
        monkeypatch.setattr(ai, "_call", call)
    install.prompts = prompts
    return install


def test_validation_keeps_only_what_the_pages_and_the_news_show():
    pages = {1: "Initial public offering price $21.00 per share. 10,000,000 shares", 3: "Model access sales 3,400 1,100 (1,900)"}
    r = reader.validate(json.loads(json.dumps(ANSWER)), pages, {}, [], "", [NEWS[0]["url"], NEWS[1]["url"]])
    assert "77" not in r["summary"] and r["summary"].startswith("Lumen Labs")
    assert [n["title"] for n in r["news"]] == ["Lumen Labs prices its IPO at $21.00"]   # no address / not from the search
    pts = r["sections"][0]["points"]
    assert [p["text"] for p in pts] == ["10,000,000 shares at $21.00 each.", "The shares rose 35% after the listing."]
    assert pts[1]["news"] == [0]                    # 35% is in the news item it cites; uncited, the same claim goes


def test_context_is_added_to_an_analysis_read_by_rules(fake_ai, monkeypatch):
    fake_ai(ANSWER)
    a = pipeline.run({"kind": "upload", "data": S1, "name": "s1.htm", "lang": "en"}, lambda *_: None)
    assert not a["ai"] and a["reading"] is None and a["facts"]           # read by rules, no AI involved
    assert not fake_ai.prompts
    a = pipeline.add_context(a["id"], "Is the IPO priced too high?", True, lambda *_: None)
    prompt, web = fake_ai.prompts[0]
    assert web and "<notes>\nIs the IPO priced too high?\n</notes>" in prompt and '<page n="3">' in prompt
    assert "3,400" in prompt and "search the web" in prompt
    assert a["ai"] and a["ai_provider"] == "Anthropic (Claude)" and a["reading"]["notes"] == "Is the IPO priced too high?"
    assert pipeline.load(a["id"])["reading"]["news"][0]["url"] == NEWS[0]["url"]          # stored with the analysis
    from analyst import pptx_report, xlsx_export
    pdf = pdfreport.build(a)
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(pdf)
    text = "".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
    assert "AI context" in text and "Latest news" in text and "Lumen Labs prices its IPO" in text
    assert b"news.example.com/lumen-ipo" in pdf                                      # the news item links to its source
    assert pptx_report.build(a)[:2] == b"PK" and xlsx_export.build(a)[:2] == b"PK"


def test_context_without_web_search_has_no_news(fake_ai, monkeypatch):
    fake_ai(ANSWER)
    monkeypatch.setattr(ai, "active", lambda: ("mistral", "k", "m"))
    a = pipeline.run({"kind": "upload", "data": S1, "name": "s1.htm", "lang": "en"}, lambda *_: None)
    a = pipeline.add_context(a["id"], "", True, lambda *_: None)
    prompt, web = fake_ai.prompts[0]
    assert not web and "cannot search the web" in prompt and "<notes>" not in prompt
    assert a["reading"]["news"] == [] and a["reading"]["web"] is False
    assert all(not p["news"] for s in a["reading"]["sections"] for p in s["points"])


def test_claude_api_web_search_resumes_a_paused_turn(monkeypatch):
    """The Claude API with its web search tool: a paused turn is resumed, the result addresses are collected."""
    from types import SimpleNamespace as NS
    calls = []

    class Stream:
        def __init__(self, resp): self.resp = resp
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get_final_message(self): return self.resp

    def stream(**kw):
        calls.append(kw)
        if len(calls) == 1:
            return Stream(NS(stop_reason="pause_turn", content=[
                NS(type="server_tool_use", citations=None),
                NS(type="web_search_tool_result", citations=None, content=[NS(url="https://news.example.com/a")])]))
        return Stream(NS(stop_reason="end_turn", content=[
            NS(type="text", text='{"doc_type": "x", ', citations=None),
            NS(type="text", text='"summary": "", "sections": [], "news": []}', citations=[NS(url="https://news.example.com/b")])]))

    class Client:
        def __init__(self, **kw): self.beta = NS(messages=NS(stream=stream))
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", Client)
    out = ai._call_anthropic("sk", "claude-test", "sys", "prompt", reader.CONTEXT_SCHEMA, 32000, web=True)
    assert out["_search_urls"] == ["https://news.example.com/a", "https://news.example.com/b"]
    assert calls[0]["tools"][0]["name"] == "web_search" and "format" not in calls[0]["output_config"]
    assert len(calls[1]["messages"]) == 2 and calls[1]["messages"][1]["role"] == "assistant"   # the paused turn is resumed


def test_page_choice_fits_the_budget():
    texts = ["Cover"] + ["filler text " * 900] * 60 + ["PROSPECTUS SUMMARY revenue 1,000 net income 200 " * 20]
    picked = reader.choose_pages(texts)
    assert picked[0] == 0 and len(texts) - 1 in picked
    assert sum(min(len(texts[i]), reader.PAGE_CAP) for i in picked) <= reader.CHAR_BUDGET


# ---------------------------------------------------------------- subscriptions through the official CLIs

@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ai, "AI_FILE", tmp_path / "ai.json")
    monkeypatch.setattr(ai, "LEGACY_KEY_FILE", tmp_path / "anthropic_key")
    for p in ai.PROVIDERS.values():
        for v in p["env"]:
            monkeypatch.delenv(v, raising=False)
    return tmp_path


def fake_tool(d: Path, name: str, body: str):
    p = d / name
    p.write_text(f"#!{sys.executable}\nimport json, sys\n{body}\n")
    p.chmod(0o755)


@pytest.mark.skipif(os.name == "nt", reason="fake tools are POSIX scripts")
def test_claude_subscription_via_claude_code(cfg, tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    fake_tool(bin_, "claude", """
a = sys.argv[1:]
assert a[0] == "-p" and "--json-schema" in a and "--no-session-persistence" in a and "--strict-mcp-config" in a
prompt = sys.stdin.read()
if '{"ok": true}' in prompt:                # the connection test
    assert a[a.index("--tools") + 1] == "" and "--allowedTools" not in a
    out = {"ok": True}
else:                                   # context with news: only its web search and web fetch, allowed without asking
    assert a[a.index("--tools") + 1] == "WebSearch,WebFetch" == a[a.index("--allowedTools") + 1]
    out = {"doc_type": "x", "summary": "Fine.", "sections": [], "news": []}
print(json.dumps({"type": "result", "is_error": False, "result": "", "structured_output": out}))""")
    monkeypatch.setenv("PATH", str(bin_))
    monkeypatch.setattr(ai.Path, "home", lambda: tmp_path)
    assert ai.active() is None
    ai.save_settings("claude_code")
    assert ai.active() == ("claude_code", "", "") and ai.test() == "Claude subscription (via Claude Code)"
    assert ai.can_search() and reader.contextualize("Doc", {}, 0, {}, web=True)["summary"] == "Fine."


@pytest.mark.skipif(os.name == "nt", reason="fake tools are POSIX scripts")
def test_chatgpt_subscription_via_codex(cfg, tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    fake_tool(bin_, "codex", """
a = sys.argv[1:]
assert a[0] == "exec" and a[a.index("--sandbox") + 1] == "read-only" and a[-1] == "-"
json.load(open(a[a.index("--output-schema") + 1]))
if '{"ok": true}' in sys.stdin.read():      # the connection test
    assert "web_search=\\"live\\"" not in a
    out = {"ok": True}
else:                                   # context with news: live web search
    assert a[a.index("-c") + 1] == 'web_search="live"'
    out = {"doc_type": "x", "summary": "Fine.", "sections": [], "news": []}
open(a[a.index("-o") + 1], "w").write(json.dumps(out))""")
    monkeypatch.setenv("PATH", str(bin_))
    monkeypatch.setattr(ai.Path, "home", lambda: tmp_path)
    ai.save_settings("codex")
    assert ai.test() == "ChatGPT subscription (via Codex)"
    assert reader.contextualize("Doc", {}, 0, {}, web=True)["web"] is True


def test_subscription_not_installed_is_not_used(cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(ai.Path, "home", lambda: tmp_path)
    ai.save_settings("claude_code")
    assert ai.active() is None
    ai.save_settings("openai", "sk-test-abcdefghij")
    assert ai.active()[0] == "openai"


def test_server_reads_without_ai_and_asks_for_one_only_for_the_context(monkeypatch):
    import server
    client = TestClient(server.app, base_url="http://127.0.0.1:8765")
    monkeypatch.setattr(ai, "active", lambda: None)
    started = []
    monkeypatch.setattr(server, "_start", lambda req: started.append(req) or "job1")
    assert client.post("/api/analyze", json={"kind": "sec", "query": "MSFT"}).json() == {"job": "job1"}
    assert client.post("/api/upload", files={"file": ("a.pdf", b"%PDF-1.4")}).json() == {"job": "job1"}
    assert all("ai" not in r for r in started)
    st = client.get("/api/status").json()
    assert st["ai"] is False and st["ai_web"] is False
    monkeypatch.setattr(pipeline, "load", lambda aid: {"id": aid})
    r = client.post("/api/context", json={"id": "0123456789abcdef", "notes": "x"})
    assert r.status_code == 409 and "AI" in r.json()["detail"]
    monkeypatch.setattr(ai, "active", lambda: ("openai", "k", "m"))
    assert client.post("/api/context", json={"id": "0123456789abcdef", "notes": " why? ", "web": False}).json() == {"job": "job1"}
    assert started[-1] == {"kind": "context", "id": "0123456789abcdef", "notes": "why?", "web": False}
    assert client.post("/api/context", json={"id": "../etc"}).status_code == 400
