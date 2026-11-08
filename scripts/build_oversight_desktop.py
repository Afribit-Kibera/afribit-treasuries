"""Build the Python core that the oversight desktop app bundles.

    python scripts/build_oversight_desktop.py

Writes oversight-desktop/build/python/ (ignored by Git): Windows' embeddable Python 3.13, the
libraries in oversight-desktop/src-tauri/python-requirements.txt (each checked by its SHA-256),
and only the clans modules the oversight core uses. `tauri build` then packs that folder into
the installer as a resource. The GitHub workflow .github/workflows/oversight-desktop.yml runs
this, then builds the screens and the installer.

Python 3.13.17 is the last 3.13 release with Windows downloads. 3.14 waits for bdkpython to
publish Windows wheels for it.
"""

import hashlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "oversight-desktop"
OUT = APP / "build" / "python"
CACHE = ROOT / ".local" / "cache"
REQUIREMENTS = APP / "src-tauri" / "python-requirements.txt"
PYTHON_VERSION = "3.13.17"
PYTHON_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
)
# Checked on 6 Nov 2026 against python.org's Sigstore bundle for this file, signed by the 3.13
# release manager (thomas@python.org, issuer accounts.google.com).
PYTHON_SHA256 = "9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38"
# The oversight core and what it imports. Nothing from the server side.
CORE = ["__init__.py", "clan_wallet.py", "explorers.py", "oversight.py", "oversight_guide.py",
        "oversight_service.py", "recover.py"]  # fmt: skip


def python_zip() -> Path:
    cached = CACHE / Path(PYTHON_URL).name
    if not cached.exists():
        cached.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(PYTHON_URL, timeout=120) as response:
            cached.write_bytes(response.read())
    digest = hashlib.sha256(cached.read_bytes()).hexdigest()
    if digest != PYTHON_SHA256:
        cached.unlink()
        raise SystemExit(f"Python's download has an unexpected SHA-256 ({digest}). Not used.")
    return cached


def main() -> int:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    with zipfile.ZipFile(python_zip()) as archive:
        archive.extractall(OUT)
    # The embeddable Python reads its search path only from this file.
    (pth,) = OUT.glob("python3*._pth")
    pth.write_text(pth.read_text().replace(".\n", ".\nlib\n", 1))
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--quiet",
            "--no-deps",
            "--require-hashes",
            "--only-binary=:all:",
            "--platform",
            "win_amd64",
            "--python-version",
            PYTHON_VERSION.rsplit(".", 1)[0],
            "--implementation",
            "cp",
            "--target",
            str(OUT / "lib"),
            "-r",
            str(REQUIREMENTS),
        ],
        check=True,
    )
    package = OUT / "lib" / "clans"
    package.mkdir()
    for name in CORE:
        shutil.copy2(ROOT / "backend" / "src" / "clans" / name, package / name)
    for cache in OUT.rglob("__pycache__"):
        shutil.rmtree(cache)
    if sys.platform == "win32":
        subprocess.run(
            [
                str(OUT / "python.exe"),
                "-I",
                "-c",
                "import clans.oversight_service, bdkpython, cryptography, httpx",
            ],
            check=True,
        )
    size = sum(path.stat().st_size for path in OUT.rglob("*") if path.is_file())
    print(f"Python core for the desktop app: {OUT} ({size // 1_000_000} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
