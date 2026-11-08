"""Clan wallet money records shared by the web app and the chain watcher.

The web app hands out addresses, records beneficiary addresses and stores signed copies of
payouts. Only the chain watcher credits money, builds payouts, checks signatures and
broadcasts. Neither holds a key that can spend.
"""

import base64
import hashlib
import json
from dataclasses import dataclass

import bdkpython as bdk
from coincurve import PublicKeyXOnly
from sqlalchemy import select

from clans.clan_wallet import BRANCHES, SAT_KWU_PER_SAT_VB, ClanPolicy, ClanWalletError
from clans.models import Clan, User, now_iso
from clans.wallet_models import (
    ClanWalletRecord,
    WalletAlarm,
    WalletPayout,
    WalletSignature,
    WalletSignerKey,
)

# A payment counts once it has this many confirmations, unless the settings say otherwise
# (CLANS_CLAN_WALLET_CONFIRMATIONS).
CONFIRMATIONS = 3
# Confirmed receipts and payouts are rechecked until this deep, to catch reorganisations.
REORG_DEPTH = 6
# Branches that sign on the normal path. Recovery-path signatures are never collected.
NORMAL_BRANCHES = {str(BRANCHES["external"][0]), str(BRANCHES["internal"][0])}


def record_policy(db, record: ClanWalletRecord) -> ClanPolicy:
    """Rebuild the wallet from its stored keys and check it matches what was confirmed."""
    keys = db.scalars(select(WalletSignerKey).where(WalletSignerKey.wallet_id == record.id))
    policy = ClanPolicy.create(
        network=record.network,
        oversight=list(record.oversight_keys),
        signers=sorted(key.key_expression for key in keys),
        recovery_threshold=record.recovery_threshold,
        recovery_blocks=record.recovery_blocks,
    )
    if (
        policy.descriptor("external") != record.descriptor_external
        or policy.wallet_code() != record.wallet_code
    ):
        raise ClanWalletError("The stored wallet doesn't match its keys")
    return policy


def actor(db, clan_id, user_id=None):
    """Who an event is shown under. Events with no person go under the clan's organizer,
    with `source` in the payload saying what really did it."""
    return user_id or db.get(Clan, clan_id).created_by


def alarm(db, record, kind, reference, **detail):
    """Record an alarm once. Returns True the first time."""
    if db.scalar(
        select(WalletAlarm.id).where(WalletAlarm.kind == kind, WalletAlarm.reference == reference)
    ):
        return False
    db.add(WalletAlarm(wallet_id=record.id, kind=kind, reference=reference, detail=detail))
    from clans.live_app import audit

    audit(
        db,
        record.clan_id,
        actor(db, record.clan_id),
        "wallet_alarm_" + kind,
        source="chain_watcher",
        reference=reference,
        **detail,
    )
    return True


def psbt_details(psbt_base64: str) -> dict:
    try:
        base64.b64decode(psbt_base64, validate=True)
        return json.loads(bdk.Psbt(psbt_base64).json_serialize())
    except Exception as exc:
        raise ClanWalletError("The payment data is not a valid PSBT") from exc


def txid_of(psbt_base64: str) -> str:
    try:
        return str(bdk.Psbt(psbt_base64).extract_tx_unchecked_fee_rate().compute_txid())
    except Exception as exc:
        raise ClanWalletError("The payment data is not a valid PSBT") from exc


def key_origins(details: dict) -> dict[str, tuple[str, str]]:
    """x-only key -> (fingerprint, path) for every key the payment can be signed with."""
    origins = {}
    for item in details.get("inputs", []):
        for xonly, (_, (fingerprint, path)) in item.get("tap_key_origins") or []:
            origins[xonly] = (fingerprint, path)
    return origins


def signature_set(details: dict) -> set[tuple[int, str, str, str]]:
    """(input index, x-only key, leaf hash, signature) for every script signature present.

    Signatures with any hash type other than the two that commit to the whole payment are
    returned with their type appended, so they never match a checked signature.
    """
    found = set()
    for position, item in enumerate(details.get("inputs", [])):
        for (xonly, leaf), value in item.get("tap_script_sigs") or []:
            signature = value["signature"]
            if value.get("sighash_type") not in SIGHASH_TYPES:
                signature += ":" + str(value.get("sighash_type"))
            found.add((position, xonly, leaf, signature))
    return found


# Hash types that commit to every input and output. SIGHASH_DEFAULT is a 64-byte signature.
SIGHASH_TYPES = {"SIGHASH_DEFAULT": 0x00, "SIGHASH_ALL": 0x01}


def _tagged_hash(tag: str, data: bytes) -> bytes:
    tag_hash = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(tag_hash + tag_hash + data).digest()


def _with_length(data: bytes) -> bytes:
    size = len(data)
    if size < 0xFD:
        return bytes([size]) + data
    if size <= 0xFFFF:
        return b"\xfd" + size.to_bytes(2, "little") + data
    return b"\xfe" + size.to_bytes(4, "little") + data


def script_path_sighash(details: dict, position: int, leaf_hash: str, hash_type: int) -> bytes:
    """The BIP-341/342 message a script-path signature on input `position` signs.

    Only SIGHASH_DEFAULT and SIGHASH_ALL are supported: no annex, no code separator.
    """
    tx = details["unsigned_tx"]
    inputs = details["inputs"]
    if len(inputs) != len(tx["input"]) or any(not i.get("witness_utxo") for i in inputs):
        raise ClanWalletError("The payment data is missing the coins it spends")
    prevouts = b"".join(
        bytes.fromhex(txid)[::-1] + int(vout).to_bytes(4, "little")
        for txid, vout in (item["previous_output"].split(":") for item in tx["input"])
    )
    amounts = b"".join(int(i["witness_utxo"]["value"]).to_bytes(8, "little") for i in inputs)
    scripts = b"".join(
        _with_length(bytes.fromhex(i["witness_utxo"]["script_pubkey"])) for i in inputs
    )
    sequences = b"".join(int(item["sequence"]).to_bytes(4, "little") for item in tx["input"])
    outputs = b"".join(
        int(item["value"]).to_bytes(8, "little")
        + _with_length(bytes.fromhex(item["script_pubkey"]))
        for item in tx["output"]
    )
    message = (
        bytes([0x00, hash_type])  # epoch, hash type
        + int(tx["version"]).to_bytes(4, "little", signed=True)
        + int(tx["lock_time"]).to_bytes(4, "little")
        + hashlib.sha256(prevouts).digest()
        + hashlib.sha256(amounts).digest()
        + hashlib.sha256(scripts).digest()
        + hashlib.sha256(sequences).digest()
        + hashlib.sha256(outputs).digest()
        + bytes([0x02])  # script path, no annex
        + position.to_bytes(4, "little")
        + bytes.fromhex(leaf_hash)
        + b"\x00"  # key version
        + b"\xff\xff\xff\xff"  # no code separator
    )
    return _tagged_hash("TapSighash", message)


def check_signatures(details: dict, base: dict) -> None:
    """Raise unless every script signature in `details` is valid for the payment in `base`.

    `base` is the server's own copy, so amounts and scripts come from data the uploader
    can't change. Each signature must use a leaf its key really belongs to.
    """
    leaves = {}
    for position, item in enumerate(base.get("inputs", [])):
        for xonly, (leaf_hashes, _) in item.get("tap_key_origins") or []:
            leaves[(position, xonly)] = set(leaf_hashes)
    for position, item in enumerate(details.get("inputs", [])):
        for (xonly, leaf), value in item.get("tap_script_sigs") or []:
            hash_type = SIGHASH_TYPES.get(value.get("sighash_type"))
            if hash_type is None:
                raise ClanWalletError("Sign with the default signature type")
            if leaf not in leaves.get((position, xonly), ()):
                raise ClanWalletError("The signed copy contains signatures from other keys")
            message = script_path_sighash(base, position, leaf, hash_type)
            try:
                valid = PublicKeyXOnly(bytes.fromhex(xonly)).verify(
                    bytes.fromhex(value["signature"]), message
                )
            except Exception:
                valid = False
            if not valid:
                raise ClanWalletError("A signature doesn't match this payment. Sign it again.")


@dataclass(frozen=True)
class Signed:
    signers: tuple[str, ...]  # fingerprints of signatories with a valid signature
    oversight: bool
    rows: tuple[WalletSignature, ...]


def signatures(db, payout: WalletPayout) -> Signed:
    rows = db.scalars(
        select(WalletSignature)
        .where(WalletSignature.payout_id == payout.id, WalletSignature.invalid_at.is_(None))
        .order_by(WalletSignature.created_at)
    ).all()
    return Signed(
        signers=tuple(sorted(r.fingerprint for r in rows if r.role == "signer")),
        oversight=any(r.role == "oversight" for r in rows),
        rows=tuple(rows),
    )


def combined_psbt(payout: WalletPayout, rows) -> str:
    """The server's own payment with every accepted signature added."""
    combined = bdk.Psbt(payout.psbt)
    for row in rows:
        combined = combined.combine(bdk.Psbt(row.psbt))
    return combined.serialize()


def view_status(payout: WalletPayout, signed: Signed, required: int) -> str:
    if payout.status != "awaiting_signatures":
        return payout.status
    if len(signed.signers) < required:
        return "awaiting_signatures"
    return "broadcasting" if signed.oversight else "awaiting_oversight"


def payout_view(db, payout: WalletPayout, policy: ClanPolicy, user_id: str | None):
    signed = signatures(db, payout)
    mine = None
    if user_id:
        mine = db.scalar(
            select(WalletSignerKey.fingerprint).where(
                WalletSignerKey.wallet_id == payout.wallet_id, WalletSignerKey.user_id == user_id
            )
        )
    names = [
        db.get(User, row.user_id).display_name
        for row in signed.rows
        if row.role == "signer" and row.user_id
    ]
    source = db.get(ClanWalletRecord, payout.wallet_id)
    destination = None
    if payout.kind != "grant":
        target = db.get(ClanWalletRecord, payout.to_wallet_id)
        # Phones and oversight laptops derive this address from their own saved copy of
        # that wallet generation before signing. The server's copy is only for display.
        destination = {
            "generation": target.generation,
            "keychain": "internal",
            "index": payout.destination_index,
            "address": payout.destination_address,
        }
    return {
        "id": payout.id,
        "clan_id": payout.clan_id,
        "kind": payout.kind,
        # The wallet generation the coins come from. Sign with that generation's saved copy.
        "generation": source.generation,
        "destination": destination,
        "status": view_status(payout, signed, policy.threshold),
        # Includes the signatures collected so far. Phones review it before adding theirs.
        "psbt": combined_psbt(payout, signed.rows),
        "txid": payout.txid,
        "fee_paid_by": payout.fee_paid_by,
        "fee_sats": payout.fee_sats,
        "max_fee_sats": payout.max_fee_sats,
        "fee_rate_sat_vb": (
            payout.fee_rate_sat_kwu / SAT_KWU_PER_SAT_VB
            if payout.fee_rate_sat_kwu
            else payout.fee_rate_sat_vb
        ),
        "recipients": payout.recipients,
        "signatures": {
            "count": len(signed.signers),
            "required": policy.threshold,
            "signed_by_me": mine is not None and mine in signed.signers,
            "names": names,
        },
        "oversight_signed": signed.oversight,
        "replaces": payout.replaces,
        "replaced_by": payout.replaced_by,
        "created_at": payout.created_at,
        "broadcast_txid": payout.txid if payout.status in {"broadcast", "confirmed"} else None,
        "confirmations": payout.confirmations,
    }


def accept_signature(db, payout: WalletPayout, uploaded: str, allowed: dict) -> WalletSignature:
    """Store a signed copy of a payout.

    `allowed` maps the fingerprints this uploader may sign with to (role, user_id). Every
    signature in the copy must be either one already accepted or from an allowed key, on the
    normal path, for every input, and new signatures must be valid for this payment. The
    chain watcher checks them again with BDK before anything is broadcast.
    """
    if txid_of(uploaded) != payout.txid:
        raise ClanWalletError("This signature is for a different payment")
    base = psbt_details(payout.psbt)
    origins = key_origins(base)
    accepted = set()
    for row in signatures(db, payout).rows:
        accepted |= signature_set(psbt_details(row.psbt))
    added: dict[str, set[int]] = {}
    for position, xonly, leaf, signature in signature_set(psbt_details(uploaded)):
        if (position, xonly, leaf, signature) in accepted:
            continue
        fingerprint, path = origins.get(xonly, (None, ""))
        steps = path.split("/")
        if fingerprint not in allowed or len(steps) < 2 or steps[-2] not in NORMAL_BRANCHES:
            raise ClanWalletError("The signed copy contains signatures from other keys")
        added.setdefault(fingerprint, set()).add(position)
    if len(added) > 1:
        raise ClanWalletError("Upload one signature at a time")
    if not added:
        existing = db.scalar(
            select(WalletSignature).where(
                WalletSignature.payout_id == payout.id,
                WalletSignature.fingerprint.in_(list(allowed)),
                WalletSignature.invalid_at.is_(None),
            )
        )
        if existing:
            return existing
        raise ClanWalletError("The signed copy doesn't include your signature")
    fingerprint, positions = next(iter(added.items()))
    if positions != set(range(len(base.get("inputs", [])))):
        raise ClanWalletError("Sign every part of the payment")
    role, user_id = allowed[fingerprint]
    # Keep only this key's signatures, so a bad signature lives in exactly one row and
    # dropping that row removes it.
    own = only_signatures_from(
        uploaded, {xonly for xonly, (fp, _) in origins.items() if fp == fingerprint}
    )
    # Checked now, so a forged copy can't replace a good one. The chain watcher checks
    # again with BDK before broadcasting.
    check_signatures(psbt_details(own), base)
    row = db.scalar(
        select(WalletSignature).where(
            WalletSignature.payout_id == payout.id, WalletSignature.fingerprint == fingerprint
        )
    )
    if row:
        row.psbt, row.invalid_at, row.created_at = own, None, now_iso()
    else:
        row = WalletSignature(
            payout_id=payout.id, fingerprint=fingerprint, role=role, user_id=user_id, psbt=own
        )
        db.add(row)
    db.flush()
    return row


TAP_SCRIPT_SIG = 0x14  # BIP-371 PSBT_IN_TAP_SCRIPT_SIG: key = type, x-only key, leaf hash


def _compact_size(data: bytes, at: int) -> tuple[int, int]:
    first = data[at]
    if first < 0xFD:
        return first, at + 1
    width = {0xFD: 2, 0xFE: 4, 0xFF: 8}[first]
    return int.from_bytes(data[at + 1 : at + 1 + width], "little"), at + 1 + width


def only_signatures_from(psbt_base64: str, keys: set[str]) -> str:
    """A copy of the PSBT with every script signature removed except those by `keys`.

    BDK can't edit signatures from Python, so this walks the BIP-174 key-value maps and drops
    input entries of type PSBT_IN_TAP_SCRIPT_SIG for other keys. Everything else is kept.
    """
    raw = base64.b64decode(psbt_base64, validate=True)
    if raw[:5] != b"psbt\xff":
        raise ClanWalletError("The payment data is not a valid PSBT")
    inputs = len(bdk.Psbt(psbt_base64).extract_tx_unchecked_fee_rate().input())
    kept, at, section = bytearray(raw[:5]), 5, 0
    try:
        while at < len(raw):
            length, start = _compact_size(raw, at)
            if length == 0:
                kept.append(0)
                at, section = start, section + 1
                continue
            key = raw[start : start + length]
            size, value = _compact_size(raw, start + length)
            end = value + size
            if end > len(raw):
                raise ValueError
            foreign = (
                1 <= section <= inputs and key[0] == TAP_SCRIPT_SIG and key[1:33].hex() not in keys
            )
            if not foreign:
                kept += raw[at:end]
            at = end
    except (IndexError, KeyError, ValueError) as exc:
        raise ClanWalletError("The payment data is not a valid PSBT") from exc
    result = base64.b64encode(bytes(kept)).decode()
    if txid_of(result) != txid_of(psbt_base64):
        raise ClanWalletError("The payment data is not a valid PSBT")
    return result
