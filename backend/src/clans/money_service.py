"""Governed payment intents and atomic, balanced treasury settlement."""

import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import case, func, select
from webauthn import verify_authentication_response

from clans.live_models import Grant, Passkey, PaymentIntent, SignerApproval
from clans.live_security import unb64
from clans.models import AuditEvent, Membership, User, now_iso
from clans.money_models import (
    Balance,
    Debt,
    DepositReceipt,
    DispatchAuthorization,
    LedgerEntry,
    Payout,
)
from clans.treasury_provider import ProviderError


def canonical_json(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def intent_digest(data):
    return hashlib.sha256(canonical_json(data).encode()).hexdigest()


def approval_challenge(digest, nonce):
    return hashlib.sha256(b"afribit-clans-payment-v1:" + bytes.fromhex(digest) + nonce).digest()


def ledger(db, clan_id, event, reference, amount_msat, debit, credit):
    if amount_msat > 0:
        db.add(
            LedgerEntry(
                clan_id=clan_id,
                event=event,
                reference=reference,
                amount_msat=amount_msat,
                debit_account=debit,
                credit_account=credit,
            )
        )


def balance(db, clan_id):
    value = db.scalar(select(Balance).where(Balance.clan_id == clan_id).with_for_update())
    if not value:
        raise ProviderError("Treasury accounting is not initialized")
    return value


def reconciled(db, clan_id):
    value = balance(db, clan_id)
    total = db.scalar(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (LedgerEntry.debit_account == "bitcoin_custody", LedgerEntry.amount_msat),
                        (LedgerEntry.credit_account == "bitcoin_custody", -LedgerEntry.amount_msat),
                        else_=0,
                    )
                ),
                0,
            )
        ).where(LedgerEntry.clan_id == clan_id)
    )
    if total != value.balance_msat:
        raise ProviderError("Treasury entries and balance need reconciliation")
    return value


def valid_approvals(db, intent, grant, settings, *, lock=False):
    if intent.digest != intent_digest(intent.canonical):
        raise ProviderError("The payment intent was modified")
    valid = []
    approvals = db.scalars(
        select(SignerApproval).where(SignerApproval.intent_id == intent.id)
    ).all()
    for approval in approvals:
        if (
            approval.user_id == grant.beneficiary_id
            or approval.user_id not in grant.eligible_signers
        ):
            continue
        member = db.scalar(
            select(Membership).where(
                Membership.clan_id == grant.clan_id,
                Membership.user_id == approval.user_id,
                Membership.active.is_(True),
                Membership.is_signer.is_(True),
            )
        )
        query = select(Passkey).where(Passkey.id == approval.passkey_id, Passkey.active.is_(True))
        key = db.scalar(query.with_for_update() if lock else query)
        user = db.get(User, approval.user_id)
        if not member or not key or key.user_id != approval.user_id or not user or not user.active:
            continue
        proof = approval.assertion
        try:
            if proof["digest"] != intent.digest or proof["public_key"] != key.public_key:
                continue
            expected = approval_challenge(intent.digest, unb64(proof["nonce"]))
            result = verify_authentication_response(
                credential=proof["credential"],
                expected_challenge=expected,
                expected_rp_id=settings.rp_id,
                expected_origin=settings.public_origin,
                credential_public_key=unb64(key.public_key),
                credential_current_sign_count=proof["sign_count_before"],
                require_user_verification=True,
            )
            if (
                result.credential_id != unb64(key.credential_id)
                or result.new_sign_count > key.sign_count
            ):
                continue
        except Exception:
            continue
        valid.append(approval.user_id)
    return sorted(set(valid))


def active_intent(db, grant_id):
    return db.scalar(
        select(PaymentIntent)
        .where(PaymentIntent.grant_id == grant_id, PaymentIntent.active.is_(True))
        .order_by(PaymentIntent.created_at.desc())
    )


def release_intent(db, intent, grant, status):
    if db.scalar(
        select(DispatchAuthorization.payout_id)
        .join(Payout, Payout.id == DispatchAuthorization.payout_id)
        .where(Payout.intent_id == intent.id)
    ):
        raise ProviderError("A dispatched payment reservation requires node reconciliation")
    value = balance(db, grant.clan_id)
    reserved = intent.canonical["amount_msat"] + intent.canonical["fee_limit_msat"]
    if value.reserved_msat < reserved:
        raise ProviderError("Missing payment reservation")
    value.reserved_msat -= reserved
    intent.active = False
    intent.status = status
    grant.status = "awaiting_funding"


def apply_receipt(db, incoming, proof, kes_rate=None):
    """Credit a settled Lightning payment. A repayment of a KES debt needs `kes_rate`, the
    rate when the payment settled; without one this raises and nothing is credited, so the
    worker tries again on its next pass."""
    from clans.kes_debts import needs_rate, repay

    previous = db.scalar(
        select(DepositReceipt).where(DepositReceipt.payment_hash == proof["payment_hash"])
    )
    if previous:
        if previous.incoming_id != incoming.id or previous.amount_msat != proof["amount_msat"]:
            raise ProviderError("Settlement was already assigned to a different request")
        incoming.status = "settled"
        return False
    value = reconciled(db, incoming.clan_id)
    amount = proof["amount_msat"]
    if amount <= 0:
        raise ProviderError("A positive settled amount is required")
    allocated = 0
    facts = {}
    if incoming.grant_id:
        debt = db.scalar(select(Debt).where(Debt.grant_id == incoming.grant_id).with_for_update())
        grant = db.get(Grant, incoming.grant_id)
        if not debt or grant.clan_id != incoming.clan_id:
            raise ProviderError("Recovery request has no disbursed grant")
        if needs_rate(grant, debt) and kes_rate is None:
            raise ProviderError("A fresh BTC/KES rate is needed to count this repayment")
        allocated, facts = repay(
            db,
            incoming.clan_id,
            grant,
            debt,
            amount,
            "receipt:" + proof["payment_hash"],
            kes_rate,
        )
    db.add(
        DepositReceipt(
            incoming_id=incoming.id, payment_hash=proof["payment_hash"], amount_msat=amount
        )
    )
    ledger(
        db,
        incoming.clan_id,
        "contribution" if not incoming.grant_id else "recovery_surplus",
        "receipt:" + proof["payment_hash"] + ":capital",
        amount - allocated,
        "bitcoin_custody",
        "clan_capital",
    )
    value.balance_msat += amount
    incoming.credited_sats = amount // 1000
    incoming.status = "settled"
    db.add(
        AuditEvent(
            clan_id=incoming.clan_id,
            actor_id=incoming.user_id,
            event_type="treasury_settled",
            payload={
                "request_id": incoming.id,
                "amount_msat": str(amount),
                "recovery_msat": str(allocated),
                **facts,
            },
        )
    )
    return True


def book_payout(db, payout, intent, grant, fee_msat):
    if payout.status == "settled":
        return False
    value = reconciled(db, grant.clan_id)
    if db.get(Debt, grant.id):
        raise ProviderError("This grant already has a disbursement")
    charge = min(fee_msat, payout.fee_limit_msat)
    reservation = payout.amount_msat + payout.fee_limit_msat
    if value.reserved_msat < reservation or value.balance_msat < payout.amount_msat + charge:
        raise ProviderError("Payout accounting requires reconciliation")
    value.reserved_msat -= reservation
    value.balance_msat -= payout.amount_msat + charge
    ledger(
        db,
        grant.clan_id,
        "grant_disbursed",
        "payout:" + payout.payment_hash,
        payout.amount_msat,
        "grant_receivable",
        "bitcoin_custody",
    )
    ledger(
        db,
        grant.clan_id,
        "routing_fee",
        "payout:" + payout.payment_hash + ":fee",
        charge,
        "routing_expense",
        "bitcoin_custody",
    )
    db.add(
        Debt(
            grant_id=grant.id,
            principal_msat=payout.amount_msat,
            outstanding_msat=payout.amount_msat,
        )
    )
    in_kes = grant.obligation_currency == "KES"
    grant.outstanding_minor = grant.principal_minor if in_kes else grant.amount_sats
    grant.status = "in_recovery"
    intent.status = "settled"
    intent.active = False
    payout.status = "settled"
    payout.fee_paid_msat = fee_msat
    payout.updated_at = now_iso()
    if fee_msat > payout.fee_limit_msat:
        payout.last_error = "operator_fee_excess_requires_review"
    db.add(
        AuditEvent(
            clan_id=grant.clan_id,
            actor_id=payout.requested_by,
            event_type="grant_disbursed",
            payload={
                "grant_id": grant.id,
                "intent_digest": intent.digest,
                "amount_msat": str(payout.amount_msat),
                "fee_msat": str(fee_msat),
                "clan_fee_msat": str(charge),
                **({"debt_kes_minor": grant.principal_minor} if in_kes else {}),
            },
        )
    )
    return True


def ensure_invoice_change_allowed(db, grant):
    intent = active_intent(db, grant.id)
    if intent:
        payout = db.scalar(select(Payout).where(Payout.intent_id == intent.id))
        if payout and payout.status in {"queued", "sending", "uncertain", "settled"}:
            raise HTTPException(409, "This exact payment is already queued or being reconciled.")
        release_intent(db, intent, grant, "superseded")
