"""Report Sniffer as a desktop app: the entry point of the downloadable builds (packaging/report_sniffer.spec) and of
launch.py when it runs from the source.

Starts the local server inside this process and shows it in the app's own window (desktop.py); closing the window
quits. Where no window can be shown (no web view on the system) the page opens in a browser as before, and the app
stops from "Quit" in the bottom bar of its home page. What the downloadable app would print goes to
~/.report-sniffer/app.log. Starting it again while it runs opens one more window on it.

    --no-window    start the server only (also --no-browser)
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
    import desktop  # noqa: F401
    import webview  # noqa: F401
    gui = {"win32": "winforms", "darwin": "cocoa"}.get(sys.platform, "qt")
    if getattr(sys, "frozen", False):              # the window's toolkit is bundled (from the source it may be GTK)
        __import__(f"webview.platforms.{gui}")
    missing = [n for n in ("index.html", "app.js", "app.css", "sniffer.js", "themes.js", "i18n.js") if not (server.WEB / n).exists()]
    if missing:
        raise SystemExit("missing web files: %s" % ", ".join(missing))
    from analyst import typefaces
    c = canvas.Canvas(os.devnull)                          # every font of the PDF report is bundled and loads
    typefaces.draw(c, 10, 10, "Report Ελληνικά Россия 日本語 中文 한국어", typefaces.SANS, 10)
    if [f for f, _ in typefaces.runs("Ελ 日本 한국")] != ["", "RS-CJK", "RS-Hangul"]:
        raise SystemExit("fonts of the PDF report: unexpected coverage")
    c.save()
    from analyst import i18n                               # every language's translations are bundled
    short = [code for code in i18n.LANGS if code not in ("it", "en") and len(i18n.catalog(code)) < 300]
    if short:
        raise SystemExit("translations missing: %s" % ", ".join(short))
    print("selftest ok")
    return 0


def main():
    import launch
    HOME.mkdir(parents=True, exist_ok=True)
    if getattr(sys, "frozen", False):
        os.environ.setdefault("SNIFFER_DATA_DIR", str(HOME / "data"))     # the app folder itself may be read-only
        sys.stdout = sys.stderr = open(HOME / "app.log", "a", buffering=1, encoding="utf-8")
    if "--selftest" in sys.argv:
        return selftest()
    import desktop
    headless = "--no-window" in sys.argv or "--no-browser" in sys.argv
    if launch.server_up():                         # already running: one more window on it
        if not headless and not desktop.open_window(launch.URL):
            launch.open_browser()
        return 0

    import uvicorn

    import server
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=server.PORT, log_level="warning"))
    if headless:
        srv.run()
        return 0
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(240):
        if launch.server_up():
            break
        if not thread.is_alive():
            print(f"the server did not start (is port {server.PORT} in use? set SNIFFER_PORT to change it)", file=sys.stderr)
            return 1
        time.sleep(0.25)
    os.environ["SNIFFER_WINDOW"] = "1"             # the page knows it is in the app's window (server.index)
    if desktop.open_window(launch.URL):            # until the window is closed
        sys.stdout.flush()
        os._exit(0)                                # analyses still running stop with it
    os.environ["SNIFFER_WINDOW"] = ""
    launch.open_browser()                          # no window on this system: a browser tab, stopped from Quit
    thread.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())
