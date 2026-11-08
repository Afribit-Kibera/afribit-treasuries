"""Exact millisatoshi accounting and durable provider dispatch records."""

from sqlalchemy import JSON, BigInteger, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from clans.db import Base
from clans.models import new_id, now_iso


class Balance(Base):
    __tablename__ = "treasury_balances"
    clan_id: Mapped[str] = mapped_column(ForeignKey("clans.id"), primary_key=True)
    balance_msat: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved_msat: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (CheckConstraint("balance_msat >= reserved_msat AND reserved_msat >= 0"),)


class LedgerEntry(Base):
    __tablename__ = "treasury_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    clan_id: Mapped[str] = mapped_column(ForeignKey("clans.id"), index=True)
    event: Mapped[str] = mapped_column(String(40))
    reference: Mapped[str] = mapped_column(String(256), unique=True)
    amount_msat: Mapped[int] = mapped_column(BigInteger)
    debit_account: Mapped[str] = mapped_column(String(50))
    credit_account: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    __table_args__ = (CheckConstraint("amount_msat > 0 AND debit_account <> credit_account"),)


class DepositReceipt(Base):
    __tablename__ = "treasury_receipts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    incoming_id: Mapped[str] = mapped_column(ForeignKey("incoming_payments.id"), index=True)
    payment_hash: Mapped[str] = mapped_column(String(64), unique=True)
    amount_msat: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    __table_args__ = (CheckConstraint("amount_msat > 0"),)


class Debt(Base):
    __tablename__ = "grant_debts"
    grant_id: Mapped[str] = mapped_column(ForeignKey("grant_proposals.id"), primary_key=True)
    principal_msat: Mapped[int] = mapped_column(BigInteger)
    outstanding_msat: Mapped[int] = mapped_column(BigInteger)
    recovered_msat: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (
        CheckConstraint(
            "principal_msat > 0 AND outstanding_msat >= 0 AND recovered_msat >= 0 "
            "AND principal_msat = outstanding_msat + recovered_msat"
        ),
    )


class Payout(Base):
    __tablename__ = "treasury_payouts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    intent_id: Mapped[str] = mapped_column(ForeignKey("payment_intents.id"), unique=True)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    payment_hash: Mapped[str] = mapped_column(String(64), unique=True)
    amount_msat: Mapped[int] = mapped_column(BigInteger)
    fee_limit_msat: Mapped[int] = mapped_column(BigInteger)
    fee_paid_msat: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    dispatched_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    updated_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    __table_args__ = (
        CheckConstraint(
            "amount_msat > 0 AND fee_limit_msat >= 0 "
            "AND (fee_paid_msat IS NULL OR fee_paid_msat >= 0)"
        ),
    )


class WorkerStatus(Base):
    __tablename__ = "treasury_worker_status"
    id: Mapped[str] = mapped_column(String(30), primary_key=True, default="treasury")
    observed_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    status: Mapped[str] = mapped_column(String(30))
    node_verified: Mapped[bool]
    message: Mapped[str] = mapped_column(String(100), default="")


class DispatchAuthorization(Base):
    """Worker-only, authenticated authorization; also a conservative spending budget charge."""

    __tablename__ = "treasury_dispatch_authorizations"
    payout_id: Mapped[str] = mapped_column(ForeignKey("treasury_payouts.id"), primary_key=True)
    clan_id: Mapped[str] = mapped_column(ForeignKey("clans.id"), index=True)
    intent_digest: Mapped[str] = mapped_column(String(64))
    payment_hash: Mapped[str] = mapped_column(String(64), unique=True)
    amount_msat: Mapped[int] = mapped_column(BigInteger)
    fee_limit_msat: Mapped[int] = mapped_column(BigInteger)
    authorized_at: Mapped[str] = mapped_column(String(40), index=True)
    authentication_tag: Mapped[str] = mapped_column(String(64))
    kes_per_btc: Mapped[str | None] = mapped_column(String(60), nullable=True)
    kes_cost_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    kes_rate_published_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    signer_trust_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    __table_args__ = (
        CheckConstraint("amount_msat > 0 AND fee_limit_msat >= 0"),
        CheckConstraint(
            "(kes_per_btc IS NULL AND kes_cost_minor IS NULL AND kes_rate_published_at IS NULL) OR "
            "(kes_per_btc IS NOT NULL AND kes_cost_minor IS NOT NULL AND kes_cost_minor > 0 "
            "AND kes_rate_published_at IS NOT NULL AND kes_rate_published_at > 0)",
            name="dispatch_kes_pair",
        ),
    )


class DepositPoll(Base):
    __tablename__ = "treasury_deposit_polls"
    incoming_id: Mapped[str] = mapped_column(ForeignKey("incoming_payments.id"), primary_key=True)
    last_checked_at: Mapped[str] = mapped_column(String(40), index=True)


class PayoutPoll(Base):
    """Worker-owned scheduling: a blocked clan cannot occupy every batch forever."""

    __tablename__ = "treasury_payout_polls"
    payout_id: Mapped[str] = mapped_column(ForeignKey("treasury_payouts.id"), primary_key=True)
    last_checked_at: Mapped[str] = mapped_column(String(40), index=True)
    next_attempt_at: Mapped[str] = mapped_column(String(40), index=True)
    reason: Mapped[str] = mapped_column(String(100), default="")


class ReceiveAuthorization(Base):
    """Worker-owned allocation accepted BEFORE any provider request."""

    __tablename__ = "treasury_receive_authorizations"
    incoming_id: Mapped[str] = mapped_column(ForeignKey("incoming_payments.id"), primary_key=True)
    identity: Mapped[dict] = mapped_column(JSON)
    authentication_tag: Mapped[str] = mapped_column(String(64))


class ReceiveInvoiceBinding(Base):
    """Insert once; neither runtime may update or delete an invoice binding."""

    __tablename__ = "treasury_receive_invoices"
    incoming_id: Mapped[str] = mapped_column(
        ForeignKey("treasury_receive_authorizations.incoming_id"), primary_key=True
    )
    provider_invoice_id: Mapped[str] = mapped_column(String(100), unique=True)
    payment_hash: Mapped[str] = mapped_column(String(64), unique=True)
    bolt11_digest: Mapped[str] = mapped_column(String(64))
    authentication_tag: Mapped[str] = mapped_column(String(64))
