"""Build the oversight laptop install kit. Installing it needs no internet and no Python.

    python scripts/build_oversight_kit.py [--url https://pilot.clans.afribit.africa]

Writes .local/oversight-kit/ and .local/afribit-oversight-<commit>.zip (both ignored by Git),
and prints the zip's SHA-256. The kit holds Windows' embeddable Python, every library the
tool needs, an installer and a launcher. It holds no keys, tokens or settings.

On the laptop: extract the zip, double-click "Install Afribit Oversight.cmd", then open
"Afribit Oversight" on the desktop. The person is guided from there (clans.oversight_guide).

Building needs the internet once, for Python and the libraries. Python's download is checked
against PYTHON_SHA256 below.
"""

import argparse
import hashlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
OUT = LOCAL / "oversight-kit"
PYTHON_VERSION = "3.12.10"
PYTHON_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
)
# Its MD5 matches the one python.org lists (fe8ef205f2e9c3ba44d0cf9954e1abd3). 3.12.10 is the
# last 3.12 release with Windows downloads.
PYTHON_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
APP_DIR = r"%LOCALAPPDATA%\Programs\Afribit Oversight"

LAUNCHER = r"""@echo off
title Afribit Oversight
"%~dp0python\python.exe" -I -m clans.oversight --url __URL__
if errorlevel 1 pause
"""

INSTALLER = r"""@echo off
setlocal
set "DEST=__APP_DIR__"
echo Installing Afribit Oversight for this Windows account. This needs no internet.
if exist "%DEST%\python" rmdir /s /q "%DEST%\python"
robocopy "%~dp0." "%DEST%" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo Copying failed. Nothing was changed on this laptop.
  pause
  exit /b 1
)
"%DEST%\python\python.exe" -I -c "import clans.oversight_guide, bdkpython"
if errorlevel 1 (
  echo The kit is incomplete. Ask the team for a new copy.
  pause
  exit /b 1
)
if /i "%~1"=="/noshortcut" exit /b 0
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Afribit Oversight.lnk'); $s.TargetPath='%DEST%\Afribit Oversight.cmd'; $s.WorkingDirectory='%DEST%'; $s.Save()"
echo.
echo Installed. Next time, open "Afribit Oversight" on your desktop.
echo Your key and records are kept when you install a newer kit.
echo Opening it now...
start "" "%DEST%\Afribit Oversight.cmd"
"""


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def python_zip() -> Path:
    cached = LOCAL / "cache" / Path(PYTHON_URL).name
    if not cached.exists():
        cached.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(PYTHON_URL, timeout=120) as response:
            cached.write_bytes(response.read())
    digest = hashlib.sha256(cached.read_bytes()).hexdigest()
    if digest != PYTHON_SHA256:
        cached.unlink()
        raise SystemExit(f"Python's download has an unexpected SHA-256 ({digest}). Not used.")
    return cached


def write_cmd(path: Path, text: str) -> None:
    path.write_bytes(text.replace("\n", "\r\n").encode("ascii"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://pilot.clans.afribit.africa")
    args = parser.parse_args()
    if not args.url.startswith("https://") or any(c in args.url for c in ' "&|<>^%'):
        raise SystemExit("Give the Clans address, for example https://clans.example.org")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("Commit your changes first, so the kit is a known commit.")
    commit = git("rev-parse", "--short=10", "HEAD")

    shutil.rmtree(OUT, ignore_errors=True)
    python = OUT / "python"
    python.mkdir(parents=True)
    with zipfile.ZipFile(python_zip()) as archive:
        archive.extractall(python)
    # The embeddable Python reads its search path only from this file.
    (pth,) = python.glob("python3*._pth")
    pth.write_text(pth.read_text().replace(".\n", ".\nlib\n", 1))

    wheels = LOCAL / "oversight-wheel"
    shutil.rmtree(wheels, ignore_errors=True)
    pip = [sys.executable, "-m", "pip", "--disable-pip-version-check"]
    subprocess.run(
        [*pip, "wheel", "--no-deps", "--quiet", "--wheel-dir", str(wheels), str(ROOT / "backend")],
        check=True,
    )
    (wheel,) = wheels.glob("*.whl")
    subprocess.run(
        [
            *pip,
            "install",
            "--quiet",
            "--target",
            str(python / "lib"),
            "--platform",
            "win_amd64",
            "--python-version",
            PYTHON_VERSION.rsplit(".", 1)[0],
            "--implementation",
            "cp",
            "--only-binary=:all:",
            str(wheel),
        ],
        check=True,
    )
    write_cmd(OUT / "Afribit Oversight.cmd", LAUNCHER.replace("__URL__", args.url))
    write_cmd(OUT / "Install Afribit Oversight.cmd", INSTALLER.replace("__APP_DIR__", APP_DIR))
    (OUT / "kit-version.txt").write_text(f"commit {commit}\nClans {args.url}\n")

    bundle = LOCAL / f"afribit-oversight-{commit}.zip"
    bundle.unlink(missing_ok=True)
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(OUT.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, Path("Afribit Oversight") / path.relative_to(OUT))
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    print(f"Kit for commit {commit}: {bundle}")
    print(f"{bundle.stat().st_size // 1_000_000} MB, SHA-256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
