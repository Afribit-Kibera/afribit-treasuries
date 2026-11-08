"""Add clan multisig wallet setup records (public keys and confirmations only)."""

import sqlalchemy as sa
from alembic import op

revision = "20261104_09"
down_revision = "20261104_08"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "clan_wallets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("clan_id", sa.String(36), sa.ForeignKey("clans.id"), nullable=False),
        sa.Column("generation", sa.Integer, nullable=False),
        sa.Column("network", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("oversight_keys", sa.JSON, nullable=False),
        sa.Column("signer_count", sa.Integer, nullable=False),
        sa.Column("recovery_threshold", sa.Integer, nullable=False),
        sa.Column("recovery_blocks", sa.Integer, nullable=False),
        sa.Column("wallet_code", sa.String(8), nullable=True),
        sa.Column("descriptor_external", sa.Text, nullable=True),
        sa.Column("descriptor_internal", sa.Text, nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("activated_at", sa.String(40), nullable=True),
        sa.UniqueConstraint("clan_id", "generation"),
        sa.CheckConstraint("signer_count IN (3, 5, 7)"),
        sa.CheckConstraint(
            "status IN ('collecting_keys', 'confirming', 'active', 'retired')",
            name="clan_wallet_status",
        ),
    )
    op.create_index("ix_clan_wallets_clan_id", "clan_wallets", ["clan_id"])
    op.create_index("ix_clan_wallets_status", "clan_wallets", ["status"])
    op.create_table(
        "clan_wallet_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("wallet_id", sa.String(36), sa.ForeignKey("clan_wallets.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("key_expression", sa.Text, nullable=False),
        sa.Column("fingerprint", sa.String(8), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("wallet_id", "user_id"),
        sa.UniqueConstraint("wallet_id", "fingerprint"),
    )
    op.create_index("ix_clan_wallet_keys_wallet_id", "clan_wallet_keys", ["wallet_id"])
    op.create_table(
        "clan_wallet_confirmations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("wallet_id", sa.String(36), sa.ForeignKey("clan_wallets.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("wallet_code", sa.String(8), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("wallet_id", "user_id"),
    )
    op.create_index(
        "ix_clan_wallet_confirmations_wallet_id", "clan_wallet_confirmations", ["wallet_id"]
    )


def downgrade():
    raise RuntimeError("Wallet key history must survive financial rollback")
