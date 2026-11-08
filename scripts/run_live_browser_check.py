"""Capture only sanitized browser check results, never staging recovery material."""

import json
import subprocess
from pathlib import Path

result = subprocess.run(
    [
        "npx.cmd",
        "--yes",
        "--package",
        "@playwright/cli",
        "playwright-cli",
        "-s=clans-stage",
        "run-code",
        "--filename",
        "scripts/live_browser_smoke.js",
    ],
    capture_output=True,
    text=True,
    encoding="utf-8",
    check=False,
)
if result.returncode or "### Result\n" not in result.stdout:
    print(result.stdout[:3000])
    print(result.stderr[:1000])
    raise SystemExit(1)
payload = result.stdout.split("### Result\n", 1)[1]
data, _ = json.JSONDecoder().raw_decode(payload)
data.update(
    environment="private PostgreSQL stage; loopback SSH tunnel",
    production_accounts_created=0,
    mainnet_funds_moved=False,
)
target = Path("docs/test-results/2026-11-03-live-browser.json")
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
print(json.dumps(data))
