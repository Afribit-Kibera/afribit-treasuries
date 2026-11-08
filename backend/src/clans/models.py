from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from clans.db import Base


def new_id() -> str:
    return str(uuid4())


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    display_name: Mapped[str] = mapped_column(String(100))
    is_test_user: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    demo_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)


class Clan(Base):
    __tablename__ = "clans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="active")
    # The community whose oversight approves this clan's payouts. None: the default
    # community (Afribit), set in the server settings. See clans.communities.
    community_id: Mapped[str | None] = mapped_column(
        ForeignKey("clan_communities.id"), nullable=True, index=True
    )


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("clan_id", "user_id"),
        Index(
            "one_active_clan_per_account",
            "user_id",
            unique=True,
            postgresql_where=text("active = true"),
            sqlite_where=text("active = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    clan_id: Mapped[str] = mapped_column(ForeignKey("clans.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")
    is_signer: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PolicyVersion(Base):
    __tablename__ = "clan_policy_versions"
    __table_args__ = (
        UniqueConstraint("clan_id", "version"),
        CheckConstraint("member_vote_quorum > 0"),
        CheckConstraint("signer_threshold > 0"),
        CheckConstraint("currency IN ('KES', 'BTC')"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    clan_id: Mapped[str] = mapped_column(ForeignKey("clans.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    member_vote_quorum: Mapped[int] = mapped_column(Integer)
    signer_threshold: Mapped[int] = mapped_column(Integer)
    beneficiary_can_approve: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    clan_id: Mapped[str] = mapped_column(ForeignKey("clans.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    event_type: Mapped[str] = mapped_column(String(80))
    occurred_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
