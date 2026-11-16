"""Report Sniffer as a desktop app: the entry point of the packaged builds (packaging/report_sniffer.spec).

Starts the local server inside this process and opens it in a Chromium-based browser. There is no
terminal window: the app stops from "Quit" in the bottom bar of its home page, and what it would
print goes to ~/.report-sniffer/app.log. Starting it again while it runs just opens the page.

    --no-browser   start the server only
    --selftest     check that everything the builds must contain is there, then exit
"""
import os
import sys
import threading
import time
from pathlib import Path

HOME = Path.home() / ".report-sniffer"


def selftest():
    import anthropic  # noqa: F401
    import curl_cffi  # noqa: F401
    import lxml.etree  # noqa: F401
    import pypdfium2  # noqa: F401
    import xlsxwriter  # noqa: F401
    from pptx import Presentation
    from reportlab.pdfgen import canvas

    import server
    from analyst import generic, pdfreport, pptx_report, reader, xlsx_export  # noqa: F401
    Presentation()                                         # needs the template bundled with python-pptx
    canvas.Canvas(os.devnull).save()
    missing = [n for n in ("index.html", "app.js", "app.css", "sniffer.js", "themes.js") if not (server.WEB / n).exists()]
    if missing:
        raise SystemExit("missing web files: %s" % ", ".join(missing))
    from analyst import typefaces
    c = canvas.Canvas(os.devnull)                          # every font of the PDF report is bundled and loads
    typefaces.draw(c, 10, 10, "Report Ελληνικά Россия 日本語 中文 한국어", typefaces.SANS, 10)
    if [f for f, _ in typefaces.runs("Ελ 日本 한국")] != ["", "RS-CJK", "RS-Hangul"]:
        raise SystemExit("fonts of the PDF report: unexpected coverage")
    c.save()
    print("selftest ok")
    return 0


def main():
    import launch
    HOME.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("SNIFFER_DATA_DIR", str(HOME / "data"))     # the app folder itself may be read-only
    if getattr(sys, "frozen", False):
        sys.stdout = sys.stderr = open(HOME / "app.log", "a", buffering=1, encoding="utf-8")
    if "--selftest" in sys.argv:
        return selftest()
    no_browser = "--no-browser" in sys.argv
    if launch.server_up():
        if not no_browser:
            launch.open_browser()
        return 0

    def open_when_up():
        for _ in range(240):
            if launch.server_up():
                return launch.open_browser()
            time.sleep(0.25)

    if not no_browser:
        threading.Thread(target=open_when_up, daemon=True).start()
    import uvicorn

    import server
    uvicorn.run(server.app, host="127.0.0.1", port=server.PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
