"""Updates: the app checks its GitHub releases and, on request, installs the new version over itself.

check()   the latest release (cached for a few hours): its version, its page, and whether this copy can install it
install() downloads the archive for this system, checks it against the SHA-256 digest GitHub publishes for it,
          unpacks it next to the installed app, runs the new version's --selftest, then starts a small helper
          script and returns; the caller then quits. The helper waits for the app to exit, renames the old
          version aside, moves the new one in its place, starts it and deletes the old one. If anything fails
          before the swap, nothing is changed; if the swap fails, the old version is put back.

Only the downloadable app installs updates (a copy run from the source shows the release page instead), and only
where it may write: not from a read-only folder such as a macOS app that was never moved to Applications.
"""
from __future__ import annotations

import hashlib
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional

import httpx

REPO = "acquantlab/report-sniffer"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOADS = f"https://github.com/{REPO}/releases/download/"
RELEASES = f"https://github.com/{REPO}/releases/latest"
TTL = 6 * 3600
MAX_BYTES = 800_000_000
_cache: dict = {"t": 0.0, "info": None}


def current() -> str:
    """This copy's version, from the VERSION file (bundled with the downloadable app)."""
    try:
        return (Path(__file__).resolve().parent / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def parse(v: str) -> Optional[tuple[int, ...]]:
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (v or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def asset_name() -> Optional[str]:
    """The release file for this system (the builds: Windows x64, macOS Apple silicon, Linux x64)."""
    machine = platform.machine().lower()
    if sys.platform == "win32" and machine in ("amd64", "x86_64"):
        return "ReportSniffer-windows-x64.zip"
    if sys.platform == "darwin" and machine == "arm64":
        return "ReportSniffer-macos-arm64.zip"
    if sys.platform.startswith("linux") and machine in ("x86_64", "amd64"):
        return "ReportSniffer-linux-x64.tar.gz"
    return None


def install_dir() -> Optional[Path]:
    """The installed app: the ReportSniffer folder (Windows, Linux) or Report Sniffer.app (macOS); None from the source."""
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        app = exe.parents[2] if len(exe.parents) > 2 else exe
        return app if app.suffix == ".app" else None
    return exe.parent


def _why_not(target: Optional[Path], asset: Optional[dict]) -> str:
    """Empty if this copy can install the update itself, else the reason."""
    if target is None:
        return "source"
    if not asset or not asset.get("digest", "").startswith("sha256:"):
        return "no_build"
    if not (os.access(target, os.W_OK) and os.access(target.parent, os.W_OK)):
        return "read_only"
    return ""


def check(force: bool = False) -> dict:
    """{current, latest, newer, url, can_install, why, size} — or {current, error} when GitHub cannot be reached."""
    now = time.time()
    if not force and _cache["info"] and now - _cache["t"] < TTL:
        return _cache["info"]
    cur = current()
    try:
        r = httpx.get(API, timeout=10, follow_redirects=True,
                      headers={"Accept": "application/vnd.github+json", "User-Agent": f"ReportSniffer/{cur or 'dev'}"})
        r.raise_for_status()
        rel = r.json()
    except (httpx.HTTPError, ValueError) as e:
        return {"current": cur, "error": f"{type(e).__name__}: {e}"[:200]}
    latest = str(rel.get("tag_name") or "")
    name = asset_name()
    asset = next((a for a in rel.get("assets") or [] if a.get("name") == name), None)
    if asset and not str(asset.get("browser_download_url", "")).startswith(DOWNLOADS):
        asset = None
    newer = bool(parse(latest) and parse(cur) and parse(latest) > parse(cur))
    why = _why_not(install_dir(), asset)
    info = {"current": cur, "latest": latest.lstrip("v"), "newer": newer, "url": str(rel.get("html_url") or RELEASES),
            "can_install": newer and not why, "why": why, "size": int(asset.get("size") or 0) if asset else 0,
            "_asset": asset}
    _cache.update(t=now, info=info)
    return info


def public(info: dict) -> dict:
    return {k: v for k, v in info.items() if not k.startswith("_")}


class UpdateError(Exception):
    pass


Progress = Callable[[str, float], None]


def install(progress: Progress, steps: dict) -> None:
    """Downloads, checks and stages the update, then starts the helper that swaps it in once this app quits.
    steps: the progress messages in the interface language ({"download", "check", "restart"} and error texts)."""
    info = check(force=True)
    if info.get("error"):
        raise UpdateError(info["error"])
    if not info.get("newer"):
        raise UpdateError(steps["none"])
    if not info.get("can_install"):
        raise UpdateError(steps["manual"])
    asset, target = info["_asset"], install_dir()
    work = target.parent / ".report-sniffer-update"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    try:
        archive = work / asset["name"]
        _download(asset["browser_download_url"], archive, int(asset.get("size") or 0), progress, steps["download"])
        progress(steps["check"], 0.8)
        if _sha256(archive) != asset["digest"].split(":", 1)[1].lower():
            raise UpdateError(steps["corrupt"])
        new = _unpack(archive, work / "new")
        archive.unlink()
        _selftest(new, steps["broken"])
        progress(steps["restart"], 0.95)
        _start_helper(target, new, work)
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise


def _download(url: str, dest: Path, size: int, progress: Progress, step: str) -> None:
    got = 0
    with httpx.stream("GET", url, timeout=60, follow_redirects=True, headers={"User-Agent": f"ReportSniffer/{current()}"}) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                got += len(chunk)
                if got > MAX_BYTES:
                    raise UpdateError("download too large")
                f.write(chunk)
                progress(step, 0.05 + 0.7 * min(1.0, got / size) if size else 0.4)


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _unpack(archive: Path, dest: Path) -> Path:
    """The new app unpacked under dest: dest/ReportSniffer or dest/Report Sniffer.app."""
    dest.mkdir()
    if archive.name.endswith(".tar.gz"):
        with tarfile.open(archive) as tf:
            tf.extractall(dest, filter="data")           # no absolute paths, no links out of dest
    elif sys.platform == "darwin":
        # ditto keeps the app bundle's symbolic links and permissions, which zipfile does not
        subprocess.run(["ditto", "-x", "-k", str(archive), str(dest)], check=True, capture_output=True)
    else:
        with zipfile.ZipFile(archive) as zf:
            root = dest.resolve()
            for m in zf.namelist():
                if not (root / m).resolve().is_relative_to(root):
                    raise UpdateError("unsafe archive")
            zf.extractall(dest)
    found = [p for p in dest.iterdir() if p.name in ("ReportSniffer", "Report Sniffer.app")]
    if len(found) != 1:
        raise UpdateError("unexpected archive")
    return found[0]


def executable(app: Path) -> Path:
    if app.suffix == ".app":
        return app / "Contents" / "MacOS" / "ReportSniffer"
    return app / ("ReportSniffer.exe" if sys.platform == "win32" else "ReportSniffer")


def _selftest(new: Path, broken: str) -> None:
    """The new version must start and find everything it needs (its --selftest) before it replaces this one."""
    try:
        r = subprocess.run([str(executable(new)), "--selftest"], capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise UpdateError(f"{broken} ({type(e).__name__})")
    if r.returncode != 0:
        raise UpdateError(broken)


def helper_script(pid: int, target: Path, new: Path, work: Path) -> tuple[str, str]:
    """(file suffix, script) that waits for this app to quit, swaps the new version in and starts it."""
    backup = target.with_name(target.name + ".old")
    if sys.platform == "win32":
        exe = target / "ReportSniffer.exe"
        return ".cmd", "\r\n".join([
            "@echo off",
            f'set "TARGET={target}"', f'set "NEW={new}"', f'set "BACKUP={backup}"', f'set "WORK={work}"',
            "set /a n=0",
            ":wait",
            f'tasklist /FI "PID eq {pid}" /NH 2>nul | find /I "ReportSniffer" >nul',
            "if errorlevel 1 goto swap",
            "ping -n 2 127.0.0.1 >nul",
            "goto wait",
            ":swap",
            'if exist "%BACKUP%" rmdir /s /q "%BACKUP%"',
            'move "%TARGET%" "%BACKUP%" >nul 2>&1',
            "if not errorlevel 1 goto moved",
            "set /a n=n+1",
            "if %n% geq 30 goto start",
            "ping -n 2 127.0.0.1 >nul",
            "goto swap",
            ":moved",
            'move "%NEW%" "%TARGET%" >nul 2>&1',
            "if errorlevel 1 goto restore",
            'rmdir /s /q "%BACKUP%"',
            "goto start",
            ":restore",
            'move "%BACKUP%" "%TARGET%" >nul 2>&1',
            ":start",
            'rmdir /s /q "%WORK%"',
            f'start "" "{exe}"',
            '(goto) 2>nul & del "%~f0"',
            ""])
    q = shlex.quote
    launch = f"open {q(str(target))}" if target.suffix == ".app" else f"({q(str(executable(target)))} >/dev/null 2>&1 &)"
    return ".sh", "\n".join([
        "#!/bin/sh",
        "# Report Sniffer update: wait for the app to quit, swap the new version in, start it",
        f"i=0; while kill -0 {pid} 2>/dev/null && [ $i -lt 600 ]; do sleep 0.2; i=$((i+1)); done",
        f"rm -rf {q(str(backup))}",
        f"if mv {q(str(target))} {q(str(backup))}; then",
        f"  if mv {q(str(new))} {q(str(target))}; then rm -rf {q(str(backup))}; else mv {q(str(backup))} {q(str(target))}; fi",
        "fi",
        f"rm -rf {q(str(work))}",
        launch,
        'rm -f "$0"',
        ""])


def _start_helper(target: Path, new: Path, work: Path) -> None:
    suffix, text = helper_script(os.getpid(), target, new, work)
    fd, path = tempfile.mkstemp(prefix="report-sniffer-update-", suffix=suffix)   # outside the folders it moves
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    quiet = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        subprocess.Popen(["cmd.exe", "/d", "/c", path], creationflags=flags, **quiet)
    else:
        os.chmod(path, 0o700)
        subprocess.Popen(["/bin/sh", path], start_new_session=True, **quiet)
