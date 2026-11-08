"""Build synthetic test-network payout fixtures, without any network connection."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/tests"))
sys.path.insert(0, str(ROOT / "backend/src"))
from clan_wallet_helpers import (
    DESTINATION,
    OTHER_DESTINATION,
    fund,
    make_policy,
    secret_key,
    sign_normal_path,
)
from clans.clan_wallet import ClanWallet, Recipient

keys = [secret_key(i) for i in range(1, 5)]
policy = make_policy([keys[0], *sorted(keys[1:], key=lambda key: str(key.as_public()))])
wallet = ClanWallet(policy)
fund(wallet, 100_000)
records = []
for address in [DESTINATION, OTHER_DESTINATION]:
    draft = wallet.build_payout(
        [Recipient(address, 40_000)],
        fee_rate_sat_vb=2,
        max_fee_sats=2000,
        allow_unconfirmed=True,
        fee_paid_by="recipients",
    )
    records.append(
        {
            "id": "fixture-payout",
            "clan_id": "preview",
            "kind": "grant",
            "generation": 1,
            "destination": None,
            "replaces": None,
            "replaced_by": None,
            "status": "awaiting_signatures",
            "psbt": sign_normal_path(policy, keys[2], draft.psbt),
            "txid": draft.txid,
            "fee_paid_by": "recipients",
            "fee_sats": draft.fee_sats,
            "max_fee_sats": 2000,
            "fee_rate_sat_vb": 2,
            "recipients": [
                {
                    "grant_id": "fixture-grant",
                    "name": "Amina",
                    "address": DESTINATION,
                    "approved_sats": 40000,
                    "received_sats": 40000 - draft.fee_sats,
                }
            ],
            "signatures": {
                "count": 1,
                "required": 2,
                "signed_by_me": False,
                "names": ["Juma"],
            },
            "oversight_signed": False,
            "created_at": "2026-11-05T09:00:00Z",
            "broadcast_txid": None,
            "confirmations": 0,
        }
    )
target = ROOT / "frontend/src/wallet-payout-fixture.ts"
target.write_text(
    "// Synthetic signet-only payments with a test signatory signature. Rebuild with scripts/build_wallet_fixtures.py.\n"
    + "\n".join(
        "export const " + name + " = " + json.dumps(record, indent=2) + " as const;\n"
        for name, record in zip(["fixturePayout", "tamperedPayout"], records)
    ),
    encoding="utf-8",
)
print("Synthetic payout fixtures rebuilt; fee:", records[0]["fee_sats"])

# A replacement wallet keeps the first two keys; the third signatory has a new key.
new_keys = [keys[1], keys[2], secret_key(5)]
new_policy = make_policy([keys[0], *sorted(new_keys, key=lambda key: str(key.as_public()))])
receiving = ClanWallet(new_policy)
sweeps = []
for kind, destination, generation in [
    ("move", receiving.change_address(0), 2),
    ("refresh", wallet.change_address(4), 1),
]:
    source = ClanWallet(policy)
    fund(source, 100_000)
    draft = source.build_sweep(
        [coin.outpoint for coin in source.wallet.list_unspent()],
        destination,
        fee_rate_sat_vb=2,
        max_fee_sats=10000,
    )
    record = {
        **records[0], "id": f"fixture-{kind}", "kind": kind,
        "psbt": sign_normal_path(policy, keys[2], draft.psbt),
        "txid": draft.txid, "fee_sats": draft.fee_sats,
        "max_fee_sats": 10000, "fee_paid_by": "clan", "recipients": [],
        "destination": {"generation": generation, "keychain": "internal", "index": 0 if kind == "move" else 4, "address": destination},
    }
    sweeps.append(record)
(ROOT / "frontend/src/wallet-sweep-fixture.ts").write_text(
    "// Synthetic signet wallet moves and refreshes. Rebuild with scripts/build_wallet_fixtures.py.\n"
    + "\n".join(
        "export const " + name + " = " + json.dumps(record, indent=2) + " as const;\n"
        for name, record in zip(["fixtureMove", "fixtureRefresh"], sweeps)
    ), encoding="utf-8",
)
print("Synthetic move and refresh fixtures rebuilt.")
