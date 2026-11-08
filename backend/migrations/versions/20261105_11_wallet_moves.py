"""Add wallet generations that replace each other, and refresh and move payments."""

import sqlalchemy as sa
from alembic import op

revision = "20261105_11"
down_revision = "20261105_10"
branch_labels = depends_on = None

KIND_RULE = (
    "(kind = 'grant' AND to_wallet_id IS NULL AND destination_index IS NULL) OR "
    "(kind IN ('refresh', 'move') AND to_wallet_id IS NOT NULL "
    "AND destination_index >= 0 AND destination_address IS NOT NULL)"
)


def upgrade():
    with op.batch_alter_table("clan_wallets") as table:
        table.add_column(
            sa.Column("started_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True)
        )
        table.add_column(sa.Column("start_reason", sa.String(30), nullable=True))
        table.add_column(sa.Column("retired_at", sa.String(40), nullable=True))
        table.add_column(sa.Column("balance_sats", sa.BigInteger, nullable=True))
    with op.batch_alter_table("clan_wallet_payouts") as table:
        table.add_column(sa.Column("kind", sa.String(10), nullable=False, server_default="grant"))
        table.add_column(
            sa.Column(
                "to_wallet_id", sa.String(36), sa.ForeignKey("clan_wallets.id"), nullable=True
            )
        )
        table.add_column(sa.Column("destination_index", sa.Integer, nullable=True))
        table.add_column(sa.Column("destination_address", sa.String(100), nullable=True))
        table.create_check_constraint("clan_wallet_payout_kind", KIND_RULE)
        table.create_index("ix_clan_wallet_payouts_to_wallet_id", ["to_wallet_id"])


def downgrade():
    with op.batch_alter_table("clan_wallet_payouts") as table:
        table.drop_index("ix_clan_wallet_payouts_to_wallet_id")
        table.drop_constraint("clan_wallet_payout_kind", type_="check")
        for column in ("destination_address", "destination_index", "to_wallet_id", "kind"):
            table.drop_column(column)
    with op.batch_alter_table("clan_wallets") as table:
        for column in ("balance_sats", "retired_at", "start_reason", "started_by"):
            table.drop_column(column)
