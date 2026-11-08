"""Check the phone's downloaded public fixture with the standalone recovery tool."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
sys.path.insert(0, str(ROOT / "backend/tests"))
from clan_wallet_helpers import make_policy, secret_key
from clans.recover import wallet_backup

path = ROOT / ".local/wallet-f9-backup.json"
actual = json.loads(path.read_text(encoding="utf-8"))
keys = [secret_key(i) for i in range(1, 5)]
policy = make_policy([keys[0], *sorted(keys[1:], key=lambda key: str(key.as_public()))])
assert actual == wallet_backup(policy, clan_id="preview", generation=1), (
    "Downloaded phone backup differs from the independent backend fixture"
)
result = subprocess.run(
    [sys.executable, "-m", "clans.recover", "check", str(path)],
    cwd=ROOT,
    capture_output=True,
    text=True,
    check=False,
)
if result.returncode:
    raise SystemExit("Recovery CLI refused the phone backup: " + result.stderr)
print("Phone backup matches the independent fixture; recovery CLI check passed.")
