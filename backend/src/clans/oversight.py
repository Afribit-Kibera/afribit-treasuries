"""Afribit oversight tool: checks and signs clan payouts on an Afribit oversight laptop.

Run it as `python -m clans.oversight`, only on an oversight laptop, never on the Clans server.
Without a command it starts the guided app (clans.oversight_guide), which is what Afribit staff
use. The commands are for administrators and for working without a connection.

The oversight key is a software key for now. Its 12 backup words are encrypted on the laptop
with the person's passphrase and decrypted only in memory while signing. A Ledger can replace
it later.

The tool trusts nothing the Clans server says about who should be paid:

* Each clan wallet is registered once, and only after the wallet code matches a signatory's
  phone. Every payout is then checked against that saved wallet, not the server's copy.
* Beneficiary addresses must be confirmed by phone with the beneficiary before first use.
* A grant is paid once. A higher-fee replacement is allowed only if it spends the same coins,
  so both versions can never confirm.
* The fee may not exceed this laptop's own limit, whatever the server asks for.
"""

import argparse
import base64
import getpass
import hashlib
import json
import os
import re
import secrets
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import scrypt
from pathlib import Path
from urllib.parse import urlsplit

import bdkpython as bdk
import httpx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from clans import recover
from clans.clan_wallet import (
    BRANCHES,
    FEE_PAYERS,
    NETWORKS,
    ClanPolicy,
    ClanWallet,
    ClanWalletError,
    Recipient,
    account_path,
    amounts_received,
    network_kind,
)

KEY_FILE = "oversight-key.json"
REGISTER_FILE = "register.json"
LOCK_FILE = "in-use.lock"
VERSION = 1
MIN_PASSPHRASE = 12
SCRYPT = {"n": 2**17, "r": 8, "p": 1}
# max_sweep_fee_sats limits refreshes and moves to a new wallet, which spend many coins.
DEFAULT_SETTINGS = {
    "max_fee_sats": 5_000,
    "max_sweep_fee_sats": 10_000,
    "large_payout_sats": 100_000,
}
CHECK_CHARACTERS = 6


class OversightError(Exception):
    """A check failed. The message says what to do."""


def default_home() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "AfribitOversight"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def only_one_app(home: Path):
    """Held while an app works on this laptop's files, so two windows can't write them at once.

    The console app and the desktop app both take it. Windows frees it if the app crashes.
    """
    home.mkdir(parents=True, exist_ok=True)
    handle = open(home / LOCK_FILE, "a+b")  # noqa: SIM115 - held until the app closes
    try:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise OversightError(
                "Afribit Oversight is already open on this laptop. Use that window, or close it "
                "and try again"
            ) from exc
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        handle.close()


# ---------- the key ----------


def _derive(passphrase: str, salt: bytes, params: dict) -> bytes:
    return scrypt(passphrase.encode(), salt=salt, dklen=32, maxmem=512 * 1024 * 1024, **params)


def _account(words: str, network: str = "signet") -> bdk.DescriptorSecretKey:
    try:
        mnemonic = bdk.Mnemonic.from_string(" ".join(words.lower().split()))
    except Exception as exc:
        raise OversightError("These backup words are not valid") from exc
    master = bdk.DescriptorSecretKey(network_kind(network), mnemonic, None)
    return master.derive(bdk.DerivationPath("m/" + account_path(network)))


def create_key(home: Path, passphrase: str, words: str | None = None) -> tuple[str, str]:
    """Create (or restore from `words`) this laptop's oversight key.

    Returns the backup words and the public key. The words are stored only encrypted.
    """
    path = home / KEY_FILE
    if path.exists():
        raise OversightError(f"This laptop already has an oversight key in {path}")
    if len(passphrase) < MIN_PASSPHRASE:
        raise OversightError(f"Use a passphrase of at least {MIN_PASSPHRASE} characters")
    words = " ".join((words or str(bdk.Mnemonic(bdk.WordCount.WORDS12))).lower().split())
    public = str(_account(words).as_public())
    mainnet = str(_account(words, "bitcoin").as_public())
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    sealed = AESGCM(_derive(passphrase, salt, SCRYPT)).encrypt(
        nonce, words.encode(), public.encode()
    )

    def encode(data: bytes) -> str:
        return base64.b64encode(data).decode()

    _write_json(
        path,
        {
            "version": VERSION,
            "public_key": public,
            # The same words give a separate key on Bitcoin mainnet. Not sealed with them.
            "mainnet_public_key": mainnet,
            "kdf": {"name": "scrypt", **SCRYPT, "salt": encode(salt)},
            "nonce": encode(nonce),
            "sealed_words": encode(sealed),
            "created_at": _now(),
        },
    )
    return words, public


def _key_file(home: Path) -> dict:
    path = home / KEY_FILE
    if not path.exists():
        raise OversightError("This laptop has no oversight key yet. Run create-key first")
    return json.loads(path.read_text(encoding="utf-8"))


def public_key(home: Path, network: str = "signet") -> str:
    """This laptop's public key on a network: tpub for test networks, xpub for mainnet."""
    record = _key_file(home)
    if network != "bitcoin":
        return record["public_key"]
    if "mainnet_public_key" not in record:
        raise OversightError(
            "This key was made before mainnet keys. Approve once with your passphrase, "
            "or run show-key --network bitcoin, to add it"
        )
    return record["mainnet_public_key"]


class WrongPassphrase(OversightError):
    def __init__(self):
        super().__init__("Wrong passphrase")


def open_words(home: Path, passphrase: str) -> str:
    """The 12 backup words, decrypted in memory. Only for checking the paper copy and signing."""
    record = _key_file(home)
    kdf = record["kdf"]
    params = {name: kdf[name] for name in ("n", "r", "p")}
    try:
        return (
            AESGCM(_derive(passphrase, base64.b64decode(kdf["salt"]), params))
            .decrypt(
                base64.b64decode(record["nonce"]),
                base64.b64decode(record["sealed_words"]),
                record["public_key"].encode(),
            )
            .decode()
        )
    except InvalidTag as exc:
        raise WrongPassphrase() from exc


def unlock(home: Path, passphrase: str, network: str = "signet") -> bdk.DescriptorSecretKey:
    record = _key_file(home)
    words = open_words(home, passphrase).encode()
    key = _account(words.decode())
    if str(key.as_public()) != record["public_key"]:
        raise OversightError("The key file is damaged. Restore it from the backup words")
    mainnet = _account(words.decode(), "bitcoin")
    if record.get("mainnet_public_key") not in (None, str(mainnet.as_public())):
        raise OversightError("The key file is damaged. Restore it from the backup words")
    if "mainnet_public_key" not in record:
        # Keys made before mainnet support: add the mainnet public key now.
        _write_json(home / KEY_FILE, {**record, "mainnet_public_key": str(mainnet.as_public())})
    return mainnet if network == "bitcoin" else key


# ---------- the local register ----------


def load_register(home: Path) -> dict:
    path = home / REGISTER_FILE
    if not path.exists():
        return {
            "version": VERSION,
            "settings": dict(DEFAULT_SETTINGS),
            "wallets": {},
            "addresses": {},
            "payouts": [],
        }
    return json.loads(path.read_text(encoding="utf-8"))


def save_register(home: Path, register: dict) -> None:
    _write_json(home / REGISTER_FILE, register)


def _policy(data: dict) -> ClanPolicy:
    try:
        return ClanPolicy.create(
            network=data["network"],
            oversight=list(data["oversight"]),
            signers=list(data["signers"]),
            recovery_threshold=int(data["recovery_threshold"]),
            recovery_blocks=int(data["recovery_blocks"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise OversightError(f"This isn't a valid clan wallet: {exc}") from exc


def add_wallet(home: Path, clan_id: str, wallet: dict, code_from_phone: str) -> ClanPolicy:
    """Register a clan wallet after checking its code against a signatory's phone."""
    data = wallet.get("policy") or wallet
    policy = _policy(data)
    mine = public_key(home, policy.network)
    if mine not in {str(key) for key in policy.oversight}:
        raise OversightError("This wallet doesn't include this laptop's oversight key")
    # Read out by phone, so spaces or dashes between the characters don't matter.
    if "".join(code_from_phone.split()).replace("-", "").lower() != policy.wallet_code():
        raise OversightError(
            "The wallet code doesn't match the signatory's phone. Don't approve anything for "
            "this clan, and tell the clan and Afribit"
        )
    saved = {
        "network": policy.network,
        "oversight": [str(key) for key in policy.oversight],
        "signers": [str(key) for key in policy.signers],
        "recovery_threshold": policy.recovery_threshold,
        "recovery_blocks": policy.recovery_blocks,
    }
    register = load_register(home)
    generation = int(wallet.get("generation", 1))
    existing = register["wallets"].get(clan_id)
    if existing and existing["policy"] != saved and generation <= existing["generation"]:
        raise OversightError(
            "This clan already has a different wallet registered. A new wallet needs a new "
            "generation number"
        )
    earlier = list(existing.get("earlier", [])) if existing else []
    if existing and generation > existing["generation"]:
        # Kept, so the move from the old wallet to the new one can be checked and signed.
        earlier.append({key: value for key, value in existing.items() if key != "earlier"})
    register["wallets"][clan_id] = {
        "generation": generation,
        "policy": saved,
        "wallet_code": policy.wallet_code(),
        "clan_name": str(wallet.get("clan_name") or (existing or {}).get("clan_name") or ""),
        "added_at": _now(),
        "earlier": earlier,
    }
    save_register(home, register)
    return policy


def _generation(saved: dict, generation: int) -> dict | None:
    """The registered copy of one wallet generation of a clan, if this laptop has it."""
    for item in [saved, *saved.get("earlier", [])]:
        if item["generation"] == generation:
            return item
    return None


def fixed_start(address: str) -> str:
    """The start every address of its kind shares (bc1q, bc1p, tb1q...), so it isn't read back."""
    if address.lower().startswith(("tb1", "bc1", "bcrt1")):
        return address[: address.rfind("1") + 2]
    return address[:1]


def check_characters(address: str) -> tuple[str, str]:
    """The characters read back by phone: 6 after the fixed start (bc1q, bc1p...) and the last 6."""
    start = len(fixed_start(address))
    return address[start : start + CHECK_CHARACTERS], address[-CHECK_CHARACTERS:]


def confirm_address(
    home: Path, address: str, name: str, start_read: str, end_read: str, network: str = "signet"
) -> None:
    """Save a beneficiary address after they read its characters back by phone."""
    address = address.strip()
    try:
        bdk.Address(address, NETWORKS[network])
    except Exception as exc:
        raise OversightError("This isn't a valid address on the clan's network") from exc
    start, end = check_characters(address)
    if (start_read.strip(), end_read.strip()) != (start, end):
        raise OversightError(
            "The characters the beneficiary read don't match. Don't use this address. Ask "
            "them to check their wallet, and tell Afribit if it still differs"
        )
    register = load_register(home)
    register["addresses"][address] = {"name": name.strip(), "confirmed_at": _now()}
    save_register(home, register)


# ---------- payouts ----------


def clan_address(home: Path, clan_id: str, index: int = 0) -> str:
    """A clan receiving address computed from the registered wallet, never from the server.

    Afribit sends grant funding only to addresses from here. Index 0 is the clan's main address.
    """
    saved = load_register(home)["wallets"].get(clan_id)
    if not saved:
        raise OversightError("This clan's wallet isn't registered on this laptop. Run add-wallet")
    try:
        return ClanWallet(_policy(saved["policy"])).address(index)
    except ClanWalletError as exc:
        raise OversightError(str(exc)) from exc


def wallet_backup(home: Path, clan_id: str) -> dict:
    """The clan's public wallet backup, from the wallet registered on this laptop.

    It's the same file signatories save from their phones. With it and their 12 words they
    can recover the money on the recovery path without Clans or Afribit (clans.recover).
    """
    saved = load_register(home)["wallets"].get(clan_id)
    if not saved:
        raise OversightError("This clan's wallet isn't registered on this laptop. Run add-wallet")
    return recover.wallet_backup(
        _policy(saved["policy"]), generation=saved["generation"], clan_id=clan_id
    )


@dataclass(frozen=True)
class Review:
    clan_id: str
    txid: str
    fee_sats: int
    fee_paid_by: str
    lines: tuple[tuple[str, str, int, int], ...]  # name, address, approved, received
    total_sats: int
    large: bool
    replaces: tuple[str, ...]
    already_signed: bool
    kind: str = "grant"
    generation: int = 1
    # For a refresh or a move: the clan change address, from this laptop's own records.
    destination: str | None = None


def _inputs(psbt: bdk.Psbt) -> list[str]:
    tx = psbt.extract_tx_unchecked_fee_rate()
    return sorted(f"{item.previous_output.txid}:{item.previous_output.vout}" for item in tx.input())


def review(home: Path, payout: dict) -> Review:
    """Check a payout against this laptop's own records. Raises OversightError if it differs."""
    register = load_register(home)
    clan_id = str(payout.get("clan_id", ""))
    saved = register["wallets"].get(clan_id)
    if not saved:
        raise OversightError("This clan's wallet isn't registered on this laptop. Run add-wallet")
    try:
        generation = int(payout.get("generation") or saved["generation"])
    except (TypeError, ValueError) as exc:
        raise OversightError("The payout file is incomplete or damaged") from exc
    source = _generation(saved, generation)
    if not source:
        raise OversightError(
            f"Wallet {generation} of this clan isn't registered on this laptop. Run add-wallet"
        )
    policy = _policy(source["policy"])
    kind = payout.get("kind", "grant")
    if kind in {"refresh", "move"}:
        return _review_sweep(register, clan_id, saved, policy, generation, payout, kind)
    if kind != "grant":
        raise OversightError("Unknown kind of payment")
    fee_paid_by = payout.get("fee_paid_by", "clan")
    if fee_paid_by not in FEE_PAYERS:
        raise OversightError("Unknown fee rule")
    try:
        recipients = [
            (str(item.get("name", "")), Recipient(item["address"], int(item["approved_sats"])))
            for item in payout["recipients"]
        ]
        grants = [str(item["grant_id"]) for item in payout["recipients"]]
        psbt = bdk.Psbt(payout["psbt"])
        server_limit = int(payout["max_fee_sats"])
    except Exception as exc:
        raise OversightError("The payout file is incomplete or damaged") from exc
    if not recipients or len(set(grants)) != len(grants):
        raise OversightError("Each payout needs one line per grant")
    max_fee = min(server_limit, register["settings"]["max_fee_sats"])
    try:
        ClanWallet(policy).check_payout(
            payout["psbt"],
            [recipient for _, recipient in recipients],
            max_fee_sats=max_fee,
            fee_paid_by=fee_paid_by,
        )
    except ClanWalletError as exc:
        raise OversightError(str(exc)) from exc
    unconfirmed = [
        name or recipient.address
        for name, recipient in recipients
        if recipient.address not in register["addresses"]
    ]
    if unconfirmed:
        raise OversightError(
            "Confirm these addresses by phone first (confirm-address): " + ", ".join(unconfirmed)
        )
    txid = str(psbt.extract_tx_unchecked_fee_rate().compute_txid())
    inputs = set(_inputs(psbt))
    replaces = []
    already_signed = False
    for earlier in register["payouts"]:
        if earlier["txid"] == txid:
            already_signed = True
            continue
        overlap = set(earlier["grant_ids"]) & set(grants)
        if not overlap:
            continue
        if not inputs & set(earlier["inputs"]):
            raise OversightError(
                f"Grant {sorted(overlap)[0]} was already paid in payment {earlier['txid']}"
            )
        replaces.append(earlier["txid"])
    fee = psbt.fee()
    received = amounts_received([r for _, r in recipients], fee, fee_paid_by)
    lines = tuple(
        (name, recipient.address, recipient.amount_sats, paid.amount_sats)
        for (name, recipient), paid in zip(recipients, received, strict=True)
    )
    total = sum(recipient.amount_sats for _, recipient in recipients)
    return Review(
        clan_id=clan_id,
        txid=txid,
        fee_sats=fee,
        fee_paid_by=fee_paid_by,
        lines=lines,
        total_sats=total,
        large=total >= register["settings"]["large_payout_sats"],
        replaces=tuple(replaces),
        already_signed=already_signed,
        generation=generation,
    )


def _review_sweep(register, clan_id, saved, policy, generation, payout, kind) -> Review:
    """A refresh or move pays everything to one change address of a registered clan wallet.

    A refresh goes back to the same wallet. A move goes to a newer generation of the same
    clan, which must already be registered here after reading its code from a phone.
    """
    destination = payout.get("destination") or {}
    try:
        target_generation = int(destination["generation"])
        index = int(destination["index"])
        psbt = bdk.Psbt(payout["psbt"])
        server_limit = int(payout["max_fee_sats"])
    except Exception as exc:
        raise OversightError("The payout file is incomplete or damaged") from exc
    if destination.get("keychain", "internal") != "internal" or (
        target_generation != generation if kind == "refresh" else target_generation <= generation
    ):
        raise OversightError("This payment doesn't go to the clan's own wallet")
    target = _generation(saved, target_generation)
    if not target:
        raise OversightError(
            "Register the clan's new wallet first (add-wallet), after reading its code from "
            "a signatory's phone"
        )
    try:
        address = ClanWallet(_policy(target["policy"])).change_address(index)
    except ClanWalletError as exc:
        raise OversightError(str(exc)) from exc
    if destination.get("address", address) != address:
        raise OversightError("The destination doesn't match this laptop's copy of the clan wallet")
    settings = register["settings"]
    limit = settings.get("max_sweep_fee_sats", DEFAULT_SETTINGS["max_sweep_fee_sats"])
    try:
        amount = ClanWallet(policy).check_sweep(
            payout["psbt"], address, max_fee_sats=min(server_limit, limit)
        )
    except ClanWalletError as exc:
        raise OversightError(str(exc)) from exc
    txid = str(psbt.extract_tx_unchecked_fee_rate().compute_txid())
    inputs = set(_inputs(psbt))
    replaces = [
        earlier["txid"]
        for earlier in register["payouts"]
        if earlier["txid"] != txid and inputs & set(earlier["inputs"])
    ]
    label = (
        f"Move to the clan's new wallet ({target_generation})"
        if kind == "move"
        else "Refresh: back to the clan's own wallet"
    )
    return Review(
        clan_id=clan_id,
        txid=txid,
        fee_sats=psbt.fee(),
        fee_paid_by="clan",
        lines=((label, address, amount, amount),),
        total_sats=amount,
        large=amount >= settings["large_payout_sats"],
        replaces=tuple(replaces),
        already_signed=any(earlier["txid"] == txid for earlier in register["payouts"]),
        kind=kind,
        generation=generation,
        destination=address,
    )


def _signature_count(psbt: bdk.Psbt) -> int:
    return sum(
        len(item.get("tap_script_sigs") or [])
        for item in json.loads(psbt.json_serialize())["inputs"]
    )


def sign(home: Path, payout: dict, passphrase: str) -> tuple[str, bool]:
    """Review, then add this laptop's oversight signature.

    Returns the signed PSBT and whether the payment is now complete (clan signatures included).
    """
    checked = review(home, payout)
    register = load_register(home)
    saved = _generation(register["wallets"][checked.clan_id], checked.generation)
    policy = _policy(saved["policy"])
    key = unlock(home, passphrase, policy.network)
    public = str(key.as_public())

    def private(keychain: str) -> bdk.Descriptor:
        normal, _ = BRANCHES[keychain]
        text = policy.descriptor(keychain)
        target = f"{public}/{normal}/*"
        if text.count(target) != 1:
            raise OversightError("This laptop's key isn't an oversight key for this wallet")
        return bdk.Descriptor(
            text.replace(target, f"{key}/{normal}/*"), network_kind(policy.network)
        )

    signer = bdk.Wallet(
        private("external"),
        private("internal"),
        NETWORKS[policy.network],
        bdk.Persister.new_in_memory(),
    )
    copy = bdk.Psbt(payout["psbt"])
    before = _signature_count(copy)
    signer.sign(
        copy,
        bdk.SignOptions(
            trust_witness_utxo=False,
            assume_height=None,
            allow_all_sighashes=False,
            try_finalize=False,
            sign_with_tap_internal_key=False,
            allow_grinding=True,
        ),
    )
    if _signature_count(copy) <= before:
        raise OversightError("This laptop's key couldn't sign this payment")
    signed = copy.serialize()
    recipients = [Recipient(address, approved) for _, address, approved, _ in checked.lines]
    try:
        if checked.destination:
            ClanWallet(policy).finalize_sweep(
                payout["psbt"], [signed], checked.destination, max_fee_sats=checked.fee_sats
            )
        else:
            ClanWallet(policy).finalize(
                payout["psbt"],
                [signed],
                recipients,
                max_fee_sats=checked.fee_sats,
                fee_paid_by=checked.fee_paid_by,
            )
        complete = True
    except ClanWalletError:
        complete = False
    if not checked.already_signed:
        register["payouts"].append(
            {
                "txid": checked.txid,
                "clan_id": checked.clan_id,
                "kind": checked.kind,
                "grant_ids": [str(item["grant_id"]) for item in payout.get("recipients") or []],
                "inputs": _inputs(copy),
                "total_sats": checked.total_sats,
                "fee_sats": checked.fee_sats,
                "signed_at": _now(),
            }
        )
        save_register(home, register)
    return signed, complete


def signed_file(payout: dict, item: Review, signed: str) -> dict:
    """What gets uploaded: the oversight-signature route takes this as it is."""
    return {"id": payout.get("id"), "clan_id": item.clan_id, "txid": item.txid, "psbt": signed}


# ---------- the Clans server ----------
#
# The laptop downloads payouts with a read token of its own and uploads its signature. The
# token can only list payouts waiting for Afribit, so losing it reveals payout details but
# can't move money. Approval comes only from the oversight key, after the checks above.

SERVER_FILE = "server.json"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
SAFE_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def connect(home: Path, url: str) -> str:
    """Save the Clans address and make this laptop's read token.

    Returns the token's SHA-256, which goes in CLANS_CLAN_WALLET_OVERSIGHT_TOKEN_HASHES. The
    token itself stays on this laptop.
    """
    parts = urlsplit(url.strip())
    secure = parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in LOCAL_HOSTS)
    if (
        not secure
        or not parts.hostname
        or parts.username
        or parts.path not in {"", "/"}
        or parts.query
        or parts.fragment
    ):
        raise OversightError("Use the Clans address, for example https://clans.example.org")
    token = secrets.token_urlsafe(32)
    _write_json(
        home / SERVER_FILE,
        {"url": f"{parts.scheme}://{parts.netloc}", "token": token, "saved_at": _now()},
    )
    return hashlib.sha256(token.encode()).hexdigest()


def server(home: Path) -> httpx.Client:
    path = home / SERVER_FILE
    if not path.exists():
        raise OversightError("This laptop isn't connected to Clans yet. Run connect first")
    saved = json.loads(path.read_text(encoding="utf-8"))
    return httpx.Client(
        base_url=saved["url"],
        headers={"Authorization": "Bearer " + saved["token"]},
        timeout=30,
        follow_redirects=False,
    )


def _call(client: httpx.Client, method: str, path: str, **options):
    try:
        response = client.request(method, path, **options)
    except httpx.HTTPError as exc:
        raise OversightError(f"Couldn't reach Clans ({type(exc).__name__}). Try again") from exc
    if not response.is_success:
        try:
            detail = response.json().get("detail")
        except Exception:
            detail = None
        raise OversightError(
            f"Clans refused this ({response.status_code}): {detail or 'no reason'}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise OversightError("Clans sent an unreadable answer") from exc


def pending(client: httpx.Client) -> list[dict]:
    """Payouts the clan has signed that wait for Afribit."""
    payouts = _call(client, "GET", "/api/oversight/payouts")
    if not isinstance(payouts, list):
        raise OversightError("Clans sent an unreadable answer")
    return payouts


def alarms(client: httpx.Client, since: str | None = None) -> list[dict]:
    """Alarms about every clan's wallets, newest first; only those after `since` if given."""
    found = _call(client, "GET", "/api/oversight/alarms", params={"since": since} if since else {})
    if not isinstance(found, list):
        raise OversightError("Clans sent an unreadable answer")
    return found


def wallets(client: httpx.Client) -> list[dict]:
    """Every clan's active wallet, as the server describes it. Checked by phone before use."""
    found = _call(client, "GET", "/api/oversight/wallets")
    if not isinstance(found, list):
        raise OversightError("The server sent an unexpected list of wallets")
    return found


def unregistered(home: Path, client: httpx.Client, clan_id: str | None = None) -> list[dict]:
    """Active clan wallets the server lists that this laptop hasn't registered yet."""
    registered = load_register(home)["wallets"]
    return [
        item
        for item in wallets(client)
        if (not clan_id or item["clan_id"] == clan_id)
        and registered.get(item["clan_id"], {}).get("generation") != item["generation"]
    ]


def register_from_server(home: Path, client: httpx.Client, clan_id: str | None = None) -> int:
    """Ask for each new wallet's code, read from a signatory's phone. Returns how many failed."""
    todo = unregistered(home, client, clan_id)
    if not todo:
        print("Every active clan wallet is already registered on this laptop.")
    failed = 0
    for item in todo:
        name = item.get("clan_name") or item["clan_id"]
        print(f"\n{name} (clan {item['clan_id']}), wallet {item['generation']}.")
        print("Phone one of its signatories. Ask them to read the wallet code on their phone.")
        try:
            policy = add_wallet(home, item["clan_id"], item, input("Wallet code: "))
        except OversightError as exc:
            print(f"Not registered: {exc}.")
            failed += 1
            continue
        print(f"Registered: {policy.threshold} of {len(policy.signers)} signatories.")
    return failed


def unread_alarms(home: Path, client: httpx.Client) -> list[dict]:
    return alarms(client, load_register(home).get("alarms_seen_at"))


def mark_alarms_read(home: Path, found: list[dict]) -> None:
    if not found:
        return
    register = load_register(home)
    newest = max(item["created_at"] for item in found)
    register["alarms_seen_at"] = max(newest, register.get("alarms_seen_at") or "")
    save_register(home, register)


def _show_alarms(found: list[dict]) -> None:
    for item in sorted(found, key=lambda alarm: alarm["created_at"]):
        clan = item.get("clan_name") or item["clan_id"]
        print(
            f"\n[{item['created_at'][:16]}] {clan}, wallet {item.get('generation')}: {item['kind']}"
        )
        print(f"  {item['message']}")
        if item.get("detail"):
            print("  " + ", ".join(f"{key}={value}" for key, value in item["detail"].items()))


def upload(client: httpx.Client, signed: dict) -> dict:
    """Send this laptop's signed copy back to Clans."""
    if not all(isinstance(signed.get(name), str) for name in ("id", "clan_id", "txid", "psbt")):
        raise OversightError("The signed file is incomplete")
    if not SAFE_ID.match(signed["id"]) or not SAFE_ID.match(signed["clan_id"]):
        raise OversightError("The signed file is damaged")
    route = f"/api/clans/{signed['clan_id']}/wallet/payouts/{signed['id']}/oversight-signature"
    return _call(client, "POST", route, json=signed)


# ---------- command line ----------


def _ask_passphrase(confirm: bool = False) -> str:
    value = getpass.getpass("Oversight passphrase: ")
    if confirm and getpass.getpass("Type it again: ") != value:
        raise OversightError("The passphrases don't match")
    return value


def _show(item: Review, clan_name: str | None = None) -> None:
    print(f"\nClan: {clan_name or item.clan_id}")
    print(f"Payment: {item.txid}")
    for name, address, approved, received in item.lines:
        start, end = check_characters(address)
        print(f"  {name or 'Beneficiary'}: approved {approved:,} sats, receives {received:,}")
        print(f"    to {address}  (check: {start} ... {end})")
    if item.kind != "grant":
        print("No beneficiary: the clan's money stays in the clan's own wallets.")
    payer = "the beneficiaries" if item.fee_paid_by == "recipients" else "the clan"
    print(f"Network fee: {item.fee_sats:,} sats, paid by {payer}")
    print(f"Total approved: {item.total_sats:,} sats")
    if item.replaces:
        print("This is a higher-fee version of " + ", ".join(item.replaces))
    if item.already_signed:
        print("This laptop already signed this exact payment.")


def _read_payout(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _agreed(item: Review) -> bool:
    """Ask the person to approve what `_show` printed. Large payouts need the total typed."""
    if item.large:
        typed = input("\nLarge payout. Type the total approved sats to continue: ")
        if typed.replace(",", "").strip() != str(item.total_sats):
            raise OversightError("The amount doesn't match. Nothing was signed")
        return True
    if input("\nSign this payment? Type yes: ").strip().lower() != "yes":
        print("Nothing was signed.")
        return False
    return True


def _approve(home: Path, client: httpx.Client, payout: dict) -> bool:
    """Check, ask, sign and upload one downloaded payout. Returns True if it was signed."""
    try:
        item = review(home, payout)
    except OversightError as exc:
        print(f"\nPayout {payout.get('id')}: stopped: {exc}", file=sys.stderr)
        return False
    _show(item)
    if not _agreed(item):
        return False
    signed, _ = sign(home, payout, _ask_passphrase())
    result = upload(client, signed_file(payout, item, signed))
    got = result.get("signatures", {})
    print(
        f"Signed and uploaded. Clan signatures {got.get('count')} of {got.get('required')}. "
        "Clans sends the payment within a minute."
    )
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m clans.oversight",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--home", type=Path, default=default_home(), help="data folder")
    parser.add_argument("--url", help="the Clans address the guided setup suggests")
    # Without a command, the guided app walks the person through setup and approvals.
    commands = parser.add_subparsers(dest="command")
    create = commands.add_parser("create-key", help="create this laptop's oversight key")
    create.add_argument("--restore", action="store_true", help="restore from backup words")
    shown = commands.add_parser("show-key", help="print the public key for the Clans settings")
    shown.add_argument("--network", default="bitcoin", choices=sorted(NETWORKS))
    wallet = commands.add_parser("add-wallet", help="register clan wallets, checked by phone")
    wallet.add_argument("--clan", help="only this clan")
    wallet.add_argument(
        "file", nargs="?", help="the clan's wallet details (JSON), if this laptop is offline"
    )
    address = commands.add_parser("confirm-address", help="save a beneficiary address")
    address.add_argument("--name", required=True)
    address.add_argument("--network", default="bitcoin", choices=sorted(NETWORKS))
    address.add_argument("address")
    check = commands.add_parser("review", help="check a payout without signing")
    check.add_argument("file")
    approve = commands.add_parser("sign", help="check and sign a payout")
    approve.add_argument("file")
    approve.add_argument("--out", required=True, help="where to write the signed payout")
    limits = commands.add_parser("set-limits", help="change this laptop's limits")
    limits.add_argument("--max-fee", type=int)
    limits.add_argument("--max-sweep-fee", type=int)
    limits.add_argument("--large-payout", type=int)
    funding = commands.add_parser("clan-address", help="a clan address for Afribit funding")
    funding.add_argument("--clan", required=True)
    funding.add_argument("--index", type=int, default=0)
    export = commands.add_parser("export-backup", help="write a clan's public wallet backup")
    export.add_argument("--clan", required=True)
    export.add_argument("--out", required=True)
    commands.add_parser("status", help="show registered wallets, addresses and payouts")
    link = commands.add_parser("connect", help="connect this laptop to Clans")
    link.add_argument("url", help="the Clans address, for example https://clans.example.org")
    commands.add_parser("pending", help="list payouts waiting for Afribit")
    show_alarms = commands.add_parser("alarms", help="show alarms about clan wallets")
    show_alarms.add_argument("--all", action="store_true", help="include ones already read")
    approve_all = commands.add_parser("approve", help="check, sign and upload waiting payouts")
    approve_all.add_argument("--id", help="only this payout")
    send = commands.add_parser("upload", help="upload a signed file made with sign")
    send.add_argument("file")
    args = parser.parse_args(argv)
    home: Path = args.home
    if args.command is None:
        from clans import oversight_guide

        return oversight_guide.run(home, args.url)

    try:
        if args.command == "create-key":
            words = None
            if args.restore:
                words = getpass.getpass("Backup words (hidden): ")
            words, public = create_key(home, _ask_passphrase(confirm=True), words)
            if not args.restore:
                print("\nWrite these 12 backup words on paper and keep them in a safe place.")
                print("Anyone with them can approve payouts as you. Never type them anywhere else.")
                print("\n  " + words + "\n")
                input("Press Enter once they're written down.")
                print("\n" * 40)
            print("Oversight public key (add this to CLANS_CLAN_WALLET_OVERSIGHT_KEYS):")
            print(public)
        elif args.command == "show-key":
            if args.network == "bitcoin" and "mainnet_public_key" not in _key_file(home):
                unlock(home, _ask_passphrase(), "bitcoin")
            print(public_key(home, args.network))
        elif args.command == "add-wallet" and not args.file:
            with server(home) as client:
                if register_from_server(home, client, args.clan):
                    raise OversightError("Some wallets weren't registered")
        elif args.command == "add-wallet":
            if not args.clan:
                raise OversightError("Give --clan with a wallet details file")
            data = json.loads(Path(args.file).read_text(encoding="utf-8"))
            code = input("Wallet code read from a signatory's phone: ")
            policy = add_wallet(home, args.clan, data, code)
            print(
                f"Registered. Wallet code {policy.wallet_code()}, "
                f"{policy.threshold} of {len(policy.signers)} signatories."
            )
        elif args.command == "confirm-address":
            start, end = check_characters(args.address)
            print(f"Phone {args.name}. Ask them to open their wallet and read:")
            print(f"  the 6 characters after {fixed_start(args.address)}, then the last 6.")
            start_read = input("First 6 they read: ")
            end_read = input("Last 6 they read: ")
            confirm_address(home, args.address, args.name, start_read, end_read, args.network)
            print("Address saved.")
        elif args.command == "review":
            _show(review(home, _read_payout(args.file)))
            print("\nAll checks passed. Nothing was signed.")
        elif args.command == "sign":
            payout = _read_payout(args.file)
            item = review(home, payout)
            _show(item)
            if not _agreed(item):
                return 1
            signed, complete = sign(home, payout, _ask_passphrase())
            Path(args.out).write_text(
                json.dumps(signed_file(payout, item, signed)), encoding="utf-8"
            )
            state = "complete and ready to broadcast" if complete else "still waiting for the clan"
            print(f"Signed: {args.out}. The payment is {state}.")
        elif args.command == "set-limits":
            register = load_register(home)
            if args.max_fee is not None:
                register["settings"]["max_fee_sats"] = max(1, args.max_fee)
            if args.max_sweep_fee is not None:
                register["settings"]["max_sweep_fee_sats"] = max(1, args.max_sweep_fee)
            if args.large_payout is not None:
                register["settings"]["large_payout_sats"] = max(1, args.large_payout)
            save_register(home, register)
            print(json.dumps(register["settings"], indent=2))
        elif args.command == "clan-address":
            address = clan_address(home, args.clan, args.index)
            start, end = check_characters(address)
            print(address)
            print(f"Check on the sending wallet: {start} ... {end}")
        elif args.command == "export-backup":
            backup = wallet_backup(home, args.clan)
            _write_json(Path(args.out), backup)
            print(f"Saved the backup of wallet {backup['wallet_code']} to {args.out}.")
            print("It holds public keys only. Give it to the clan's signatories.")
        elif args.command == "status":
            register = load_register(home)
            print(f"Key: {public_key(home)}")
            print(f"Limits: {register['settings']}")
            for clan_id, saved in register["wallets"].items():
                print(f"Clan {clan_id}: wallet {saved['wallet_code']} (gen {saved['generation']})")
            for address, saved in register["addresses"].items():
                print(f"Address {saved['name']}: {address}")
            for payout in register["payouts"][-10:]:
                print(f"Signed {payout['signed_at']}: {payout['txid']} ({payout['total_sats']:,})")
        elif args.command == "connect":
            digest = connect(home, args.url)
            print("Connected. Give this line to the Clans administrator, to add to")
            print("CLANS_CLAN_WALLET_OVERSIGHT_TOKEN_HASHES (it lets this laptop list payouts):")
            print(digest)
        elif args.command == "pending":
            with server(home) as client:
                waiting = pending(client)
                unread = unread_alarms(home, client)
            registered = load_register(home)["wallets"]
            if unread:
                print(f"{len(unread)} new alarm(s). Read them with: alarms\n")
            for payout in waiting:
                known = "" if payout["clan_id"] in registered else "  (clan not registered here)"
                if payout.get("kind", "grant") != "grant":
                    what = f"{payout['kind']} of wallet {payout.get('generation')}"
                else:
                    total = sum(int(item["approved_sats"]) for item in payout["recipients"])
                    names = ", ".join(
                        item.get("name") or "Beneficiary" for item in payout["recipients"]
                    )
                    what = f"{total:,} sats to {names}"
                print(f"{payout['id']}  clan {payout['clan_id']}  {what}{known}")
            print(f"{len(waiting)} payout(s) waiting for Afribit.")
        elif args.command == "alarms":
            with server(home) as client:
                found = alarms(client) if args.all else unread_alarms(home, client)
            _show_alarms(found)
            mark_alarms_read(home, found)
            print(f"\n{len(found)} alarm(s).")
        elif args.command == "approve":
            with server(home) as client:
                unread = unread_alarms(home, client)
                if unread:
                    # Read these before signing: one may mean a clan's wallet is compromised.
                    print("New alarms since you last looked:")
                    _show_alarms(unread)
                    if input("\nContinue to the payouts? Type yes: ").strip().lower() != "yes":
                        raise OversightError("Nothing was signed")
                    mark_alarms_read(home, unread)
                waiting = [p for p in pending(client) if not args.id or p["id"] == args.id]
                if args.id and not waiting:
                    raise OversightError("That payout isn't waiting for Afribit")
                done = sum(_approve(home, client, payout) for payout in waiting)
            print(f"\n{done} of {len(waiting)} payout(s) signed.")
        elif args.command == "upload":
            with server(home) as client:
                result = upload(client, _read_payout(args.file))
            print(
                f"Uploaded. Clan signatures {result['signatures']['count']} of "
                f"{result['signatures']['required']}."
            )
    except OversightError as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
