"""Clan multisig wallet records. Clans stores public keys only, never anything that can spend."""

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from clans.db import Base
from clans.models import new_id, now_iso

WALLET_STATUSES = ("collecting_keys", "confirming", "active", "retired")
ADDRESS_PURPOSES = ("contribution", "repayment", "grant_funding")
# Stored payout statuses. Before broadcast, the view also shows "awaiting_oversight" and
# "broadcasting", worked out from the signatures collected.
PAYOUT_STATUSES = ("awaiting_signatures", "broadcast", "confirmed", "replaced", "expired")
LIVE_PAYOUT_STATUSES = ("awaiting_signatures", "broadcast")
KIND_RULE = (
    "(kind = 'grant' AND to_wallet_id IS NULL AND destination_index IS NULL) OR "
    "(kind IN ('refresh', 'move') AND to_wallet_id IS NOT NULL "
    "AND destination_index >= 0 AND destination_address IS NOT NULL)"
)
# grant: pays beneficiaries. refresh: moves coins to the wallet's own change address,
# so the recovery wait starts again. move: empties an earlier wallet into the newest.
PAYOUT_KINDS = ("grant", "refresh", "move")


class ClanWalletRecord(Base):
    """One wallet generation for a clan. A key or roster change creates a new generation.

    The newest active generation receives money. Once a newer one is active, the older
    one is `retired`: the chain watcher keeps watching it and moves its coins across.
    """

    __tablename__ = "clan_wallets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    clan_id: Mapped[str] = mapped_column(ForeignKey("clans.id"), index=True)
    generation: Mapped[int] = mapped_column(Integer, default=1)
    network: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="collecting_keys", index=True)
    # Afribit's oversight public keys, in order. Any one of them can approve a payout.
    oversight_keys: Mapped[list] = mapped_column(JSON)
    signer_count: Mapped[int] = mapped_column(Integer)
    recovery_threshold: Mapped[int] = mapped_column(Integer)
    recovery_blocks: Mapped[int] = mapped_column(Integer)
    # Set once every signatory key is in; cleared again if a key changes before activation.
    wallet_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    descriptor_external: Mapped[str | None] = mapped_column(Text, nullable=True)
    descriptor_internal: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    activated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # The signatory who started this generation while an earlier one was active.
    started_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    start_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    retired_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # The chain watcher's last view of the coins in this wallet, for display.
    balance_sats: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Sizes of the coins no payout is spending, largest first, for fee previews.
    spendable_coins: Mapped[list | None] = mapped_column(JSON, nullable=True)
    __table_args__ = (
        UniqueConstraint("clan_id", "generation"),
        CheckConstraint("signer_count IN (3, 5, 7)"),
        CheckConstraint(
            "status IN ('collecting_keys', 'confirming', 'active', 'retired')",
            name="clan_wallet_status",
        ),
    )


class WalletSignerKey(Base):
    """A signatory's account-level public key, created on their own phone."""

    __tablename__ = "clan_wallet_keys"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    wallet_id: Mapped[str] = mapped_column(ForeignKey("clan_wallets.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    key_expression: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    __table_args__ = (
        UniqueConstraint("wallet_id", "user_id"),
        UniqueConstraint("wallet_id", "fingerprint"),
    )


class WalletConfirmation(Base):
    """A signatory confirmed that their phone computed the same wallet code."""

    __tablename__ = "clan_wallet_confirmations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    wallet_id: Mapped[str] = mapped_column(ForeignKey("clan_wallets.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    wallet_code: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    __table_args__ = (UniqueConstraint("wallet_id", "user_id"),)


class WalletAddress(Base):
    """A receiving address handed out for one purpose. Index 0 is the clan's main address.

    The web app derives and stores these; the worker re-derives each one before crediting.
    """

    __tablename__ = "clan_wallet_addresses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    wallet_id: Mapped[str] = mapped_column(ForeignKey("clan_wallets.id"), index=True)
    address_index: Mapped[int] = mapped_column(Integer)
    address: Mapped[str] = mapped_column(String(100), unique=True)
    purpose: Mapped[str] = mapped_column(String(20))
    grant_id: Mapped[str | None] = mapped_column(ForeignKey("grant_proposals.id"), nullable=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    __table_args__ = (
        UniqueConstraint("wallet_id", "address_index"),
        CheckConstraint("address_index >= 0"),
        CheckConstraint(
            "purpose IN ('contribution', 'repayment', 'grant_funding')",
            name="clan_wallet_address_purpose",
        ),
    )


class WalletReceipt(Base):
    """One payment seen at a clan address, identified by txid:vout. Worker-owned."""

    __tablename__ = "clan_wallet_receipts"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    wallet_id: Mapped[str] = mapped_column(ForeignKey("clan_wallets.id"), index=True)
    address_id: Mapped[str] = mapped_column(ForeignKey("clan_wallet_addresses.id"), index=True)
    txid: Mapped[str] = mapped_column(String(64), index=True)
    vout: Mapped[int] = mapped_column(Integer)
    amount_sats: Mapped[int] = mapped_column(BigInteger)
    block_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmations: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    credited_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    first_seen_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    updated_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    # Repayments of a KES debt: the KES/BTC rate when the watcher first saw the payment,
    # and what it counted for. Kept so every credit can be checked and worked out again.
    kes_per_btc: Mapped[str | None] = mapped_column(String(60), nullable=True)
    kes_rate_published_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    kes_rate_seen_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    kes_credited_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    kes_surplus_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    kes_owed_after_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Why a confirmed payment isn't counted yet, for example "waiting_for_rate".
    credit_note: Mapped[str | None] = mapped_column(String(40), nullable=True)
    __table_args__ = (
        UniqueConstraint("txid", "vout"),
        CheckConstraint("amount_sats > 0 AND vout >= 0 AND confirmations >= 0"),
        CheckConstraint(
            "(kes_per_btc IS NULL) = (kes_rate_published_at IS NULL)", name="clan_wallet_kes_rate"
        ),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'dropped')", name="clan_wallet_receipt_status"
        ),
    )


class WalletPayoutRequest(Base):
    """A beneficiary's Bitcoin address for an accepted grant. The worker builds the payout."""

    __tablename__ = "clan_wallet_payout_requests"
    grant_id: Mapped[str] = mapped_column(ForeignKey("grant_proposals.id"), primary_key=True)
    wallet_id: Mapped[str] = mapped_column(ForeignKey("clan_wallets.id"), index=True)
    address: Mapped[str] = mapped_column(String(100))
    # Held from the clan's confirmed balance when the address was first given.
    reserved_sats: Mapped[int] = mapped_column(BigInteger)
    # waiting: needs a payout built; drafted: one is being signed; paid: confirmed.
    status: Mapped[str] = mapped_column(String(20), default="waiting", index=True)
    last_error: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    updated_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    __table_args__ = (
        CheckConstraint("reserved_sats > 0"),
        CheckConstraint(
            "status IN ('waiting', 'drafted', 'paid')", name="clan_wallet_request_status"
        ),
    )


class WalletPayout(Base):
    """An unsigned payout built by the worker. The web app never changes these rows."""

    __tablename__ = "clan_wallet_payouts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    wallet_id: Mapped[str] = mapped_column(ForeignKey("clan_wallets.id"), index=True)
    clan_id: Mapped[str] = mapped_column(ForeignKey("clans.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="awaiting_signatures", index=True)
    kind: Mapped[str] = mapped_column(String(10), default="grant")
    psbt: Mapped[str] = mapped_column(Text)
    txid: Mapped[str] = mapped_column(String(64), unique=True)
    # "txid:vout" of every coin spent. A new version of a payout spends the same coins.
    inputs: Mapped[list] = mapped_column(JSON)
    change_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fee_sats: Mapped[int] = mapped_column(BigInteger)
    max_fee_sats: Mapped[int] = mapped_column(BigInteger)
    fee_rate_sat_vb: Mapped[int] = mapped_column(Integer)
    # The exact rate in sats per 1,000 weight units (250 = 1 sat/vB). Older rows have none.
    fee_rate_sat_kwu: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fee_paid_by: Mapped[str] = mapped_column(String(20))
    # [{grant_id, name, address, approved_sats, received_sats}], in payment order.
    # Empty for refreshes and moves, which pay one change address of a clan wallet.
    recipients: Mapped[list] = mapped_column(JSON)
    to_wallet_id: Mapped[str | None] = mapped_column(
        ForeignKey("clan_wallets.id"), nullable=True, index=True
    )
    destination_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    destination_address: Mapped[str | None] = mapped_column(String(100), nullable=True)
    replaces: Mapped[str | None] = mapped_column(String(36), nullable=True)
    replaced_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    raw_tx: Mapped[str | None] = mapped_column(Text, nullable=True)
    block_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmations: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    broadcast_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    updated_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    __table_args__ = (
        CheckConstraint("fee_sats >= 0 AND max_fee_sats >= fee_sats AND fee_rate_sat_vb > 0"),
        CheckConstraint(
            "status IN ('awaiting_signatures', 'broadcast', 'confirmed', 'replaced', 'expired')",
            name="clan_wallet_payout_status",
        ),
        CheckConstraint(KIND_RULE, name="clan_wallet_payout_kind"),
    )


class WalletSignature(Base):
    """A signed copy of a payout from one key. The worker checks it before broadcasting."""

    __tablename__ = "clan_wallet_signatures"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    payout_id: Mapped[str] = mapped_column(ForeignKey("clan_wallet_payouts.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(8))
    role: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    psbt: Mapped[str] = mapped_column(Text)
    # Set by the worker when BDK rejects this signature. The row is kept as evidence.
    invalid_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    __table_args__ = (
        UniqueConstraint("payout_id", "fingerprint"),
        CheckConstraint("role IN ('signer', 'oversight')", name="clan_wallet_signature_role"),
    )


class WalletAlarm(Base):
    """Something Afribit and the clan must hear about, recorded once per cause."""

    __tablename__ = "clan_wallet_alarms"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    wallet_id: Mapped[str] = mapped_column(ForeignKey("clan_wallets.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    reference: Mapped[str] = mapped_column(String(160))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    __table_args__ = (UniqueConstraint("kind", "reference"),)


class ChainStatus(Base):
    """The chain watcher's last view of the network. Fee quotes need a recent one."""

    __tablename__ = "clan_wallet_chain_status"
    network: Mapped[str] = mapped_column(String(20), primary_key=True)
    tip_height: Mapped[int] = mapped_column(Integer)
    fee_rate_sat_vb: Mapped[int] = mapped_column(Integer)
    fee_rate_sat_kwu: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_at: Mapped[str] = mapped_column(String(40), default=now_iso)
    message: Mapped[str] = mapped_column(String(100), default="")
