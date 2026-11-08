"""Persisted production identities, consent, governance and settlement records."""

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    null,
)
from sqlalchemy.orm import Mapped, mapped_column

from clans.db import Base
from clans.models import new_id, now_iso


class Profile(Base):
    __tablename__ = "account_profiles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    handle: Mapped[str] = mapped_column(String(80), unique=True)
    passkey_handle: Mapped[str] = mapped_column(String(80), unique=True)
    terms_version: Mapped[str] = mapped_column(String(30))
    onboarded_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)


class Passkey(Base):
    __tablename__ = "passkeys"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    credential_id: Mapped[str] = mapped_column(String(2048), unique=True)
    public_key: Mapped[str] = mapped_column(Text)
    sign_count: Mapped[int] = mapped_column(BigInteger, default=0)
    backed_up: Mapped[bool] = mapped_column(Boolean, default=False)
    label: Mapped[str] = mapped_column(String(100), default="My passkey")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    last_used_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    expires_at: Mapped[str] = mapped_column(String(40), index=True)
    authenticated_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class AuthChallenge(Base):
    __tablename__ = "auth_challenges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    binding_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(40))
    challenge: Mapped[str] = mapped_column(String(256))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    expires_at: Mapped[str] = mapped_column(String(40), index=True)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class RecoveryCode(Base):
    __tablename__ = "recovery_codes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class RateLimit(Base):
    __tablename__ = "request_limits"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer)
    resets_at: Mapped[int] = mapped_column(BigInteger)


class ClanConfig(Base):
    __tablename__ = "clan_configurations"
    clan_id: Mapped[str] = mapped_column(ForeignKey("clans.id"), primary_key=True)
    description: Mapped[str] = mapped_column(String(500), default="")
    target_signers: Mapped[int] = mapped_column(Integer)
    custody_terms_version: Mapped[str] = mapped_column(String(30))
    custody_accepted_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (CheckConstraint("target_signers IN (3, 5, 7)"),)


class Invitation(Base):
    __tablename__ = "clan_invitations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    clan_id: Mapped[str] = mapped_column(ForeignKey("clans.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    is_signer: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[str] = mapped_column(String(40))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    accepted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    accepted_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)


class Treasury(Base):
    __tablename__ = "clan_treasuries"
    clan_id: Mapped[str] = mapped_column(ForeignKey("clans.id"), primary_key=True)
    balance_sats: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved_sats: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (
        CheckConstraint(
            "balance_sats >= 0 AND reserved_sats >= 0 AND balance_sats >= reserved_sats"
        ),
    )


class Grant(Base):
    __tablename__ = "grant_proposals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    clan_id: Mapped[str] = mapped_column(ForeignKey("clans.id"), index=True)
    beneficiary_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    purpose: Mapped[str] = mapped_column(String(1000))
    amount_sats: Mapped[int] = mapped_column(BigInteger)
    obligation_currency: Mapped[str] = mapped_column(String(3), default="BTC")
    principal_minor: Mapped[int] = mapped_column(BigInteger)
    outstanding_minor: Mapped[int] = mapped_column(BigInteger)
    recovered_sats: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(30), default="voting", index=True)
    policy_snapshot: Mapped[dict] = mapped_column(JSON)
    eligible_voters: Mapped[list] = mapped_column(JSON)
    eligible_signers: Mapped[list] = mapped_column(JSON)
    accepted_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    __table_args__ = (
        CheckConstraint("amount_sats > 0 AND principal_minor > 0 AND outstanding_minor >= 0"),
    )


class Vote(Base):
    __tablename__ = "grant_votes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    grant_id: Mapped[str] = mapped_column(ForeignKey("grant_proposals.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    choice: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    __table_args__ = (
        UniqueConstraint("grant_id", "user_id"),
        CheckConstraint("choice IN ('approve', 'reject', 'abstain')"),
    )


class PaymentIntent(Base):
    __tablename__ = "payment_intents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    grant_id: Mapped[str] = mapped_column(ForeignKey("grant_proposals.id"), index=True)
    digest: Mapped[str] = mapped_column(String(64), unique=True)
    canonical: Mapped[dict] = mapped_column(JSON)
    bolt11: Mapped[str] = mapped_column(Text)
    payment_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[str] = mapped_column(String(40))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(30), default="awaiting_approvals")
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)


class SignerApproval(Base):
    __tablename__ = "signer_approvals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    intent_id: Mapped[str] = mapped_column(ForeignKey("payment_intents.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    passkey_id: Mapped[str] = mapped_column(ForeignKey("passkeys.id"))
    assertion: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    __table_args__ = (UniqueConstraint("intent_id", "user_id"),)


class IncomingPayment(Base):
    __tablename__ = "incoming_payments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    clan_id: Mapped[str] = mapped_column(ForeignKey("clans.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    grant_id: Mapped[str | None] = mapped_column(ForeignKey("grant_proposals.id"), nullable=True)
    method: Mapped[str] = mapped_column(String(20), default="lightning")
    amount_sats: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(30), default="creating", index=True)
    provider_invoice_id: Mapped[str | None] = mapped_column(
        String(100), unique=True, nullable=True, server_default=null()
    )
    bolt11: Mapped[str | None] = mapped_column(Text, nullable=True, server_default=null())
    checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True, server_default=null())
    expires_at: Mapped[str | None] = mapped_column(String(40), nullable=True, server_default=null())
    credited_sats: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    __table_args__ = (CheckConstraint("amount_sats > 0 AND credited_sats >= 0"),)


class Receipt(Base):
    __tablename__ = "settlement_receipts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    incoming_id: Mapped[str] = mapped_column(ForeignKey("incoming_payments.id"), index=True)
    provider_reference: Mapped[str] = mapped_column(String(256), unique=True)
    amount_sats: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)


class Journal(Base):
    __tablename__ = "treasury_journals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    clan_id: Mapped[str] = mapped_column(ForeignKey("clans.id"), index=True)
    event: Mapped[str] = mapped_column(String(40))
    reference: Mapped[str] = mapped_column(String(256), unique=True)
    amount_sats: Mapped[int] = mapped_column(BigInteger)
    debit_account: Mapped[str] = mapped_column(String(50))
    credit_account: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    __table_args__ = (CheckConstraint("amount_sats > 0"),)


class Operation(Base):
    __tablename__ = "idempotent_operations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    scope: Mapped[str] = mapped_column(String(120))
    key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    __table_args__ = (UniqueConstraint("user_id", "scope", "key"),)


def after(seconds: int) -> str:
    from datetime import timedelta

    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()
