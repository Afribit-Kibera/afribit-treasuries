"""Private account contacts and delayed, clan-approved access recovery."""

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from clans.db import Base
from clans.models import new_id, now_iso


class Contact(Base):
    __tablename__ = "account_contacts"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    phone_number: Mapped[str] = mapped_column(String(20))
    lightning_address: Mapped[str | None] = mapped_column(String(254), nullable=True)
    recovery_consent_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    updated_at: Mapped[str] = mapped_column(String(40), default=now_iso)


class AccessRecovery(Base):
    __tablename__ = "account_access_recoveries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    credential_id: Mapped[str] = mapped_column(String(2048), unique=True)
    public_key: Mapped[str] = mapped_column(Text)
    sign_count: Mapped[int] = mapped_column(BigInteger)
    backed_up: Mapped[bool] = mapped_column(Boolean)
    canonical: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    claim_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    expires_at: Mapped[str] = mapped_column(String(40))
    ready_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class AccessRecoveryApproval(Base):
    __tablename__ = "account_recovery_approvals"
    __table_args__ = (UniqueConstraint("recovery_id", "clan_id", "user_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    recovery_id: Mapped[str] = mapped_column(ForeignKey("account_access_recoveries.id"), index=True)
    clan_id: Mapped[str] = mapped_column(ForeignKey("clans.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    passkey_id: Mapped[str] = mapped_column(ForeignKey("passkeys.id"))
    proof: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)


class AccessRecoveryClan(Base):
    __tablename__ = "account_recovery_clans"
    recovery_id: Mapped[str] = mapped_column(
        ForeignKey("account_access_recoveries.id"), primary_key=True
    )
    clan_id: Mapped[str] = mapped_column(ForeignKey("clans.id"), primary_key=True, index=True)
