# PyInstaller recipe for the desktop app:   pyinstaller --noconfirm packaging/report_sniffer.spec
# Output: dist/ReportSniffer/ (Windows, Linux) or "dist/Report Sniffer.app" (macOS).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent
ICON = str(ROOT / "packaging" / "icon.png")          # converted to .ico / .icns by PyInstaller (needs Pillow)

# the web interface, and the fonts of the PDF report (Latin, Greek, Cyrillic, Chinese, Japanese, Korean)
datas, binaries, hidden = [(str(ROOT / "web"), "web"), (str(ROOT / "analyst" / "fonts"), "analyst/fonts")], [], ["server", "launch"]
for pkg in ("uvicorn", "curl_cffi", "pypdfium2", "pypdfium2_raw", "pptx", "reportlab", "anthropic"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden += h

a = Analysis([str(ROOT / "app.py")], pathex=[str(ROOT)], datas=datas, binaries=binaries, hiddenimports=hidden,
             excludes=["tkinter", "pytest"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, exclude_binaries=True, name="ReportSniffer", console=False, icon=ICON)
coll = COLLECT(exe, a.binaries, a.datas, name="ReportSniffer")
if sys.platform == "darwin":
    # no Dock icon: the app is a local server whose window is a browser tab
    app = BUNDLE(coll, name="Report Sniffer.app", icon=ICON, bundle_identifier="com.acquantlab.reportsniffer",
                 info_plist={"LSUIElement": True, "CFBundleDisplayName": "Report Sniffer", "NSHighResolutionCapable": True})
