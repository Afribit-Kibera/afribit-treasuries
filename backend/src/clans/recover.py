"""Recover a clan's money without Clans or Afribit, on the wallet's recovery path.

After a coin has waited the recovery period (about 6 months) without being spent, the
clan's signatories alone can move it: no Afribit key and no Clans server are needed.

What the signatories need:

* the wallet backup file, which holds only public keys (every signatory should keep one);
* their own 12 backup words, entered only on the computer that signs;
* a block explorer, to find the coins and send the payment.

Steps: `check` the backup, list `coins`, `build` a sweep to an agreed address, each
signatory `sign`s it (offline is fine), then `finish` combines and sends it.

Usage: python -m clans.recover <command> ...   (test networks only, like the wallets)
"""

import argparse
import getpass
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import bdkpython as bdk

from clans.clan_wallet import (
    BRANCHES,
    KEYCHAINS,
    NETWORKS,
    RECOVERY_PATH,
    ClanPolicy,
    ClanWallet,
    ClanWalletError,
    account_path,
    bdk_fee_rate,
    network_kind,
)

BACKUP_FORMAT = "afribit-clan-wallet-backup/1"
SWEEP_FORMAT = "afribit-clan-recovery-sweep/1"
SIGNED_FORMAT = "afribit-clan-recovery-signature/1"
# Ten-minute blocks, for showing waits in days.
BLOCKS_PER_DAY = 144
DEFAULT_MAX_FEE_SATS = 10_000
DEFAULT_STOP_GAP = 200
SIGN_OPTIONS = dict(
    trust_witness_utxo=False,
    assume_height=None,
    allow_all_sighashes=False,
    try_finalize=False,
    sign_with_tap_internal_key=False,
    allow_grinding=True,
)


class RecoveryError(Exception):
    """The backup, the sweep or a signature can't be used safely."""


# Backup file ---------------------------------------------------------------------------


def wallet_backup(policy: ClanPolicy, *, generation: int = 1, clan_id: str | None = None) -> dict:
    """The public wallet backup. Phones and the oversight tool write the same fields."""
    return {
        "format": BACKUP_FORMAT,
        "network": policy.network,
        "clan_id": clan_id,
        "generation": generation,
        "wallet_code": policy.wallet_code(),
        "oversight": [str(key) for key in policy.oversight],
        "signers": [str(key) for key in policy.signers],
        "threshold": policy.threshold,
        "recovery_threshold": policy.recovery_threshold,
        "recovery_blocks": policy.recovery_blocks,
        "descriptors": {
            keychain: str(policy.bdk_descriptor(keychain)) for keychain in ("external", "internal")
        },
    }


def read_backup(data: dict) -> ClanPolicy:
    """Rebuild the wallet from its keys and check it matches every other field in the file."""
    if not isinstance(data, dict) or data.get("format") != BACKUP_FORMAT:
        raise RecoveryError("This isn't an Afribit clan wallet backup")
    try:
        policy = ClanPolicy.create(
            network=data["network"],
            oversight=list(data["oversight"]),
            signers=list(data["signers"]),
            recovery_threshold=int(data["recovery_threshold"]),
            recovery_blocks=int(data["recovery_blocks"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RecoveryError(f"The backup can't be read: {exc}") from exc
    expected = wallet_backup(policy, generation=data.get("generation", 1))
    for field in ("wallet_code", "threshold", "descriptors"):
        if data.get(field) != expected[field]:
            raise RecoveryError(f"The backup's {field.replace('_', ' ')} doesn't match its keys")
    return policy


def load_backup(path: str | Path) -> ClanPolicy:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecoveryError(f"Can't open the backup file: {exc}") from exc
    return read_backup(data)


def core_import(policy: ClanPolicy, timestamp: int | str = 0) -> list[dict]:
    """Bitcoin Core `importdescriptors` request for a watch-only copy of the wallet."""
    return [
        {
            "desc": str(policy.bdk_descriptor(keychain)),
            "timestamp": timestamp,
            "active": True,
            "internal": keychain == "internal",
            "range": [0, 1000],
        }
        for keychain in ("external", "internal")
    ]


# Coins -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Coin:
    outpoint: str
    amount_sats: int
    confirmations: int
    waiting_blocks: int

    @property
    def recoverable(self) -> bool:
        return self.waiting_blocks == 0


def coins(policy: ClanPolicy, wallet: ClanWallet, tip: int) -> list[Coin]:
    """Every coin in the wallet and how long it still has to wait for the recovery path."""
    found = []
    for utxo in wallet.wallet.list_unspent():
        position = utxo.chain_position
        if position.is_confirmed():
            height = position.confirmation_block_time.block_id.height
            depth = max(tip - height + 1, 0)
        else:
            depth = 0
        found.append(
            Coin(
                outpoint=f"{utxo.outpoint.txid}:{utxo.outpoint.vout}",
                amount_sats=utxo.txout.value.to_sat(),
                confirmations=depth,
                # A relative timelock of n blocks needs n confirmations on the coin.
                waiting_blocks=max(policy.recovery_blocks - depth, 0),
            )
        )
    return sorted(found, key=lambda coin: coin.outpoint)


def _outpoint(text: str) -> bdk.OutPoint:
    txid, vout = text.rsplit(":", 1)
    return bdk.OutPoint(txid=bdk.Txid.from_string(txid), vout=int(vout))


# Sweep -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Sweep:
    to: str
    amount_sats: int
    fee_sats: int
    inputs: tuple[str, ...]
    txid: str


def build_sweep(
    policy: ClanPolicy,
    wallet: ClanWallet,
    to: str,
    outpoints: list[str],
    *,
    fee_rate_sat_vb: float,
    max_fee_sats: int = DEFAULT_MAX_FEE_SATS,
) -> dict:
    """Move the chosen coins, minus the network fee, to one address on the recovery path."""
    if not outpoints:
        raise RecoveryError("No coins have waited long enough for the recovery path yet")
    if not 1 <= fee_rate_sat_vb <= 1_000:
        raise RecoveryError("Unreasonable network fee rate")
    builder = (
        bdk.TxBuilder()
        .fee_rate(bdk_fee_rate(fee_rate_sat_vb))
        .add_utxos([_outpoint(item) for item in outpoints])
        .manually_selected_only()
        .drain_to(_script(policy, to))
    )
    for keychain in KEYCHAINS.values():
        policy_id = wallet.wallet.policies(keychain).id()
        builder = builder.policy_path({policy_id: RECOVERY_PATH}, keychain)
    try:
        psbt = builder.finish(wallet.wallet)
    except Exception as exc:
        raise RecoveryError(f"The sweep can't be built: {exc}") from exc
    sweep = {"format": SWEEP_FORMAT, "wallet_code": policy.wallet_code(), "to": to}
    sweep["psbt"] = psbt.serialize()
    check_sweep(policy, sweep, max_fee_sats=max_fee_sats)
    return sweep


def _script(policy: ClanPolicy, address: str) -> bdk.Script:
    try:
        return bdk.Address(address, NETWORKS[policy.network]).script_pubkey()
    except Exception as exc:
        raise RecoveryError("The destination address isn't valid on this network") from exc


def check_sweep(
    policy: ClanPolicy, sweep: dict, *, max_fee_sats: int = DEFAULT_MAX_FEE_SATS
) -> Sweep:
    """Check a sweep before anyone signs it: our coins, one destination, the recovery wait."""
    if not isinstance(sweep, dict) or sweep.get("format") != SWEEP_FORMAT:
        raise RecoveryError("This isn't a clan recovery sweep")
    if sweep.get("wallet_code") != policy.wallet_code():
        raise RecoveryError("This sweep is for a different clan wallet")
    try:
        psbt = bdk.Psbt(sweep["psbt"])
        details = json.loads(psbt.json_serialize())
    except Exception as exc:
        raise RecoveryError("The sweep's payment data can't be read") from exc
    tx, view = details["unsigned_tx"], ClanWallet(policy)
    outputs = tx["output"]
    expected = bytes(_script(policy, sweep["to"]).to_bytes()).hex()
    if len(outputs) != 1 or outputs[0]["script_pubkey"] != expected:
        raise RecoveryError("The sweep must pay everything to the one agreed address")
    total = 0
    for txin, item in zip(tx["input"], details["inputs"], strict=True):
        if txin["sequence"] != policy.recovery_blocks:
            raise RecoveryError("The sweep doesn't use the recovery wait")
        utxo = item.get("witness_utxo")
        if not utxo or not _ours(policy, view, item, utxo["script_pubkey"]):
            raise RecoveryError("The sweep spends a coin that isn't in this clan wallet")
        total += int(utxo["value"])
    amount = int(outputs[0]["value"])
    fee = total - amount
    if fee <= 0 or fee > max_fee_sats:
        raise RecoveryError(f"The network fee ({fee} sats) is above the limit of {max_fee_sats}")
    txid = str(psbt.extract_tx_unchecked_fee_rate().compute_txid())
    return Sweep(sweep["to"], amount, fee, tuple(t["previous_output"] for t in tx["input"]), txid)


def _ours(policy: ClanPolicy, view: ClanWallet, item: dict, script_hex: str) -> bool:
    """The coin's address must come from this wallet at the position the payment claims."""
    for _key, (_leaves, (_fingerprint, path)) in item.get("tap_key_origins", []):
        steps = path.lstrip("m/").split("/")
        expected = account_path(policy.network)
        if len(steps) != 5 or "/".join(steps[:3]).replace("h", "'") != expected:
            continue
        branch, index = int(steps[3]), int(steps[4])
        keychain = next((k for k, pair in BRANCHES.items() if branch in pair), None)
        if keychain is None:
            continue
        try:
            address = view.wallet.peek_address(KEYCHAINS[keychain], index).address
        except Exception:
            return False
        return bytes(address.script_pubkey().to_bytes()).hex() == script_hex
    return False


def account_key(words: str, network: str = "signet") -> bdk.DescriptorSecretKey:
    try:
        mnemonic = bdk.Mnemonic.from_string(" ".join(words.lower().split()))
    except Exception as exc:
        raise RecoveryError("These backup words aren't valid") from exc
    master = bdk.DescriptorSecretKey(network_kind(network), mnemonic, None)
    return master.derive(bdk.DerivationPath("m/" + account_path(network)))


def sign_sweep(policy: ClanPolicy, sweep: dict, words: str, **limits) -> dict:
    """Add one signatory's signature, on the recovery path only."""
    checked = check_sweep(policy, sweep, **limits)
    key = account_key(words, policy.network)
    public = str(key.as_public())
    if public not in {str(signer) for signer in policy.signers}:
        raise RecoveryError("These words don't belong to a signatory of this clan wallet")

    def private(keychain: str) -> bdk.Descriptor:
        _, recovery = BRANCHES[keychain]
        text, target = policy.descriptor(keychain), f"{public}/{recovery}/*"
        return bdk.Descriptor(
            text.replace(target, f"{key}/{recovery}/*"), network_kind(policy.network)
        )

    signer = bdk.Wallet(
        private("external"),
        private("internal"),
        NETWORKS[policy.network],
        bdk.Persister.new_in_memory(),
    )
    copy = bdk.Psbt(sweep["psbt"])
    before = _signatures(copy)
    signer.sign(copy, bdk.SignOptions(**SIGN_OPTIONS))
    if any(new <= old for old, new in zip(before, _signatures(copy), strict=True)):
        raise RecoveryError("Your key couldn't sign every coin in this sweep")
    return {
        "format": SIGNED_FORMAT,
        "wallet_code": policy.wallet_code(),
        "txid": checked.txid,
        "signer": public,
        "psbt": copy.serialize(),
    }


def _signatures(psbt: bdk.Psbt) -> list[int]:
    return [
        len(item.get("tap_script_sigs", [])) for item in json.loads(psbt.json_serialize())["inputs"]
    ]


def finish_sweep(policy: ClanPolicy, sweep: dict, signed: list[dict], **limits) -> str:
    """Combine the signatories' copies and return the transaction, ready to send."""
    checked = check_sweep(policy, sweep, **limits)
    combined = bdk.Psbt(sweep["psbt"])
    for copy in signed:
        if copy.get("format") != SIGNED_FORMAT or copy.get("txid") != checked.txid:
            raise RecoveryError("A signed copy is for a different sweep")
        part = bdk.Psbt(copy["psbt"])
        if str(part.extract_tx_unchecked_fee_rate().compute_txid()) != checked.txid:
            raise RecoveryError("A signed copy is for a different sweep")
        combined = combined.combine(part)
    result = combined.finalize()
    if not result.could_finalize:
        raise RecoveryError(
            f"Not enough valid signatures yet: {policy.recovery_threshold} signatories must sign"
        )
    return bytes(result.psbt.extract_tx().serialize()).hex()


# Command line ----------------------------------------------------------------------------


def _explorer(policy: ClanPolicy, url: str | None) -> str:
    return (url or f"https://mempool.space/{policy.network}/api").rstrip("/")


def _synced(policy: ClanPolicy, url: str, stop_gap: int) -> tuple[ClanWallet, int]:
    wallet = ClanWallet(policy)
    wallet.sync(url, stop_gap=stop_gap, all_change=True)
    return wallet, bdk.EsploraClient(url).get_height()


def _read(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecoveryError(f"Can't open {path}: {exc}") from exc


def _write(path: str, value: dict) -> None:
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _days(blocks: int) -> str:
    return f"about {max(round(blocks / BLOCKS_PER_DAY), 1)} days"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m clans.recover", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="Check a wallet backup and show its first address")
    check.add_argument("backup")
    core = commands.add_parser("core", help="Print a Bitcoin Core importdescriptors request")
    core.add_argument("backup")
    for name in ("coins", "build"):
        command = commands.add_parser(
            name, help="List coins and their wait" if name == "coins" else "Build a sweep"
        )
        command.add_argument("backup")
        command.add_argument("--esplora", help="Block explorer API (default: mempool.space)")
        command.add_argument("--stop-gap", type=int, default=DEFAULT_STOP_GAP)
    build = commands.choices["build"]
    build.add_argument("--to", required=True, help="The address everyone agreed on")
    build.add_argument("--fee-rate", type=float, required=True, help="sats per vbyte")
    build.add_argument("--max-fee", type=int, default=DEFAULT_MAX_FEE_SATS)
    build.add_argument("--out", default="sweep.json")
    sign = commands.add_parser("sign", help="Sign a sweep with your 12 words (works offline)")
    sign.add_argument("backup")
    sign.add_argument("sweep")
    sign.add_argument("--max-fee", type=int, default=DEFAULT_MAX_FEE_SATS)
    sign.add_argument("--out", default="signed.json")
    finish = commands.add_parser("finish", help="Combine signed copies and send the sweep")
    finish.add_argument("backup")
    finish.add_argument("sweep")
    finish.add_argument("signed", nargs="+")
    finish.add_argument("--max-fee", type=int, default=DEFAULT_MAX_FEE_SATS)
    finish.add_argument("--esplora")
    finish.add_argument("--broadcast", action="store_true")
    args = parser.parse_args(argv)
    try:
        policy = load_backup(args.backup)
        if args.command == "check":
            print(f"Clan wallet {policy.wallet_code()} on {policy.network}. Backup checked.")
            print(f"First address: {ClanWallet(policy).address(0)}")
            print(
                f"Normal payments: Afribit and {policy.threshold} of {len(policy.signers)} "
                f"signatories. Recovery: {policy.recovery_threshold} signatories alone, once a "
                f"coin has waited {policy.recovery_blocks} blocks "
                f"({_days(policy.recovery_blocks)})."
            )
        elif args.command == "core":
            print(json.dumps(core_import(policy), indent=2))
        elif args.command in {"coins", "build"}:
            url = _explorer(policy, args.esplora)
            wallet, tip = _synced(policy, url, args.stop_gap)
            found = coins(policy, wallet, tip)
            if args.command == "coins":
                for coin in found:
                    wait = "ready" if coin.recoverable else f"in {_days(coin.waiting_blocks)}"
                    print(
                        f"{coin.outpoint}  {coin.amount_sats} sats  "
                        f"{coin.confirmations} confirmations  recovery {wait}"
                    )
                print(f"{len(found)} coins, {sum(c.amount_sats for c in found)} sats in total.")
            else:
                ready = [coin.outpoint for coin in found if coin.recoverable]
                sweep = build_sweep(
                    policy,
                    wallet,
                    args.to,
                    ready,
                    fee_rate_sat_vb=args.fee_rate,
                    max_fee_sats=args.max_fee,
                )
                checked = check_sweep(policy, sweep, max_fee_sats=args.max_fee)
                _write(args.out, sweep)
                print(
                    f"Sweep of {len(ready)} coins: {checked.amount_sats} sats to {checked.to}, "
                    f"fee {checked.fee_sats} sats. Saved to {args.out}. Coins still waiting: "
                    f"{len(found) - len(ready)}."
                )
        elif args.command == "sign":
            sweep = _read(args.sweep)
            checked = check_sweep(policy, sweep, max_fee_sats=args.max_fee)
            print(f"Pays {checked.amount_sats} sats to {checked.to}")
            print(f"Network fee: {checked.fee_sats} sats. Coins: {len(checked.inputs)}.")
            typed = input("Type the last 6 characters of the address you agreed on: ").strip()
            if typed.lower() != checked.to[-6:].lower():
                print("That doesn't match. Nothing was signed.")
                return 1
            words = getpass.getpass("Your 12 backup words (not shown): ")
            signed = sign_sweep(policy, sweep, words, max_fee_sats=args.max_fee)
            words = ""
            _write(args.out, signed)
            print(f"Signed. Send {args.out} to whoever finishes the sweep. It holds no secrets.")
        elif args.command == "finish":
            sweep = _read(args.sweep)
            signed = [_read(path) for path in args.signed]
            raw = finish_sweep(policy, sweep, signed, max_fee_sats=args.max_fee)
            txid = str(bdk.Transaction(bytes.fromhex(raw)).compute_txid())
            if args.broadcast:
                client = bdk.EsploraClient(_explorer(policy, args.esplora))
                client.broadcast(bdk.Transaction(bytes.fromhex(raw)))
                print(f"Sent: {txid}")
            else:
                print(raw)
                print(f"Ready to send: {txid}. Run again with --broadcast, or paste the line above")
                print("into a block explorer's 'broadcast transaction' page.")
    except (RecoveryError, ClanWalletError) as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
