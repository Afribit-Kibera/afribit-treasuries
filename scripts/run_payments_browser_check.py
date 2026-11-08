"""Run a loopback browser check and print only its sanitized result."""

import json
import subprocess
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text(encoding="utf-8").strip().removesuffix(";")
session = Path(".local/payments-browser-session.json").read_text(encoding="utf-8")
runtime = Path(".local/home-browser-runtime.js")
runtime.write_text(source.replace("__LOCAL_SESSION__", session), encoding="utf-8")
result = subprocess.run(
    [
        "npx.cmd",
        "--yes",
        "--package",
        "@playwright/cli",
        "playwright-cli",
        "-s=" + (sys.argv[2] if len(sys.argv) > 2 else "clans-home"),
        "run-code",
        "--filename",
        str(runtime),
    ],
    capture_output=True,
    text=True,
    encoding="utf-8",
    check=False,
)
if "### Result\n" not in result.stdout:
    print(result.stdout.split("### Ran Playwright code")[0][:2000])
    print(result.stderr[:500])
    raise SystemExit(1)
data, _ = json.JSONDecoder().raw_decode(result.stdout.split("### Result\n", 1)[1])
print(json.dumps(data, indent=2))
