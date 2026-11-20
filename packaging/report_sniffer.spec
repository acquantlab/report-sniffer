# PyInstaller recipe for the desktop app:   pyinstaller --noconfirm packaging/report_sniffer.spec
# Output: dist/ReportSniffer/ (Windows, Linux) or "dist/Report Sniffer.app" (macOS).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent
# the app icon (drawn in packaging/icon.svg): the .ico on Windows, the PNG elsewhere (converted to .icns on macOS by
# PyInstaller, with Pillow); the PNG is also the window icon on Linux
PNG = str(ROOT / "packaging" / "icon.png")
ICON = str(ROOT / "packaging" / "icon.ico") if sys.platform == "win32" else PNG

# the web interface, the translations, the fonts of the PDF report (Latin, Greek, Cyrillic, Chinese, Japanese, Korean),
# the window icon and the version (checked against the releases by updater.py)
datas, binaries, hidden = [(str(ROOT / "web"), "web"), (str(ROOT / "analyst" / "locales"), "analyst/locales"),
                           (str(ROOT / "analyst" / "fonts"), "analyst/fonts"), (PNG, "packaging"), (str(ROOT / "VERSION"), ".")], [], \
    ["server", "launch", "desktop", "updater"]
# the app's window (pywebview picks its toolkit at run time): Edge WebView2 through pythonnet on Windows, WebKit
# through PyObjC on macOS, Qt WebEngine on Linux
if sys.platform == "win32":
    hidden += ["webview.platforms.winforms", "webview.platforms.edgechromium", "clr"]
elif sys.platform == "darwin":
    hidden += ["webview.platforms.cocoa"]
else:
    hidden += ["webview.platforms.qt", "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebEngineCore", "PyQt6.QtWebChannel"]
# OCR: rapidocr with its models and settings, ONNX Runtime's native library, OpenCV (cv2 has its own hook)
for pkg in ("uvicorn", "curl_cffi", "pypdfium2", "pypdfium2_raw", "pptx", "reportlab", "anthropic", "rapidocr", "onnxruntime", "omegaconf"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden += h

a = Analysis([str(ROOT / "app.py")], pathex=[str(ROOT)], datas=datas, binaries=binaries, hiddenimports=hidden,
             excludes=["tkinter", "pytest", "PyQt5", "PySide2", "PySide6", "gi"])
if sys.platform.startswith("linux"):
    # the window needs Qt WebEngine and Qt Widgets only: no QML, 3D, multimedia or control styles, and only
    # Chromium's own locale files among the translations (about 60% of the size of Qt)
    import re
    drop = re.compile(r"PyQt6/Qt6/(qml/|translations/(?!qtwebengine_locales/)|lib/libQt6(Quick3D|QuickControls2|QuickDialogs2|"
                      r"QuickTemplates2|QuickParticles|QuickShapes|QuickTimeline|QuickLayouts|QuickVectorImage|Labs|Multimedia|"
                      r"SpatialAudio|ShaderTools|Sensors|TextToSpeech|RemoteObjects|Test|WebSockets|Pdf|3D|Charts|Graphs))")
    a.binaries = [x for x in a.binaries if not drop.search(x[0].replace("\\", "/"))]
    a.datas = [x for x in a.datas if not drop.search(x[0].replace("\\", "/"))]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, exclude_binaries=True, name="ReportSniffer", console=False, icon=ICON)
coll = COLLECT(exe, a.binaries, a.datas, name="ReportSniffer")
if sys.platform == "darwin":
    # a regular app: its own window, Dock icon and menu bar
    app = BUNDLE(coll, name="Report Sniffer.app", icon=ICON, bundle_identifier="com.acquantlab.reportsniffer",
                 info_plist={"CFBundleDisplayName": "Report Sniffer", "NSHighResolutionCapable": True})
