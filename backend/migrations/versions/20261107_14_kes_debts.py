"""Grant debts in KES: keep the rate each repayment was counted at, and what it counted for.

Existing grants keep `obligation_currency = 'BTC'` and are not rewritten.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261107_14"
down_revision = "20261106_13"
branch_labels = depends_on = None

COLUMNS = (
    ("kes_per_btc", sa.String(60)),
    ("kes_rate_published_at", sa.BigInteger),
    ("kes_rate_seen_at", sa.String(40)),
    ("kes_credited_minor", sa.BigInteger),
    ("kes_surplus_minor", sa.BigInteger),
    ("kes_owed_after_minor", sa.BigInteger),
    ("credit_note", sa.String(40)),
)


def upgrade():
    with op.batch_alter_table("clan_wallet_receipts") as table:
        for name, kind in COLUMNS:
            table.add_column(sa.Column(name, kind, nullable=True))
        table.create_check_constraint(
            "clan_wallet_kes_rate", "(kes_per_btc IS NULL) = (kes_rate_published_at IS NULL)"
        )


def downgrade():
    with op.batch_alter_table("clan_wallet_receipts") as table:
        table.drop_constraint("clan_wallet_kes_rate", type_="check")
        for name, _ in reversed(COLUMNS):
            table.drop_column(name)
