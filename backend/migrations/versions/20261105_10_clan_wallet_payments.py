"""Add clan wallet addresses, receipts, payout drafts, signatures, alarms and chain status."""

import sqlalchemy as sa
from alembic import op

revision = "20261105_10"
down_revision = "20261104_09"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "clan_wallet_addresses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("wallet_id", sa.String(36), sa.ForeignKey("clan_wallets.id"), nullable=False),
        sa.Column("address_index", sa.Integer, nullable=False),
        sa.Column("address", sa.String(100), nullable=False, unique=True),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("grant_id", sa.String(36), sa.ForeignKey("grant_proposals.id"), nullable=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("wallet_id", "address_index"),
        sa.CheckConstraint("address_index >= 0"),
        sa.CheckConstraint(
            "purpose IN ('contribution', 'repayment', 'grant_funding')",
            name="clan_wallet_address_purpose",
        ),
    )
    op.create_index("ix_clan_wallet_addresses_wallet_id", "clan_wallet_addresses", ["wallet_id"])
    op.create_table(
        "clan_wallet_receipts",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("wallet_id", sa.String(36), sa.ForeignKey("clan_wallets.id"), nullable=False),
        sa.Column(
            "address_id",
            sa.String(36),
            sa.ForeignKey("clan_wallet_addresses.id"),
            nullable=False,
        ),
        sa.Column("txid", sa.String(64), nullable=False),
        sa.Column("vout", sa.Integer, nullable=False),
        sa.Column("amount_sats", sa.BigInteger, nullable=False),
        sa.Column("block_height", sa.Integer, nullable=True),
        sa.Column("confirmations", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("credited_at", sa.String(40), nullable=True),
        sa.Column("first_seen_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("txid", "vout"),
        sa.CheckConstraint("amount_sats > 0 AND vout >= 0 AND confirmations >= 0"),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'dropped')", name="clan_wallet_receipt_status"
        ),
    )
    op.create_index("ix_clan_wallet_receipts_wallet_id", "clan_wallet_receipts", ["wallet_id"])
    op.create_index("ix_clan_wallet_receipts_address_id", "clan_wallet_receipts", ["address_id"])
    op.create_index("ix_clan_wallet_receipts_txid", "clan_wallet_receipts", ["txid"])
    op.create_index("ix_clan_wallet_receipts_status", "clan_wallet_receipts", ["status"])
    op.create_table(
        "clan_wallet_payout_requests",
        sa.Column("grant_id", sa.String(36), sa.ForeignKey("grant_proposals.id"), primary_key=True),
        sa.Column("wallet_id", sa.String(36), sa.ForeignKey("clan_wallets.id"), nullable=False),
        sa.Column("address", sa.String(100), nullable=False),
        sa.Column("reserved_sats", sa.BigInteger, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("last_error", sa.String(100), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.CheckConstraint("reserved_sats > 0"),
        sa.CheckConstraint(
            "status IN ('waiting', 'drafted', 'paid')", name="clan_wallet_request_status"
        ),
    )
    op.create_index(
        "ix_clan_wallet_payout_requests_wallet_id", "clan_wallet_payout_requests", ["wallet_id"]
    )
    op.create_index(
        "ix_clan_wallet_payout_requests_status", "clan_wallet_payout_requests", ["status"]
    )
    op.create_table(
        "clan_wallet_payouts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("wallet_id", sa.String(36), sa.ForeignKey("clan_wallets.id"), nullable=False),
        sa.Column("clan_id", sa.String(36), sa.ForeignKey("clans.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("psbt", sa.Text, nullable=False),
        sa.Column("txid", sa.String(64), nullable=False, unique=True),
        sa.Column("inputs", sa.JSON, nullable=False),
        sa.Column("change_index", sa.Integer, nullable=True),
        sa.Column("fee_sats", sa.BigInteger, nullable=False),
        sa.Column("max_fee_sats", sa.BigInteger, nullable=False),
        sa.Column("fee_rate_sat_vb", sa.Integer, nullable=False),
        sa.Column("fee_paid_by", sa.String(20), nullable=False),
        sa.Column("recipients", sa.JSON, nullable=False),
        sa.Column("replaces", sa.String(36), nullable=True),
        sa.Column("replaced_by", sa.String(36), nullable=True),
        sa.Column("raw_tx", sa.Text, nullable=True),
        sa.Column("block_height", sa.Integer, nullable=True),
        sa.Column("confirmations", sa.Integer, nullable=False),
        sa.Column("last_error", sa.String(100), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("broadcast_at", sa.String(40), nullable=True),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.CheckConstraint("fee_sats >= 0 AND max_fee_sats >= fee_sats AND fee_rate_sat_vb > 0"),
        sa.CheckConstraint(
            "status IN ('awaiting_signatures', 'broadcast', 'confirmed', 'replaced', 'expired')",
            name="clan_wallet_payout_status",
        ),
    )
    op.create_index("ix_clan_wallet_payouts_wallet_id", "clan_wallet_payouts", ["wallet_id"])
    op.create_index("ix_clan_wallet_payouts_clan_id", "clan_wallet_payouts", ["clan_id"])
    op.create_index("ix_clan_wallet_payouts_status", "clan_wallet_payouts", ["status"])
    op.create_table(
        "clan_wallet_signatures",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "payout_id", sa.String(36), sa.ForeignKey("clan_wallet_payouts.id"), nullable=False
        ),
        sa.Column("fingerprint", sa.String(8), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("psbt", sa.Text, nullable=False),
        sa.Column("invalid_at", sa.String(40), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("payout_id", "fingerprint"),
        sa.CheckConstraint("role IN ('signer', 'oversight')", name="clan_wallet_signature_role"),
    )
    op.create_index("ix_clan_wallet_signatures_payout_id", "clan_wallet_signatures", ["payout_id"])
    op.create_table(
        "clan_wallet_alarms",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("wallet_id", sa.String(36), sa.ForeignKey("clan_wallets.id"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("reference", sa.String(160), nullable=False),
        sa.Column("detail", sa.JSON, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("kind", "reference"),
    )
    op.create_index("ix_clan_wallet_alarms_wallet_id", "clan_wallet_alarms", ["wallet_id"])
    op.create_table(
        "clan_wallet_chain_status",
        sa.Column("network", sa.String(20), primary_key=True),
        sa.Column("tip_height", sa.Integer, nullable=False),
        sa.Column("fee_rate_sat_vb", sa.Integer, nullable=False),
        sa.Column("observed_at", sa.String(40), nullable=False),
        sa.Column("message", sa.String(100), nullable=False),
    )


def downgrade():
    for table in (
        "clan_wallet_chain_status",
        "clan_wallet_alarms",
        "clan_wallet_signatures",
        "clan_wallet_payouts",
        "clan_wallet_payout_requests",
        "clan_wallet_receipts",
        "clan_wallet_addresses",
    ):
        op.drop_table(table)
