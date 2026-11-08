"""Keep exact network fee rates, and the coins a fee preview needs."""

import sqlalchemy as sa
from alembic import op

revision = "20261106_13"
down_revision = "20261106_12"
branch_labels = depends_on = None


def upgrade():
    for name in ("clan_wallet_chain_status", "clan_wallet_payouts"):
        with op.batch_alter_table(name) as table:
            table.add_column(sa.Column("fee_rate_sat_kwu", sa.Integer, nullable=True))
    with op.batch_alter_table("clan_wallets") as table:
        table.add_column(sa.Column("spendable_coins", sa.JSON, nullable=True))


def downgrade():
    with op.batch_alter_table("clan_wallets") as table:
        table.drop_column("spendable_coins")
    for name in ("clan_wallet_payouts", "clan_wallet_chain_status"):
        with op.batch_alter_table(name) as table:
            table.drop_column("fee_rate_sat_kwu")
