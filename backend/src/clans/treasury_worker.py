"""Durable, single-leader money worker; no payout credential is needed by the web app."""

import argparse
import hashlib
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, text

from clans.dispatch_security import authorize, validate_worker_settings, verify_binding
from clans.live_config import LiveSettings
from clans.live_models import Grant, IncomingPayment, PaymentIntent, Vote
from clans.live_security import Security
from clans.models import Clan, now_iso
from clans.money_models import (
    Debt,
    DepositPoll,
    DispatchAuthorization,
    Payout,
    PayoutPoll,
    ReceiveAuthorization,
    ReceiveInvoiceBinding,
    WorkerStatus,
)
from clans.money_service import (
    apply_receipt,
    book_payout,
    intent_digest,
    reconciled,
    release_intent,
    valid_approvals,
)
from clans.receive_security import (
    ReceiveBindingError,
    accept,
    bind,
    digest,
    validate_receive_settings,
    verify,
    verify_invoice,
)
from clans.treasury_provider import (
    PayoutDeferred,
    ProviderError,
    ProviderUnavailable,
    TreasuryProvider,
    decode_invoice,
)


class TreasuryWorker:
    def __init__(self, settings, *, provider=None):
        if settings.payouts_enabled:
            validate_worker_settings(settings)
        if settings.receiving_enabled:
            validate_receive_settings(settings)
        self.settings = settings
        self.security = Security(settings)
        self.provider = provider or TreasuryProvider(settings)

    def status(self, status, message=""):
        with self.security.db() as db:
            value = db.get(WorkerStatus, "treasury")
            if not value:
                value = WorkerStatus(id="treasury", status=status, node_verified=status == "ready")
                db.add(value)
            value.status = status
            value.node_verified = status == "ready"
            value.observed_at = now_iso()
            value.message = message

    def kes_rate(self):
        """The rate a KES repayment is counted at, read when it settles. None if no fresh
        rate: the repayment then waits, uncredited, for the next pass."""
        from clans.kes_debts import Rate

        try:
            quote = self.provider.kes_rate()
        except ProviderError:
            print("No fresh BTC/KES rate; a KES repayment waits for the next pass.")
            return None
        return Rate(quote.rate, quote.published_at)

    def incoming(self, incoming_id):
        try:
            self._incoming(incoming_id)
        except ReceiveBindingError:
            # No credit or debt movement may survive a changed attribution.
            with self.security.db() as db:
                row = db.get(IncomingPayment, incoming_id)
                if row and row.status != "settled":
                    row.status = "review_required"

    def _incoming(self, incoming_id):
        with self.security.db() as db:
            row = db.scalar(
                select(IncomingPayment).where(IncomingPayment.id == incoming_id).with_for_update()
            )
            if not row or row.status in {"settled", "failed", "review_required"}:
                return
            authorization = db.get(ReceiveAuthorization, row.id)
            if not authorization:
                if (
                    row.status != "creating"
                    or row.provider_invoice_id
                    or row.bolt11
                    or row.credited_sats
                ):
                    raise ReceiveBindingError("Legacy invoice needs receiving review")
                authorization = accept(self.settings, row)
                db.add(authorization)
            verify(self.settings, row, authorization)
            binding = db.get(ReceiveInvoiceBinding, row.id)
            if binding:
                verify_invoice(self.settings, row, authorization, binding)
            elif row.provider_invoice_id or row.bolt11:
                raise ReceiveBindingError("Unbound receiving invoice")
            request_id, clan_id, amount = row.id, row.clan_id, row.amount_sats
            grant = db.get(Grant, row.grant_id) if row.grant_id else None
            kes_debt = bool(grant) and grant.obligation_currency == "KES"
            clan = db.get(Clan, clan_id)
            label = "Repayment" if row.grant_id else "Add money"
            description = f"{clan.name} - {label}"
            provider_id = binding.provider_invoice_id if binding else None
            create = row.status == "creating"
            if create and not self.settings.receiving_enabled:
                return
            if create:
                row.status = "creating_provider"
        try:
            invoice = (
                self.provider.invoice(provider_id)
                if provider_id
                else self.provider.find_invoice(request_id)
            )
            if not invoice and create:
                # Only this transition may create an external invoice. A crash/timeout
                # leaves creating_provider for lookup, never an automatic second POST.
                invoice = self.provider.create_invoice(
                    request_id,
                    amount,
                    description=description,
                    clan_id=clan_id,
                    receive_authorization=digest(authorization.identity),
                )
            if not invoice:
                return
            if invoice.get("metadata", {}).get("clansReceiveAuthorization") != digest(
                authorization.identity
            ):
                raise ReceiveBindingError("Provider receiving authorization mismatch")
            details = self.provider.receive_details(invoice, request_id, amount)
            proof = self.provider.settlement(invoice, request_id, amount)
            kes_rate = self.kes_rate() if proof and kes_debt else None
            with self.security.db() as db:
                db.scalar(select(Clan).where(Clan.id == clan_id).with_for_update())
                row = db.scalar(
                    select(IncomingPayment)
                    .where(IncomingPayment.id == incoming_id)
                    .with_for_update()
                )
                if row.status == "settled":
                    return
                authorization = db.get(ReceiveAuthorization, row.id)
                verify(self.settings, row, authorization)
                binding = db.get(ReceiveInvoiceBinding, row.id)
                if not binding:
                    if row.provider_invoice_id or row.bolt11:
                        raise ReceiveBindingError("Unbound receiving invoice")
                    binding = bind(self.settings, authorization, details)
                    db.add(binding)
                    db.flush()
                verify_invoice(self.settings, row, authorization, binding, details, proof)
                row.provider_invoice_id = details["provider_invoice_id"]
                row.bolt11 = details["bolt11"]
                row.checkout_url = details["checkout_url"]
                row.expires_at = details["expires_at"]
                if proof:
                    apply_receipt(db, row, proof, kes_rate)
                else:
                    row.status = "expired" if details["expires_at"] <= now_iso() else "pending"
        except ReceiveBindingError:
            raise
        except ProviderError:
            # Preserve both the durable request and any ambiguous provider creation.
            # The next pass searches by the exact immutable order ID.
            with self.security.db() as db:
                row = db.get(IncomingPayment, incoming_id)
                if row and row.status == "creating_provider":
                    row.status = "reconciling"
        finally:
            with self.security.db() as db:
                marker = db.get(DepositPoll, incoming_id)
                if marker:
                    marker.last_checked_at = now_iso()
                else:
                    db.add(DepositPoll(incoming_id=incoming_id, last_checked_at=now_iso()))

    def expire(self):
        with self.security.db() as db:
            dispatched = (
                select(Payout.intent_id)
                .outerjoin(DispatchAuthorization, DispatchAuthorization.payout_id == Payout.id)
                .where(
                    or_(
                        Payout.status.in_(["sending", "uncertain", "settled"]),
                        DispatchAuthorization.payout_id.is_not(None),
                    )
                )
            )
            ids = db.scalars(
                select(PaymentIntent.id)
                .where(
                    PaymentIntent.active.is_(True),
                    PaymentIntent.expires_at <= now_iso(),
                    PaymentIntent.id.not_in(dispatched),
                )
                .order_by(PaymentIntent.expires_at, PaymentIntent.id)
                .limit(100)
            ).all()
        for intent_id in ids:
            with self.security.db() as db:
                initial = db.get(PaymentIntent, intent_id)
                grant = db.get(Grant, initial.grant_id)
                db.scalar(select(Clan).where(Clan.id == grant.clan_id).with_for_update())
                intent = db.scalar(
                    select(PaymentIntent)
                    .where(PaymentIntent.id == intent_id)
                    .execution_options(populate_existing=True)
                    .with_for_update()
                )
                payout = db.scalar(
                    select(Payout).where(Payout.intent_id == intent_id).with_for_update()
                )
                if (
                    not intent.active
                    or (payout and payout.status in {"sending", "uncertain", "settled"})
                    or (payout and db.get(DispatchAuthorization, payout.id))
                ):
                    continue
                release_intent(db, intent, grant, "expired")
                if payout:
                    payout.status = "failed"
                    payout.last_error = "invoice_expired_before_dispatch"

    def fail_before_dispatch(self, payout_id, reason):
        with self.security.db() as db:
            row = db.get(Payout, payout_id)
            intent = db.get(PaymentIntent, row.intent_id)
            grant = db.get(Grant, intent.grant_id)
            db.scalar(select(Clan).where(Clan.id == grant.clan_id).with_for_update())
            row = db.scalar(
                select(Payout)
                .where(Payout.id == payout_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
            if row.status not in {"queued", "awaiting_approvals"} or row.attempts:
                return
            release_intent(db, intent, grant, "rejected")
            row.status = "failed"
            row.last_error = reason

    def payout(self, payout_id):
        with self.security.db() as db:
            row = db.get(Payout, payout_id)
            if not row or row.status in {"settled", "failed", "awaiting_approvals"}:
                return
            payment_hash = row.payment_hash
            needs_rate = self.settings.payout_budget_currency == "KES" and not db.get(
                DispatchAuthorization, row.id
            )
        # A provider lookup is read-only. Only a NEW, fully authorized transaction
        # below may cause send(); recovery cycles NEVER repeat that external call.
        existing = self.provider.payment(payment_hash)
        try:
            kes_rate = self.provider.kes_rate() if needs_rate else None
        except ProviderError as exc:
            raise PayoutDeferred(
                "A fresh exchange rate is unavailable", "exchange_rate_unavailable", 30
            ) from exc
        send_now = False
        with self.security.db() as db:
            initial = db.get(Payout, payout_id)
            intent = db.get(PaymentIntent, initial.intent_id)
            grant = db.get(Grant, intent.grant_id)
            db.scalar(select(Clan).where(Clan.id == grant.clan_id).with_for_update())
            row = db.scalar(
                select(Payout)
                .where(Payout.id == payout_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
            if row.status in {"settled", "failed", "awaiting_approvals"}:
                return
            authorization = db.get(DispatchAuthorization, row.id)
            if authorization:
                verify_binding(self.settings, authorization, row, intent, grant)
            elif row.status != "queued" or row.attempts or row.dispatched_at:
                # Includes pre-upgrade in-flight records. Never invent authorization
                # or release their reservations; they require operator reconciliation.
                raise ProviderError("Missing worker dispatch authorization")
            else:
                if not self.settings.payouts_enabled:
                    return
                if existing:
                    release_intent(db, intent, grant, "rejected")
                    row.status = "failed"
                    row.last_error = "invoice_already_paid_or_inflight"
                    return
                from clans.access_service import recovery_hold

                if recovery_hold(db, grant.beneficiary_id):
                    return
                if not intent.active or intent.expires_at <= now_iso():
                    release_intent(db, intent, grant, "expired")
                    row.status = "failed"
                    row.last_error = "invoice_expired_before_dispatch"
                    return
                decoded = decode_invoice(intent.bolt11)
                if (
                    intent.digest != intent_digest(intent.canonical)
                    or decoded["payment_hash"] != row.payment_hash
                    or decoded["amount_msat"] != row.amount_msat
                    or row.amount_msat != grant.amount_sats * 1000
                    or intent.canonical["beneficiary_id"] != grant.beneficiary_id
                    or intent.canonical["policy"] != grant.policy_snapshot
                    or intent.canonical["fee_limit_msat"] != row.fee_limit_msat
                    or intent.canonical["amount_msat"] != row.amount_msat
                    or intent.canonical["payment_hash"] != row.payment_hash
                    or intent.canonical["bolt11_sha256"]
                    != hashlib.sha256(intent.bolt11.encode()).hexdigest()
                    or intent.canonical["clan_id"] != grant.clan_id
                    or intent.canonical["grant_id"] != grant.id
                    or intent.canonical["eligible_signers"] != sorted(grant.eligible_signers)
                    or intent.canonical["expires_at"] != decoded["expires_at"]
                    or intent.canonical["network"] != "mainnet"
                    or intent.canonical["asset"] != "BTC"
                    or row.amount_msat > self.settings.max_payout_sats * 1000
                    or row.fee_limit_msat > self.settings.payout_fee_max_sats * 1000
                    or decoded["payee"] == self.settings.expected_node_pubkey
                    or row.fee_limit_msat % 1000
                ):
                    raise ProviderError("Immutable payment fields do not match")
                value = reconciled(db, grant.clan_id)
                reserve = row.amount_msat + row.fee_limit_msat
                if value.reserved_msat < reserve or db.get(Debt, grant.id):
                    raise ProviderError("Payout reservation or principal needs reconciliation")
                voters = set(
                    db.scalars(
                        select(Vote.user_id).where(
                            Vote.grant_id == grant.id, Vote.choice == "approve"
                        )
                    ).all()
                )
                voters &= set(grant.eligible_voters) - {grant.beneficiary_id}
                if (
                    not grant.accepted_at
                    or len(voters) < grant.policy_snapshot["quorum"]
                    or len(voters) <= len(grant.eligible_voters) // 2
                ):
                    raise ProviderError("The member vote and beneficiary acceptance are incomplete")
                approvals = valid_approvals(db, intent, grant, self.settings, lock=True)
                if any(recovery_hold(db, uid) for uid in approvals):
                    return
                if len(approvals) < grant.policy_snapshot["threshold"]:
                    row.status = "awaiting_approvals"
                    intent.status = "awaiting_approvals"
                    grant.status = "awaiting_signatures"
                    return
                from clans.signer_trust import verify_signer_trust

                trust_digest = verify_signer_trust(db, self.settings, grant, intent, approvals)
                authorization = authorize(
                    db, self.settings, row, intent, grant, kes_rate, trust_digest
                )
                row.status = "sending"
                row.last_error = None
                row.dispatched_at = authorization.authorized_at
                row.attempts = 1
                intent.status = "sending"
                grant.status = "paying"
                send_now = True
            invoice = intent.bolt11
            amount = row.amount_msat
            fee_limit = row.fee_limit_msat // 1000
            row.updated_at = now_iso()
        if send_now:
            try:
                self.provider.send(invoice, fee_limit)
            except ProviderError:
                pass
            existing = self.provider.payment(payment_hash)
        with self.security.db() as db:
            initial = db.get(Payout, payout_id)
            intent = db.get(PaymentIntent, initial.intent_id)
            grant = db.get(Grant, intent.grant_id)
            db.scalar(select(Clan).where(Clan.id == grant.clan_id).with_for_update())
            row = db.scalar(
                select(Payout)
                .where(Payout.id == payout_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
            if row.status == "settled":
                return
            authorization = db.get(DispatchAuthorization, row.id)
            if not authorization:
                raise ProviderError("Missing worker dispatch authorization")
            verify_binding(self.settings, authorization, row, intent, grant)
            if existing and existing.get("status") == "Complete":
                fee = self.provider.payout_proof(existing, payment_hash, amount)
                book_payout(db, row, intent, grant, fee)
            elif existing and existing.get("status") == "Failed":
                # The authenticated dispatch is preserved for budget/audit purposes.
                # Only a matching terminal provider failure may release its reservation.
                if str(existing.get("paymentHash", "")).lower() != payment_hash:
                    raise ProviderError("Failed payout payment hash mismatch")
                value = reconciled(db, grant.clan_id)
                reserve = authorization.amount_msat + authorization.fee_limit_msat
                if value.reserved_msat < reserve:
                    raise ProviderError("Failed payout reservation needs reconciliation")
                value.reserved_msat -= reserve
                intent.active = False
                intent.status = "failed"
                grant.status = "awaiting_funding"
                row.status = "failed"
                row.last_error = "payment_failed_no_route_or_liquidity"
            else:
                row.status = "uncertain"
                row.last_error = "waiting_for_node_confirmation"
            row.updated_at = now_iso()

    def record_payout_poll(self, payout_id, reason="", delay=0):
        now = datetime.now(UTC)
        with self.security.db() as db:
            row = db.scalar(select(Payout).where(Payout.id == payout_id).with_for_update())
            marker = db.get(PayoutPoll, payout_id)
            if not marker:
                marker = PayoutPoll(payout_id=payout_id)
                db.add(marker)
            marker.last_checked_at = now.isoformat()
            marker.next_attempt_at = (now + timedelta(seconds=delay)).isoformat()
            marker.reason = reason
            if reason and row.status not in {"settled", "failed"}:
                row.last_error = reason

    def due_payouts(self, db, statuses):
        return db.scalars(
            select(Payout.id)
            .outerjoin(PayoutPoll, PayoutPoll.payout_id == Payout.id)
            .where(
                Payout.status.in_(statuses),
                or_(PayoutPoll.payout_id.is_(None), PayoutPoll.next_attempt_at <= now_iso()),
            )
            .order_by(
                func.coalesce(PayoutPoll.last_checked_at, "1970"), Payout.created_at, Payout.id
            )
            .limit(4)
        ).all()

    def tick(self):
        with self.security.engine.connect() as connection:
            postgres = self.security.engine.dialect.name == "postgresql"
            if (
                postgres
                and not connection.execute(
                    text("SELECT pg_try_advisory_lock(24110301)")
                ).scalar_one()
            ):
                return
            if postgres:
                connection.commit()
            try:
                self.provider.verify_node()
                with self.security.db() as db:
                    excess = db.scalar(
                        select(Payout.id)
                        .where(Payout.last_error == "operator_fee_excess_requires_review")
                        .limit(1)
                    )
                    incoming = db.scalars(
                        select(IncomingPayment.id)
                        .where(
                            IncomingPayment.status.not_in(["settled", "failed", "review_required"])
                        )
                        .outerjoin(DepositPoll, DepositPoll.incoming_id == IncomingPayment.id)
                        .order_by(
                            func.coalesce(DepositPoll.last_checked_at, "1970"),
                            IncomingPayment.created_at,
                        )
                        .limit(100)
                    ).all()
                    # Separate bounded queues guarantee progress for both old
                    # dispatch reconciliation and new, independently valid work.
                    payouts = self.due_payouts(db, ["sending", "uncertain"])
                    payouts += self.due_payouts(db, ["queued"])
                if excess:
                    raise ProviderError("A provider fee discrepancy requires operator review")
                self.status("ready")
                # Reconcile already-dispatched payments even with new movement disabled.
                # Outgoing work precedes the bounded incoming queue to avoid starvation.
                for payout_id in payouts:
                    try:
                        self.payout(payout_id)
                    except PayoutDeferred as exc:
                        self.record_payout_poll(payout_id, exc.reason, exc.retry_seconds)
                    except ProviderUnavailable:
                        # No state reset or second send. An ambiguous dispatch
                        # retains its authorization, reservation and attempt count.
                        self.record_payout_poll(payout_id, "payment_provider_retry", 15)
                    else:
                        self.record_payout_poll(payout_id)
                    with self.security.db() as db:
                        if db.scalar(
                            select(Payout.id)
                            .where(Payout.last_error == "operator_fee_excess_requires_review")
                            .limit(1)
                        ):
                            raise ProviderError(
                                "A provider fee discrepancy requires operator review"
                            )
                for incoming_id in incoming:
                    self.incoming(incoming_id)
                self.expire()
                self.status("ready")
            except ProviderError:
                self.status("unavailable", "provider_or_accounting_reconciliation_required")
            finally:
                if postgres:
                    connection.execute(text("SELECT pg_advisory_unlock(24110301)"))
                    connection.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    worker = TreasuryWorker(LiveSettings())
    while True:
        try:
            worker.tick()
        except Exception:
            # No provider response, invoice, key or raw SQL is logged by this service.
            print("Treasury cycle interrupted; durable records will be reconciled.", flush=True)
            worker.status("unavailable", "worker_cycle_interrupted")
        if args.once:
            break
        time.sleep(5)


if __name__ == "__main__":
    main()
