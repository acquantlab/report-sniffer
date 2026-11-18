"""The app's own window: the local page in the system's web view, as a desktop app instead of a browser tab.

Windows: Microsoft Edge WebView2 (part of Windows 10/11); macOS: WebKit (the engine of Safari); Linux: Qt WebEngine
(bundled with the downloadable app) or WebKitGTK. Closing the window quits the app. Files the page saves (reports,
original documents) go through the system's Save dialog (Bridge.save).

open_window() returns False when this system cannot show the window (no web view, no display): the caller then
opens the page in a browser, as before.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote

HOME = Path.home() / ".report-sniffer"
ICON = Path(__file__).resolve().parent / "packaging" / "icon.png"
_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))        # 127.0.0.1 never goes through a proxy


def filename(disposition: str, fallback: str = "report") -> str:
    """The file name a download offers (Content-Disposition), reduced to a plain name."""
    m = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.I)
    name = unquote(m.group(1)) if m else (re.search(r'filename="([^"]+)"', disposition) or [None, ""])[1]
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", Path(name or "").name).strip(". ")
    return name or fallback


def downloads_folder() -> Path:
    d = Path.home() / "Downloads"
    return d if d.is_dir() else Path.home()


class Bridge:
    """Called from the page as window.pywebview.api.<method> (names starting with _ are not exposed)."""

    def __init__(self, base: str):
        self._base = base.rstrip("/")
        self._window = None

    def save(self, path: str) -> dict:
        """Fetches a file the server makes (path: /api/...) and saves it where the user chooses."""
        if not isinstance(path, str) or not path.startswith("/api/"):
            return {"error": "invalid request"}
        try:
            with _LOCAL.open(self._base + path, timeout=900) as r:
                data, disposition = r.read(), r.headers.get("Content-Disposition", "")
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read()).get("detail")
            except (ValueError, AttributeError):
                detail = None
            return {"error": str(detail or f"HTTP {e.code}")}
        except OSError as e:
            return {"error": str(e)}
        import webview
        chosen = self._window.create_file_dialog(webview.FileDialog.SAVE, directory=str(downloads_folder()),
                                                 save_filename=filename(disposition))
        if not chosen:
            return {"cancelled": True}
        target = Path(chosen if isinstance(chosen, str) else chosen[0])
        try:
            target.write_bytes(data)
        except OSError as e:
            return {"error": str(e)}
        return {"path": str(target)}


def _linux_ok() -> bool:
    """A display to open the window on. With Qt on X11 its xcb plugin must load: it needs system libraries
    (xcb-cursor, xkbcommon-x11...) that minimal systems lack, and without them Qt aborts the whole process."""
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    try:
        import gi  # noqa: F401  (WebKitGTK through PyGObject: pywebview prefers it)
        return True
    except ImportError:
        pass
    os.environ.setdefault("PYWEBVIEW_GUI", "qt")          # no GTK bindings: straight to Qt
    try:
        # Ubuntu 24.04 and later forbid the user namespaces Chromium's sandbox needs to programs without an
        # AppArmor profile, and Chromium refuses to sandbox as root: Qt WebEngine would not start. The page is the
        # app's own, local one; documents are shown sanitised, without scripts.
        restricted = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns").read_text().strip() == "1"
    except OSError:
        restricted = False
    if restricted or os.geteuid() == 0:
        os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("QT_QPA_PLATFORM"):
        return True
    import ctypes
    try:
        import PyQt6
        ctypes.CDLL(str(Path(PyQt6.__file__).parent / "Qt6" / "plugins" / "platforms" / "libqxcb.so"))
        return True
    except (ImportError, OSError) as e:
        print(f"window: Qt cannot use this display: {e}", file=sys.stderr)
        return False


def open_window(url: str, title: str = "Report Sniffer") -> bool:
    """Shows the page in the app's own window until it is closed. False if no window can be shown here."""
    try:
        import webview
    except Exception as e:  # not installed, or its GUI bindings are missing
        print(f"window: {type(e).__name__}: {e}", file=sys.stderr)
        return False
    if sys.platform.startswith("linux") and not _linux_ok():
        print("window: no display or web view on this system", file=sys.stderr)
        return False
    if sys.platform == "win32":
        try:
            from webview.platforms import winforms
        except Exception as e:
            print(f"window: {type(e).__name__}: {e}", file=sys.stderr)
            return False
        if winforms.renderer != "edgechromium":       # without WebView2 the fallback is Internet Explorer: no
            print("window: Microsoft Edge WebView2 is not installed", file=sys.stderr)
            return False
    bridge = Bridge(url)
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
        win = webview.create_window(title, url, js_api=bridge, width=1440, height=920, min_size=(960, 640),
                                    background_color="#000000", text_select=True, zoomable=True)
        bridge._window = win
        HOME.mkdir(parents=True, exist_ok=True)
        # cookies and local storage kept (interface language, theme)
        webview.start(private_mode=False, storage_path=str(HOME / "webview"), icon=str(ICON) if ICON.exists() else None)
    except Exception as e:
        print(f"window: {type(e).__name__}: {e}", file=sys.stderr)
        return False
    return True
