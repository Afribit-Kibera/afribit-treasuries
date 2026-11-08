"""Authenticated treasury request and exact-intent WebAuthn endpoints."""

import secrets

from fastapi import HTTPException, Request, Response
from pydantic import Field, model_validator
from sqlalchemy import select

from clans.live_app import Finish, Input, audit, lock_clan, membership, operation
from clans.live_models import Grant, IncomingPayment, PaymentIntent, SignerApproval
from clans.live_security import b64
from clans.models import new_id, now_iso
from clans.money_models import Debt, Payout, WorkerStatus
from clans.money_service import (
    active_intent,
    approval_challenge,
    ensure_invoice_change_allowed,
    intent_digest,
    reconciled,
    valid_approvals,
)
from clans.treasury_provider import ProviderError, decode_invoice


class DepositInput(Input):
    amount_sats: int | None = Field(default=None, strict=True, gt=0, le=10_000_000)
    quote: str | None = Field(default=None, min_length=20, max_length=2000)
    grant_id: str | None = Field(default=None, max_length=36)

    @model_validator(mode="after")
    def one_amount(self):
        if (self.amount_sats is None) == (self.quote is None):
            raise ValueError("Use one quote or one amount in sats")
        return self


class DestinationInput(Input):
    bolt11: str = Field(min_length=20, max_length=12_010)


def worker_state(db):
    state = db.get(WorkerStatus, "treasury")
    from datetime import UTC, datetime, timedelta

    cutoff = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
    return bool(
        state and state.status == "ready" and state.node_verified and state.observed_at > cutoff
    )


def require_worker(db):
    if not worker_state(db):
        raise HTTPException(
            503, "Treasury synchronization is temporarily unavailable. Please try again shortly."
        )


def incoming_view(row):
    return {
        "id": row.id,
        "clan_id": row.clan_id,
        "amount_sats": row.amount_sats,
        "grant_id": row.grant_id,
        "status": row.status,
        "bolt11": row.bolt11,
        "checkout_url": row.checkout_url,
        "expires_at": row.expires_at,
        "credited_sats": row.credited_sats,
        "created_at": row.created_at,
    }


def intent_view(db, intent, grant, settings, user_id):
    from clans.access_service import recovery_hold
    from clans.models import User

    approvals = valid_approvals(db, intent, grant, settings)
    payout = db.scalar(select(Payout).where(Payout.intent_id == intent.id))
    return {
        "id": intent.id,
        "digest": intent.digest,
        "payment_hash": intent.payment_hash,
        "status": intent.status,
        "expires_at": intent.expires_at,
        "amount_msat": str(intent.canonical["amount_msat"]),
        "fee_limit_msat": str(intent.canonical["fee_limit_msat"]),
        "approval_count": len(approvals),
        "required_approvals": grant.policy_snapshot["threshold"],
        "approved_by_me": user_id in approvals,
        "approved_names": [db.get(User, uid).display_name for uid in approvals],
        "account_recovery_pending": recovery_hold(db, grant.beneficiary_id)
        or any(recovery_hold(db, uid) for uid in approvals),
        "can_approve": intent.active
        and intent.status == "awaiting_approvals"
        and user_id in grant.eligible_signers
        and user_id != grant.beneficiary_id
        and user_id not in approvals
        and not recovery_hold(db, user_id)
        and intent.expires_at > now_iso(),
        "payout_status": payout.status if payout else None,
        "last_error": payout.last_error if payout else None,
        "fee_paid_msat": str(payout.fee_paid_msat)
        if payout and payout.fee_paid_msat is not None
        else None,
    }


def install(app, security, settings):
    @app.post("/api/clans/{clan_id}/deposits")
    def request_deposit(clan_id: str, data: DepositInput, request: Request):
        security.limit(request, "deposit", 30, 3600)
        if not settings.receiving_enabled:
            raise HTTPException(503, "Deposits are temporarily unavailable.")
        with security.db() as db:
            user = security.current(request, db)
            lock_clan(db, clan_id)
            membership(db, clan_id, user.id)
            require_worker(db)

            def perform():
                from clans.display_rates import read_grant_quote

                quote = (
                    read_grant_quote(security, data.quote, user.id, clan_id) if data.quote else None
                )
                amount = quote["amount_sats"] if quote else data.amount_sats
                if amount > settings.max_invoice_sats:
                    raise HTTPException(
                        400, f"The per-invoice limit is {settings.max_invoice_sats:,} sats."
                    )
                if data.grant_id:
                    grant = db.get(Grant, data.grant_id)
                    debt = db.get(Debt, data.grant_id)
                    if (
                        not grant
                        or grant.clan_id != clan_id
                        or not debt
                        or debt.outstanding_msat <= 0
                    ):
                        raise HTTPException(409, "This grant has no outstanding recovery balance.")
                incoming = IncomingPayment(
                    id=new_id(),
                    clan_id=clan_id,
                    user_id=user.id,
                    grant_id=data.grant_id,
                    amount_sats=amount,
                    status="creating",
                )
                db.add(incoming)
                audit(
                    db,
                    clan_id,
                    user.id,
                    "deposit_requested",
                    request_id=incoming.id,
                    amount_sats=amount,
                    grant_id=data.grant_id,
                    display_quote=quote,
                )
                return {"request_id": incoming.id}

            return operation(db, request, user, "deposit:" + clan_id, data.model_dump(), perform)

    @app.get("/api/clans/{clan_id}/deposits/{incoming_id}")
    def get_deposit(clan_id: str, incoming_id: str, request: Request):
        with security.db() as db:
            user = security.current(request, db)
            membership(db, clan_id, user.id)
            incoming = db.get(IncomingPayment, incoming_id)
            if not incoming or incoming.clan_id != clan_id:
                raise HTTPException(404, "Deposit request not found.")
            return incoming_view(incoming)

    @app.post("/api/clans/{clan_id}/grants/{grant_id}/destination")
    def destination(clan_id: str, grant_id: str, data: DestinationInput, request: Request):
        if not settings.payouts_enabled:
            raise HTTPException(503, "Payouts are temporarily unavailable.")
        with security.db() as db:
            user = security.current(request, db)
            lock_clan(db, clan_id)
            membership(db, clan_id, user.id)
            try:
                decoded = decode_invoice(data.bolt11)
            except ProviderError as exc:
                raise HTTPException(400, str(exc)) from exc
            require_worker(db)
            grant = db.get(Grant, grant_id)
            if not grant or grant.clan_id != clan_id:
                raise HTTPException(404, "Grant not found.")
            if grant.beneficiary_id != user.id:
                raise HTTPException(403, "Only the beneficiary can supply their payout invoice.")
            from clans.wallet_api import active_wallet

            if active_wallet(db, clan_id):
                raise HTTPException(
                    409, "This clan pays grants to a Bitcoin address. Give your address instead."
                )
            from clans.access_service import recovery_hold

            if recovery_hold(db, user.id):
                raise HTTPException(
                    409,
                    "An account recovery is waiting. "
                    "Block it or finish it before changing a payment.",
                )
            if not grant.accepted_at or grant.status not in {
                "awaiting_funding",
                "awaiting_signatures",
            }:
                raise HTTPException(
                    409, "The grant must pass the member vote and be accepted first."
                )
            if grant.amount_sats > settings.max_payout_sats:
                raise HTTPException(
                    400, f"The per-payment limit is {settings.max_payout_sats:,} sats."
                )
            if decoded["amount_msat"] != grant.amount_sats * 1000:
                raise HTTPException(
                    400, "The invoice must request the exact approved grant amount."
                )
            if decoded["payee"] == settings.expected_node_pubkey:
                raise HTTPException(
                    400, "Use an invoice from your own external wallet, not the clan treasury."
                )

            def perform():
                ensure_invoice_change_allowed(db, grant)
                value = reconciled(db, clan_id)
                fee_sats = min(
                    settings.payout_fee_max_sats,
                    max(1, (grant.amount_sats * settings.payout_fee_ppm + 999_999) // 1_000_000),
                )
                amount = grant.amount_sats * 1000
                reserve = amount + fee_sats * 1000
                if value.balance_msat - value.reserved_msat < reserve:
                    raise HTTPException(
                        409,
                        "The clan needs enough settled capital for the grant "
                        "and its maximum routing fee.",
                    )
                canonical = {
                    "version": 1,
                    "clan_id": clan_id,
                    "grant_id": grant_id,
                    "beneficiary_id": user.id,
                    "asset": "BTC",
                    "network": "mainnet",
                    "amount_msat": amount,
                    "fee_limit_msat": fee_sats * 1000,
                    "payment_hash": decoded["payment_hash"],
                    "bolt11_sha256": __import__("hashlib")
                    .sha256(decoded["bolt11"].encode())
                    .hexdigest(),
                    "expires_at": decoded["expires_at"],
                    "policy": grant.policy_snapshot,
                    "eligible_signers": sorted(grant.eligible_signers),
                }
                intent = PaymentIntent(
                    id=new_id(),
                    grant_id=grant_id,
                    digest=intent_digest(canonical),
                    canonical=canonical,
                    bolt11=decoded["bolt11"],
                    payment_hash=decoded["payment_hash"],
                    expires_at=decoded["expires_at"],
                    status="awaiting_approvals",
                )
                db.add(intent)
                value.reserved_msat += reserve
                grant.status = "awaiting_signatures"
                audit(
                    db,
                    clan_id,
                    user.id,
                    "payment_prepared",
                    grant_id=grant_id,
                    intent_digest=intent.digest,
                    amount_msat=str(amount),
                    fee_limit_msat=str(fee_sats * 1000),
                )
                return {"intent_id": intent.id}

            return operation(
                db, request, user, "destination:" + grant_id, data.model_dump(), perform
            )

    @app.get("/api/clans/{clan_id}/grants/{grant_id}/payment")
    def payment(clan_id: str, grant_id: str, request: Request):
        with security.db() as db:
            user = security.current(request, db)
            membership(db, clan_id, user.id)
            grant = db.get(Grant, grant_id)
            if not grant or grant.clan_id != clan_id:
                raise HTTPException(404, "Grant not found.")
            intent = db.scalar(
                select(PaymentIntent)
                .where(PaymentIntent.grant_id == grant_id)
                .order_by(PaymentIntent.created_at.desc())
            )
            return intent_view(db, intent, grant, settings, user.id) if intent else None

    @app.post("/api/clans/{clan_id}/grants/{grant_id}/payment/approval/options")
    def approval_options(clan_id: str, grant_id: str, request: Request, response: Response):
        if not settings.payouts_enabled:
            raise HTTPException(503, "Payouts are temporarily unavailable.")
        security.limit(request, "payment-approval", 30)
        with security.db() as db:
            user = security.current(request, db)
            lock_clan(db, clan_id)
            membership(db, clan_id, user.id)
            grant = db.get(Grant, grant_id)
            intent = active_intent(db, grant_id)
            if not grant or grant.clan_id != clan_id or not intent:
                raise HTTPException(404, "No active payment intent.")
            view = intent_view(db, intent, grant, settings, user.id)
            if not view["can_approve"]:
                raise HTTPException(
                    409, "You cannot approve this exact payment, or it has expired."
                )
            nonce = secrets.token_bytes(32)
            return {
                **security.challenge(
                    db,
                    response,
                    "payment-approval",
                    user_id=user.id,
                    payload={"intent_id": intent.id, "digest": intent.digest, "nonce": b64(nonce)},
                    challenge_bytes=approval_challenge(intent.digest, nonce),
                ),
                "intent": view,
            }

    @app.post("/api/clans/{clan_id}/grants/{grant_id}/payment/approval/verify")
    def approval_verify(clan_id: str, grant_id: str, data: Finish, request: Request):
        with security.db() as db:
            user = security.current(request, db)
            lock_clan(db, clan_id)
            membership(db, clan_id, user.id)
            require_worker(db)
            record = security.take_challenge(db, request, data.challenge_id, "payment-approval")
            grant = db.get(Grant, grant_id)
            intent = active_intent(db, grant_id)
            if (
                not grant
                or grant.clan_id != clan_id
                or not intent
                or record.user_id != user.id
                or record.payload["intent_id"] != intent.id
                or record.payload["digest"] != intent.digest
            ):
                raise HTTPException(409, "The payment intent changed. Review it again.")
            if not intent_view(db, intent, grant, settings, user.id)["can_approve"]:
                raise HTTPException(409, "This payment cannot be approved by this account.")
            # Preserve the original counter for independent executor verification.
            from clans.live_models import Passkey

            key_before = db.scalar(
                select(Passkey)
                .where(
                    Passkey.credential_id == data.credential.get("id", ""),
                    Passkey.user_id == user.id,
                    Passkey.active.is_(True),
                )
                .with_for_update()
            )
            if not key_before:
                raise HTTPException(400, "Use your own account passkey.")
            counter = key_before.sign_count
            key = security.assertion(db, data.credential, record, expected_user=user.id)
            proof = {
                "digest": intent.digest,
                "nonce": record.payload["nonce"],
                "public_key": key.public_key,
                "sign_count_before": counter,
                "credential": data.credential,
            }
            previous = db.scalar(
                select(SignerApproval).where(
                    SignerApproval.intent_id == intent.id, SignerApproval.user_id == user.id
                )
            )
            if previous:
                previous.passkey_id = key.id
                previous.assertion = proof
            else:
                db.add(
                    SignerApproval(
                        intent_id=intent.id, user_id=user.id, passkey_id=key.id, assertion=proof
                    )
                )
            db.flush()
            approvals = valid_approvals(db, intent, grant, settings)
            if len(approvals) >= grant.policy_snapshot["threshold"]:
                payout = db.scalar(select(Payout).where(Payout.intent_id == intent.id))
                if not payout:
                    db.add(
                        Payout(
                            intent_id=intent.id,
                            requested_by=user.id,
                            payment_hash=intent.payment_hash,
                            amount_msat=intent.canonical["amount_msat"],
                            fee_limit_msat=intent.canonical["fee_limit_msat"],
                        )
                    )
                else:
                    payout.status = "queued"
                intent.status = "queued"
                grant.status = "payment_queued"
            audit(
                db,
                clan_id,
                user.id,
                "payment_approved",
                grant_id=grant_id,
                intent_digest=intent.digest,
                approvals=len(approvals),
                required=grant.policy_snapshot["threshold"],
            )
            return {"status": intent.status, "approvals": len(approvals)}
