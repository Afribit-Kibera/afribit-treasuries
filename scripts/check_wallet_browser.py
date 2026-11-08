"""Run wallet browser checks serially against the isolated development preview."""

import json
import subprocess
import sys
from pathlib import Path

total = 0
for name in [
    "setup",
    "compare",
    "status",
    "payout",
    "deposit_restore",
    "routing",
    "f8",
    "backup",
    "f10",
]:
    report = Path(f".local/wallet-{name}-final.json")
    subprocess.run(
        [
            sys.executable,
            "scripts/run_wallet_browser.py",
            f"scripts/wallet_{name}_browser.js",
            str(report),
        ],
        check=True,
    )
    total += json.loads(report.read_text())["passed"]
print(f"Wallet browser checks passed: {total}")
