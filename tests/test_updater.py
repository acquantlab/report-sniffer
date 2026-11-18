"""Updates from the GitHub releases: which release is newer, what this copy may install, and the install itself
(download, digest, unpacking, the new version's selftest, the swap done by the helper script) on a fake app."""
import hashlib
import io
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import updater  # noqa: E402

POSIX = pytest.mark.skipif(os.name == "nt", reason="the fake app and its helper are POSIX scripts")
STEPS = {k: k for k in ("download", "check", "restart", "none", "manual", "corrupt", "broken")}


def test_versions_and_builds(monkeypatch):
    assert updater.parse("v2.10.0") > updater.parse("2.9.3") and updater.parse("dev") is None
    assert updater.parse(updater.current())                     # the VERSION file of this checkout
    monkeypatch.setattr(updater.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(updater.sys, "platform", "darwin")
    assert updater.asset_name() == "ReportSniffer-macos-arm64.zip"
    monkeypatch.setattr(updater.platform, "machine", lambda: "x86_64")
    assert updater.asset_name() is None                         # Intel Macs: no build, the release page instead
    monkeypatch.setattr(updater.sys, "platform", "linux")
    assert updater.asset_name() == "ReportSniffer-linux-x64.tar.gz"


def fake_app(root: Path, marker: Path, ok: bool = True) -> Path:
    """A ReportSniffer folder whose program passes (or fails) --selftest and, started normally, writes marker."""
    app = root / "ReportSniffer"
    app.mkdir(parents=True)
    exe = app / "ReportSniffer"
    exe.write_text(f'#!/bin/sh\nif [ "$1" = "--selftest" ]; then exit {0 if ok else 1}; fi\necho started > "{marker}"\n')
    exe.chmod(0o755)
    return app


def release(tmp_path: Path, marker: Path, ok: bool = True, tamper: bool = False) -> tuple[bytes, dict]:
    build = tmp_path / "build"
    fake_app(build, marker, ok)
    (build / "ReportSniffer" / "VERSION").write_text("2.1.0\n")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        tf.add(build / "ReportSniffer", arcname="ReportSniffer")
    data = buf.getvalue()
    digest = hashlib.sha256(data + (b"x" if tamper else b"")).hexdigest()
    asset = {"name": "ReportSniffer-linux-x64.tar.gz", "size": len(data), "digest": f"sha256:{digest}",
             "browser_download_url": updater.DOWNLOADS + "v2.1.0/ReportSniffer-linux-x64.tar.gz"}
    return data, {"tag_name": "v2.1.0", "html_url": "https://github.com/acquantlab/report-sniffer/releases/tag/v2.1.0",
                  "assets": [asset]}


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """This process pretends to be the downloadable app installed in tmp/apps/ReportSniffer, version 2.0.0."""
    marker = tmp_path / "started-old"
    app = fake_app(tmp_path / "apps", marker)
    (app / "VERSION").write_text("2.0.0\n")
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater.sys, "executable", str(app / "ReportSniffer"))
    monkeypatch.setattr(updater.sys, "platform", "linux")
    monkeypatch.setattr(updater.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(updater, "current", lambda: "2.0.0")
    monkeypatch.setattr(updater, "_cache", {"t": 0.0, "info": None})
    return app


def serve(monkeypatch, rel: dict, data: bytes):
    monkeypatch.setattr(updater.httpx, "get", lambda url, **k: httpx.Response(200, json=rel, request=httpx.Request("GET", url)))

    class Stream:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def raise_for_status(self): pass
        def iter_bytes(self, n): return (data[i:i + n] for i in range(0, len(data), n))
    monkeypatch.setattr(updater.httpx, "stream", Stream)


@POSIX
def test_check_says_what_this_copy_can_install(installed, tmp_path, monkeypatch):
    data, rel = release(tmp_path, tmp_path / "m")
    serve(monkeypatch, rel, data)
    info = updater.check()
    assert updater.public(info) == {"current": "2.0.0", "latest": "2.1.0", "newer": True, "url": rel["html_url"],
                                    "can_install": True, "why": "", "size": len(data)}
    rel["assets"][0]["browser_download_url"] = "https://example.com/ReportSniffer-linux-x64.tar.gz"   # not GitHub's
    assert updater.check(force=True)["why"] == "no_build"
    monkeypatch.setattr(updater.sys, "frozen", False)
    assert updater.check(force=True)["why"] == "source"
    monkeypatch.setattr(updater.httpx, "get", lambda url, **k: (_ for _ in ()).throw(httpx.ConnectError("offline")))
    assert "offline" in updater.check(force=True)["error"]


@POSIX
def test_install_swaps_the_new_version_in_and_starts_it(installed, tmp_path, monkeypatch):
    marker = tmp_path / "started-new"
    data, rel = release(tmp_path, marker)
    serve(monkeypatch, rel, data)
    staged = {}
    monkeypatch.setattr(updater, "_start_helper", lambda target, new, work: staged.update(target=target, new=new, work=work))
    steps = []
    updater.install(lambda s, p: steps.append(s), STEPS)
    assert staged["new"].is_dir() and (staged["new"] / "VERSION").read_text() == "2.1.0\n"
    assert (installed / "VERSION").read_text() == "2.0.0\n"            # nothing replaced while the app runs
    assert steps[0] == "download" and steps[-1] == "restart"
    # the helper, once the app (here: a process that already ended) has quit
    done = subprocess.Popen(["true"])
    done.wait()
    suffix, script = updater.helper_script(done.pid, staged["target"], staged["new"], staged["work"])
    path = tmp_path / f"helper{suffix}"
    path.write_text(script)
    subprocess.run(["/bin/sh", str(path)], check=True, timeout=60)
    for _ in range(50):
        if marker.exists():
            break
        time.sleep(0.1)
    assert (installed / "VERSION").read_text() == "2.1.0\n" and marker.read_text().strip() == "started"
    assert not installed.with_name("ReportSniffer.old").exists() and not staged["work"].exists() and not path.exists()


@POSIX
def test_a_bad_download_or_a_broken_build_changes_nothing(installed, tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "_start_helper", lambda *a: pytest.fail("the helper must not start"))
    for kw, err in (({"tamper": True}, "corrupt"), ({"ok": False}, "broken")):
        data, rel = release(tmp_path / err, tmp_path / "m", **kw)
        serve(monkeypatch, rel, data)
        with pytest.raises(updater.UpdateError, match=err):
            updater.install(lambda s, p: None, STEPS)
        assert (installed / "VERSION").read_text() == "2.0.0\n"
        assert not (installed.parent / ".report-sniffer-update").exists()


def test_the_page_asks_the_server(monkeypatch):
    from fastapi.testclient import TestClient
    import server
    monkeypatch.setattr(updater, "check", lambda force=False: {"current": "2.0.0", "latest": "2.1.0", "newer": True,
                                                               "url": "u", "can_install": False, "why": "source", "size": 1, "_asset": {}})
    c = TestClient(server.app, base_url="http://127.0.0.1:8765")
    assert c.get("/api/update").json() == {"current": "2.0.0", "latest": "2.1.0", "newer": True, "url": "u",
                                           "can_install": False, "why": "source", "size": 1}
    assert c.get("/api/status").json()["version"] == updater.current()
    assert c.post("/api/update", content=b"x", headers={"content-type": "text/plain"}).status_code == 415
