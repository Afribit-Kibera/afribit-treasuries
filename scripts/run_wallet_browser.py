"""Run local wallet UI checks without printing the evaluated code or secrets."""

import json
import subprocess
import sys
from pathlib import Path

runtime = Path(".local/wallet-browser-runtime.js")
source = Path(sys.argv[1]).read_text(encoding="utf-8").strip().removesuffix(";")
if len(sys.argv) > 3:
    source = source.replace(
        "__LOCAL_WALLET_SESSION__",
        json.dumps(json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))),
    )
runtime.write_text(source, encoding="utf-8")
result = subprocess.run(
    [
        "npx.cmd",
        "--yes",
        "--package",
        "@playwright/cli",
        "playwright-cli",
        "-s=clans-wallet",
        "run-code",
        "--filename",
        str(runtime),
    ],
    capture_output=True,
    check=False,
    text=True,
    encoding="utf-8",
)
if "### Result\n" not in result.stdout:
    print(result.stdout.split("### Ran Playwright code")[0][:1800])
    raise SystemExit(1)
value, _ = json.JSONDecoder().raw_decode(result.stdout.split("### Result\n", 1)[1])
if len(sys.argv) > 2:
    Path(sys.argv[2]).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
print(json.dumps(value))
