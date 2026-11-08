"""Clan wallet setup: signatories register public keys from their phones and confirm the
wallet code. The server only ever sees public keys and cannot spend.

Phones must not trust this API. Each phone rebuilds the wallet from the keys returned
here, checks its own key is included and shows its own wallet code for comparison.

A clan moves to a new wallet generation when a key must change (a stolen phone, a lost
backup, a new signatory or a new Afribit key). Any signatory starts it; every signatory
registers a key and confirms the new code, exactly as at first setup. The current wallet
keeps working until then. Once the new one is active, the old one is retired and the chain
watcher builds one payment moving its coins across, signed like any payout.
"""

import re
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import delete, func, select

from clans import communities
from clans.clan_wallet import MAJORITY, ClanPolicy, ClanWalletError, SignerKey
from clans.live_app import Input, audit, lock_clan, membership
from clans.live_models import ClanConfig
from clans.models import Membership, User, now_iso
from clans.wallet_alarms import recent_count
from clans.wallet_models import ClanWalletRecord, WalletConfirmation, WalletSignerKey

CODE_PATTERN = re.compile(r"^[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{8}$")
MINUTES_PER_BLOCK = 10


class KeyInput(Input):
    key: str = Field(min_length=20, max_length=300)


class ConfirmInput(Input):
    wallet_code: str = Field(min_length=8, max_length=8)


class NextWalletInput(Input):
    reason: Literal["lost_key", "stolen_phone", "signatory_change", "oversight_change", "other"]


SETUP_STATUSES = ("collecting_keys", "confirming")


def active_wallet(db, clan_id):
    """The wallet that receives money and pays new grants."""
    return db.scalar(
        select(ClanWalletRecord)
        .where(ClanWalletRecord.clan_id == clan_id, ClanWalletRecord.status == "active")
        .order_by(ClanWalletRecord.generation.desc())
    )


def setup_wallet(db, clan_id):
    """A generation still collecting keys or confirmations, if any."""
    return db.scalar(
        select(ClanWalletRecord)
        .where(
            ClanWalletRecord.clan_id == clan_id,
            ClanWalletRecord.status.in_(SETUP_STATUSES),
        )
        .order_by(ClanWalletRecord.generation.desc())
    )


def current_wallet(db, clan_id):
    """The wallet the clan uses now: the active one, or else the first one being set up."""
    return active_wallet(db, clan_id) or setup_wallet(db, clan_id)


def earlier_wallets(db, clan_id):
    """Retired generations that were once active. Their coins are moved to the newest."""
    return db.scalars(
        select(ClanWalletRecord)
        .where(
            ClanWalletRecord.clan_id == clan_id,
            ClanWalletRecord.status == "retired",
            ClanWalletRecord.activated_at.is_not(None),
        )
        .order_by(ClanWalletRecord.generation.desc())
    ).all()


def new_generation(db, clan_id, settings, *, started_by=None, reason=None):
    config = db.get(ClanConfig, clan_id)
    oversight = communities.for_clan(db, settings, clan_id)
    if not oversight.keys:
        raise HTTPException(
            409,
            f"{oversight.name} hasn't set up an oversight laptop yet, so the clan wallet can't "
            "be made. Ask the community's administrator.",
        )
    generation = db.scalar(
        select(func.coalesce(func.max(ClanWalletRecord.generation), 0)).where(
            ClanWalletRecord.clan_id == clan_id
        )
    )
    wallet = ClanWalletRecord(
        clan_id=clan_id,
        generation=generation + 1,
        network=settings.clan_wallet_network,
        status="collecting_keys",
        oversight_keys=[str(SignerKey.parse(value)) for value in oversight.keys],
        signer_count=config.target_signers,
        recovery_threshold=MAJORITY[config.target_signers],
        recovery_blocks=settings.clan_wallet_recovery_blocks,
        started_by=started_by,
        start_reason=reason,
    )
    db.add(wallet)
    db.flush()
    return wallet


def signer_members(db, clan_id):
    return db.scalars(
        select(Membership)
        .where(
            Membership.clan_id == clan_id,
            Membership.active.is_(True),
            Membership.is_signer.is_(True),
        )
        .order_by(Membership.user_id)
    ).all()


def wallet_keys(db, wallet):
    if not wallet:
        return {}
    rows = db.scalars(select(WalletSignerKey).where(WalletSignerKey.wallet_id == wallet.id))
    return {row.user_id: row for row in rows}


def confirmations(db, wallet):
    if not wallet:
        return {}
    rows = db.scalars(select(WalletConfirmation).where(WalletConfirmation.wallet_id == wallet.id))
    return {row.user_id: row for row in rows}


def policy_view(wallet, keys):
    """The exact inputs a phone needs to rebuild the wallet. Signers in canonical order."""
    return {
        "network": wallet.network,
        "oversight": list(wallet.oversight_keys),
        "signers": sorted(key.key_expression for key in keys),
        "recovery_threshold": wallet.recovery_threshold,
        "recovery_blocks": wallet.recovery_blocks,
    }


def wallet_view(db, clan_id, user_id, settings):
    wallet = current_wallet(db, clan_id)
    view = {"enabled": settings.clan_wallets_enabled}
    view |= generation_view(db, clan_id, wallet, user_id, settings)
    setup = setup_wallet(db, clan_id)
    # A new generation being set up while the current one keeps working.
    view["next"] = (
        generation_view(db, clan_id, setup, user_id, settings)
        if setup and wallet and setup.id != wallet.id
        else None
    )
    # Member alarms in the last 30 days; the list is GET …/wallet/alarms.
    view["alarms_recent"] = recent_count(db, clan_id)
    view["earlier"] = [
        {
            "generation": row.generation,
            "wallet_code": row.wallet_code,
            "retired_at": row.retired_at,
            # The chain watcher's last count of coins still to move, or null before it looked.
            "balance_sats": row.balance_sats,
        }
        for row in earlier_wallets(db, clan_id)
    ]
    return view


def generation_view(db, clan_id, wallet, user_id, settings):
    config = db.get(ClanConfig, clan_id)
    signers = signer_members(db, clan_id)
    keys = wallet_keys(db, wallet)
    confirmed = confirmations(db, wallet)
    me = next((m for m in signers if m.user_id == user_id), None)
    count = wallet.signer_count if wallet else config.target_signers
    blocks = wallet.recovery_blocks if wallet else settings.clan_wallet_recovery_blocks
    ready = wallet is not None and wallet.status in {"confirming", "active"}
    starter = db.get(User, wallet.started_by) if wallet and wallet.started_by else None
    return {
        "status": wallet.status if wallet else "not_started",
        "generation": wallet.generation if wallet else None,
        "network": wallet.network if wallet else settings.clan_wallet_network,
        "signer_count": count,
        "threshold": MAJORITY[count],
        "recovery_threshold": wallet.recovery_threshold if wallet else MAJORITY[count],
        "recovery_blocks": blocks,
        "recovery_days": round(blocks * MINUTES_PER_BLOCK / 1440),
        "confirmations_required": settings.clan_wallet_confirmations,
        "oversight_keys": list(wallet.oversight_keys)
        if wallet
        else list(communities.for_clan(db, settings, clan_id).keys),
        "signers": [
            {
                "user_id": m.user_id,
                "display_name": db.get(User, m.user_id).display_name,
                "key_registered": m.user_id in keys,
                "fingerprint": keys[m.user_id].fingerprint if m.user_id in keys else None,
                "confirmed": m.user_id in confirmed,
            }
            for m in signers
        ],
        "me": {
            "is_signer": me is not None,
            "key": keys[user_id].key_expression if user_id in keys else None,
            "confirmed": user_id in confirmed,
        },
        "policy": policy_view(wallet, [keys[m.user_id] for m in signers]) if ready else None,
        # For display beside the phone's own code. Phones must compute their own.
        "wallet_code": wallet.wallet_code if ready else None,
        "activated_at": wallet.activated_at if wallet else None,
        "started_by": starter.display_name if starter else None,
        "start_reason": wallet.start_reason if wallet else None,
    }


def refresh(db, wallet, clan_id):
    """Build the wallet once every current signatory has a key; reset if anything changed."""
    signers = signer_members(db, clan_id)
    keys = wallet_keys(db, wallet)
    previous = wallet.wallet_code
    if len(signers) == wallet.signer_count and all(m.user_id in keys for m in signers):
        try:
            policy = ClanPolicy.create(
                network=wallet.network,
                oversight=list(wallet.oversight_keys),
                signers=sorted(keys[m.user_id].key_expression for m in signers),
                recovery_threshold=wallet.recovery_threshold,
                recovery_blocks=wallet.recovery_blocks,
            )
        except ClanWalletError as exc:
            raise HTTPException(409, str(exc)) from exc
        same = db.scalar(
            select(ClanWalletRecord.id).where(
                ClanWalletRecord.clan_id == clan_id,
                ClanWalletRecord.id != wallet.id,
                ClanWalletRecord.activated_at.is_not(None),
                ClanWalletRecord.wallet_code == policy.wallet_code(),
            )
        )
        if same:
            raise HTTPException(
                409,
                "This is the same wallet as before. A new clan wallet needs at least one new key.",
            )
        wallet.descriptor_external = policy.descriptor("external")
        wallet.descriptor_internal = policy.descriptor("internal")
        wallet.wallet_code = policy.wallet_code()
        wallet.status = "confirming"
    else:
        wallet.descriptor_external = wallet.descriptor_internal = wallet.wallet_code = None
        wallet.status = "collecting_keys"
    if wallet.wallet_code != previous:
        db.execute(delete(WalletConfirmation).where(WalletConfirmation.wallet_id == wallet.id))


def install(app, security, settings):
    def require_enabled():
        if not settings.clan_wallets_enabled:
            raise HTTPException(503, "Clan wallets are not available yet.")

    @app.get("/api/clans/{clan_id}/wallet")
    def get_wallet(clan_id: str, request: Request):
        with security.db() as db:
            user = security.current(request, db)
            membership(db, clan_id, user.id)
            return wallet_view(db, clan_id, user.id, settings)

    @app.post("/api/clans/{clan_id}/wallet/keys")
    def register_key(clan_id: str, data: KeyInput, request: Request):
        require_enabled()
        security.limit(request, "wallet-key", 20, 3600)
        with security.db() as db:
            user = security.current(request, db)
            lock_clan(db, clan_id)
            member = membership(db, clan_id, user.id)
            if not member.is_signer:
                raise HTTPException(403, "Only signatories hold a clan wallet key.")
            try:
                key = SignerKey.parse(data.key)
            except ClanWalletError as exc:
                raise HTTPException(400, str(exc)) from exc
            community = communities.for_clan(db, settings, clan_id)
            oversight = [SignerKey.parse(value) for value in community.keys]
            if any(key.fingerprint == o.fingerprint or key.xpub == o.xpub for o in oversight):
                raise HTTPException(400, "A signatory key cannot be an oversight key.")
            wallet = setup_wallet(db, clan_id)
            if not wallet:
                if active_wallet(db, clan_id):
                    raise HTTPException(
                        409,
                        "The clan wallet is already active. To change a key, start a new "
                        "clan wallet.",
                    )
                wallet = new_generation(db, clan_id, settings)
            keys = wallet_keys(db, wallet)
            for other, row in keys.items():
                if other != user.id and (
                    row.fingerprint == key.fingerprint or row.key_expression == str(key)
                ):
                    raise HTTPException(409, "Another signatory already registered this key.")
            mine = keys.get(user.id)
            if mine and mine.key_expression == str(key):
                return wallet_view(db, clan_id, user.id, settings)
            if mine:
                mine.key_expression, mine.fingerprint, mine.created_at = (
                    str(key),
                    key.fingerprint,
                    now_iso(),
                )
            else:
                db.add(
                    WalletSignerKey(
                        wallet_id=wallet.id,
                        user_id=user.id,
                        key_expression=str(key),
                        fingerprint=key.fingerprint,
                    )
                )
            db.flush()
            refresh(db, wallet, clan_id)
            audit(
                db,
                clan_id,
                user.id,
                "wallet_key_registered",
                wallet_id=wallet.id,
                fingerprint=key.fingerprint,
                replaced=mine is not None,
                status=wallet.status,
            )
            return wallet_view(db, clan_id, user.id, settings)

    @app.post("/api/clans/{clan_id}/wallet/confirm")
    def confirm_wallet(clan_id: str, data: ConfirmInput, request: Request):
        require_enabled()
        security.limit(request, "wallet-confirm", 20, 3600)
        if not CODE_PATTERN.match(data.wallet_code):
            raise HTTPException(400, "A wallet code has 8 letters and numbers.")
        with security.db() as db:
            user = security.current(request, db)
            lock_clan(db, clan_id)
            member = membership(db, clan_id, user.id)
            if not member.is_signer:
                raise HTTPException(403, "Only signatories confirm the clan wallet.")
            wallet = setup_wallet(db, clan_id)
            if wallet and wallet.status == "confirming":
                # The signatory list may have changed since the code was shown.
                refresh(db, wallet, clan_id)
            if not wallet or wallet.status != "confirming":
                raise HTTPException(409, "The clan wallet is not waiting for confirmation.")
            if user.id not in wallet_keys(db, wallet):
                raise HTTPException(409, "Register your key before confirming the wallet.")
            if data.wallet_code != wallet.wallet_code:
                # Saved even though the request fails: everyone must hear about this.
                audit(
                    db,
                    clan_id,
                    user.id,
                    "wallet_code_mismatch",
                    wallet_id=wallet.id,
                    phone_code=data.wallet_code,
                    server_code=wallet.wallet_code,
                )
                return JSONResponse(
                    {
                        "detail": "Your phone computed a different wallet code. Do not use this "
                        "wallet. Tell your clan and Afribit."
                    },
                    status_code=409,
                )
            if user.id not in confirmations(db, wallet):
                db.add(
                    WalletConfirmation(
                        wallet_id=wallet.id, user_id=user.id, wallet_code=data.wallet_code
                    )
                )
                db.flush()
            confirmed = confirmations(db, wallet)
            if all(m.user_id in confirmed for m in signer_members(db, clan_id)):
                wallet.status = "active"
                wallet.activated_at = now_iso()
                for older in db.scalars(
                    select(ClanWalletRecord).where(
                        ClanWalletRecord.clan_id == clan_id,
                        ClanWalletRecord.status == "active",
                        ClanWalletRecord.id != wallet.id,
                    )
                ).all():
                    # Still watched: the chain watcher moves its coins to the new wallet.
                    older.status, older.retired_at = "retired", now_iso()
                    audit(
                        db,
                        clan_id,
                        user.id,
                        "wallet_retired",
                        wallet_id=older.id,
                        generation=older.generation,
                        replaced_by=wallet.generation,
                    )
            audit(
                db,
                clan_id,
                user.id,
                "wallet_confirmed",
                wallet_id=wallet.id,
                wallet_code=wallet.wallet_code,
                status=wallet.status,
            )
            return wallet_view(db, clan_id, user.id, settings)

    @app.post("/api/clans/{clan_id}/wallet/next")
    def start_next_wallet(clan_id: str, data: NextWalletInput, request: Request):
        """Start a new wallet generation. The current one keeps working until it's active."""
        require_enabled()
        security.limit(request, "wallet-next", 20, 3600)
        with security.db() as db:
            user = security.current(request, db)
            lock_clan(db, clan_id)
            member = membership(db, clan_id, user.id)
            if not member.is_signer:
                raise HTTPException(403, "Only signatories can start a new clan wallet.")
            from clans.access_service import recovery_hold

            if recovery_hold(db, user.id):
                raise HTTPException(
                    409, "An account recovery is waiting. Block it or finish it first."
                )
            current = active_wallet(db, clan_id)
            if not current:
                raise HTTPException(409, "Finish setting up the clan wallet first.")
            if setup_wallet(db, clan_id):
                raise HTTPException(409, "A new clan wallet is already being set up.")
            wallet = new_generation(db, clan_id, settings, started_by=user.id, reason=data.reason)
            audit(
                db,
                clan_id,
                user.id,
                "wallet_next_started",
                wallet_id=wallet.id,
                generation=wallet.generation,
                replaces=current.generation,
                reason=data.reason,
            )
            return wallet_view(db, clan_id, user.id, settings)

    @app.post("/api/clans/{clan_id}/wallet/next/cancel")
    def cancel_next_wallet(clan_id: str, request: Request):
        """Stop setting up a new generation. Nothing moves; the current wallet carries on."""
        require_enabled()
        security.limit(request, "wallet-next", 20, 3600)
        with security.db() as db:
            user = security.current(request, db)
            lock_clan(db, clan_id)
            member = membership(db, clan_id, user.id)
            if not member.is_signer:
                raise HTTPException(403, "Only signatories can stop a new clan wallet.")
            wallet = setup_wallet(db, clan_id)
            if not wallet or not active_wallet(db, clan_id):
                raise HTTPException(409, "No new clan wallet is being set up.")
            wallet.status, wallet.retired_at = "retired", now_iso()
            audit(
                db,
                clan_id,
                user.id,
                "wallet_next_cancelled",
                wallet_id=wallet.id,
                generation=wallet.generation,
            )
            return wallet_view(db, clan_id, user.id, settings)
