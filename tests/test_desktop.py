"""The app's window: the names of saved files, and what the page may ask it to save."""
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import desktop  # noqa: E402


def test_file_names_from_the_download_header():
    assert desktop.filename('attachment; filename="Societe-report-fr.pdf"; filename*=UTF-8\'\'Soci%C3%A9t%C3%A9-report-fr.pdf') == "Société-report-fr.pdf"
    assert desktop.filename('attachment; filename="acme-data-en.xlsx"') == "acme-data-en.xlsx"
    assert desktop.filename("attachment; filename*=UTF-8''..%2F..%2Fetc%2Fpasswd") == "passwd"      # a plain name, no folders
    assert desktop.filename("") == "report"


def test_save_fetches_from_the_app_and_writes_where_the_user_chose(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/doc/x/report.pdf"):
                self.send_response(200)
                self.send_header("Content-Disposition", 'attachment; filename="acme-report-en.pdf"')
                self.end_headers()
                self.wfile.write(b"%PDF-1.7 test")
            else:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"detail": "analysis not found"}')

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    asked = []

    class Window:
        def create_file_dialog(self, kind, directory="", save_filename=""):
            asked.append(save_filename)
            return str(tmp_path / save_filename)
    b = desktop.Bridge(f"http://127.0.0.1:{srv.server_port}/")
    b._window = Window()
    try:
        import webview  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("pywebview not installed")
    assert b.save("/api/doc/x/report.pdf?theme=paper") == {"path": str(tmp_path / "acme-report-en.pdf")}
    assert (tmp_path / "acme-report-en.pdf").read_bytes() == b"%PDF-1.7 test" and asked == ["acme-report-en.pdf"]
    assert b.save("/api/doc/y/report.pdf") == {"error": "analysis not found"}
    assert b.save("https://example.com/x") == {"error": "invalid request"}            # only the app's own files
    srv.shutdown()
