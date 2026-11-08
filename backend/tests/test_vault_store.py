"""The phone key store (frontend/src/vault/store.ts) encrypts words and refuses bad unlocks."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    not NODE or not (FRONTEND / "node_modules" / "@noble" / "hashes").is_dir(),
    reason="Node.js and frontend dependencies are needed for the key store check",
)


def test_phone_key_store():
    result = subprocess.run(
        [NODE, "--no-warnings", "scripts/vault-store-check.ts"],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["ok"]
    assert report["results"] == [
        "pin round trip",
        "no plaintext",
        "bad input",
        "pin lockout",
        "bound to clan and untampered",
        "passkey",
        "forget",
    ]
