"""AI providers (simulated HTTP), documents read without an AI, and the PDF export."""
import json
import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from analyst import ai, pipeline  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ai, "AI_FILE", tmp_path / "ai.json")
    monkeypatch.setattr(ai, "LEGACY_KEY_FILE", tmp_path / "anthropic_key")
    for p in ai.PROVIDERS.values():
        for v in p["env"]:
            monkeypatch.delenv(v, raising=False)
    return tmp_path


def test_settings_and_active_provider(cfg, monkeypatch):
    assert ai.active() is None and not ai.available()
    ai.save_settings("openrouter", "sk-or-test-1234567890", "")
    assert ai.active() == ("openrouter", "sk-or-test-1234567890", "openrouter/auto")
    ai.save_settings("openai", "sk-test-abcdefghij", "gpt-test")
    assert ai.active() == ("openai", "sk-test-abcdefghij", "gpt-test")
    assert oct(os.stat(cfg / "ai.json").st_mode)[-3:] == "600" or os.name == "nt"
    ai.save_settings("openai", remove=True)
    assert ai.active()[0] == "openrouter"                      # falls back to another saved key
    monkeypatch.setenv("MISTRAL_API_KEY", "env-key-123456")
    assert {p["id"]: p["has_key"] for p in ai.status()["providers"]}["mistral"]


def test_openai_compatible_call_is_validated(cfg, monkeypatch):
    from analyst import reader
    ai.save_settings("openrouter", "sk-or-test-1234567890", "")
    assert ai.available() and not ai.can_search()             # context, but no live news through this provider
    sent = {}

    def fake_post(url, headers, json, timeout):
        sent.update(url=url, headers=headers, body=json)
        content = ('```json\n{"doc_type": "10-K", "summary": "Revenue reached $120B, up 20.0%. Margins will double to 99%.",'
                   ' "sections": [], "news": [{"title": "Invented", "source": "x", "url": "https://example.com/n", "date": "", "summary": ""}]}\n```')
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    monkeypatch.setattr(ai.httpx, "post", fake_post)
    figures = {"revenue_cur": {"label": "Revenue", "display": "$120B", "pages": [3]},
               "growth_revenue": {"label": "Revenue growth", "display": "+20.0%", "pages": [3]}}
    r = reader.contextualize("Example", {}, 0, figures, web=True)
    assert sent["url"] == "https://openrouter.ai/api/v1/chat/completions" and sent["body"]["model"] == "openrouter/auto"
    assert sent["headers"]["Authorization"] == "Bearer sk-or-test-1234567890"
    assert "cannot search the web" in sent["body"]["messages"][1]["content"] and r["web"] is False
    assert r["summary"] == "Revenue reached $120B, up 20.0%."           # the invented 99% is dropped
    assert r["news"] == []                                          # not searched: no "news" from the model's memory


def test_documents_are_read_without_ai_and_context_errors_are_shown(cfg, monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "DOCS", tmp_path / "docs")
    import make_fixtures
    FIX.mkdir(exist_ok=True)
    (FIX / "sec_10k.htm").write_text(make_fixtures.sec(), encoding="utf-8")
    a = pipeline.run({"kind": "upload", "data": (FIX / "sec_10k.htm").read_bytes(), "name": "x.htm", "lang": "en"}, lambda *_: None)
    assert not ai.available() and not a["ai"] and a["reading"] is None and a["findings"] and a["card"]
    from analyst import sources
    with pytest.raises(sources.SourceError, match="Set up the AI"):
        pipeline.add_context(a["id"], "", True, lambda *_: None)
    ai.save_settings("openai", "sk-bad-key-1234567", "")
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: httpx.Response(401, json={"error": {"message": "Incorrect API key"}}))
    with pytest.raises(sources.SourceError, match="Incorrect API key"):
        pipeline.add_context(a["id"], "", True, lambda *_: None)
    assert pipeline.load(a["id"])["reading"] is None


def test_pdf_report(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "DOCS", tmp_path / "docs")
    import make_fixtures
    FIX.mkdir(exist_ok=True)
    (FIX / "sec_10k.htm").write_text(make_fixtures.sec(), encoding="utf-8")
    from analyst import pdfreport
    for lang in ("en", "it"):
        a = pipeline.run({"kind": "upload", "data": (FIX / "sec_10k.htm").read_bytes(), "name": "x.htm", "lang": lang}, lambda *_: None)
        pdf = pdfreport.build(json.loads(json.dumps(a)))           # as stored on disk (string keys)
        assert pdf.startswith(b"%PDF") and len(pdf) > 3000
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(pdf)
        text = "".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
        assert ("Key findings" if lang == "en" else "Osservazioni chiave") in text
        assert ("$120B" if lang == "en" else "$120 mld") in text and "EXAMPLE CORP" in text
