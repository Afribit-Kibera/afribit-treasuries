"""Offline-approved clan signer keys, outside the web database's write authority.

The operator signs a reviewed manifest on a separate trusted machine. Only its
public verification key and signed manifests reach the worker. No automatic
trust-on-first-use or database-derived approval is permitted in production.
"""

import hashlib
import json
import os
import stat
from datetime import UTC, datetime, timedelta
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy import select

from clans.live_models import Passkey, SignerApproval
from clans.live_security import unb64
from clans.money_service import canonical_json
from clans.treasury_provider import PayoutDeferred, ProviderError

DOMAIN = "afribit-clan-trust-v1"


def required(settings):
    return settings.environment == "production" or settings.signer_trust_required


def validate_trust_settings(settings):
    if not required(settings):
        return
    try:
        Ed25519PublicKey.from_public_bytes(unb64(settings.signer_trust_public_key))
        if not settings.signer_trust_directory or not settings.signer_trust_directory.is_dir():
            raise ValueError
        if settings.environment == "production":
            directory = settings.signer_trust_directory
            if (
                directory.is_symlink()
                or directory.stat().st_uid != 0
                or directory.stat().st_mode & 0o022
            ):
                raise ValueError
    except (ValueError, OSError) as exc:
        raise ValueError(
            "Treasury requires root-protected offline signer trust configuration"
        ) from exc


def fingerprint(public_key):
    return hashlib.sha256(unb64(public_key)).hexdigest()


def validate_manifest(manifest, settings, grant, *, at=None):
    at = at or datetime.now(UTC)
    issued = datetime.fromisoformat(manifest["issued_at"])
    expires = datetime.fromisoformat(manifest["expires_at"])
    if (
        manifest["domain"] != DOMAIN
        or manifest["namespace"] != settings.provider_namespace
        or manifest["clan_id"] != grant.clan_id
        or manifest["node"] != settings.expected_node_pubkey
        or manifest["store"] != settings.btcpay_store_id
        or manifest["policy"] != grant.policy_snapshot
        or issued > at + timedelta(minutes=5)
        or expires <= at
        or expires <= issued
        or expires - issued > timedelta(days=7)
        or sorted(set(manifest["signers"]) - {grant.beneficiary_id})
        != sorted(grant.eligible_signers)
        or len(set(manifest["members"])) != len(manifest["members"])
        or not set(grant.eligible_voters).issubset(manifest["members"])
        or grant.beneficiary_id not in manifest["members"]
        or len(manifest["signers"]) not in {3, 5, 7}
        or not set(manifest["signers"]).issubset(manifest["members"])
        or manifest["policy"]["threshold"] != len(manifest["signers"]) // 2 + 1
    ):
        raise ValueError("Manifest does not authorize this clan policy and roster")


def verify_signer_trust(db, settings, grant, intent, approvals):
    """Verify the actual approved keys against an independently signed roster."""
    if not required(settings):
        return
    try:
        validate_trust_settings(settings)
    except ValueError as exc:
        raise ProviderError("Independent signer trust configuration needs review") from exc
    try:
        UUID(grant.clan_id)
        path = settings.signer_trust_directory / (grant.clan_id + ".json")
        if path.is_symlink():
            raise ValueError
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 131_072:
                raise ValueError
            if settings.environment == "production" and (info.st_uid != 0 or info.st_mode & 0o022):
                raise ValueError
            envelope = json.loads(source.read(131_073))
        manifest = envelope["manifest"]
        Ed25519PublicKey.from_public_bytes(unb64(settings.signer_trust_public_key)).verify(
            unb64(envelope["signature"]), canonical_json(manifest).encode()
        )
        validate_manifest(manifest, settings, grant)
        for user_id in approvals:
            approval = db.scalar(
                select(SignerApproval).where(
                    SignerApproval.intent_id == intent.id, SignerApproval.user_id == user_id
                )
            )
            key = db.get(Passkey, approval.passkey_id)
            pinned = manifest["signers"][user_id]
            if not any(
                pin["credential_id"] == key.credential_id
                and pin["public_key_sha256"] == fingerprint(key.public_key)
                for pin in pinned
            ):
                raise ValueError("Signatory key is not independently approved")
        return hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
    except (InvalidSignature, KeyError, TypeError, ValueError, OSError) as exc:
        # Do not leak paths, credentials or manifest contents into worker logs.
        raise PayoutDeferred(
            "Independent clan signer trust needs operator review", "clan_verification_required"
        ) from exc
