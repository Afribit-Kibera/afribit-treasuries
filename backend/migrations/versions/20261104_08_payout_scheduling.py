"""Persist payment-local deferrals and fair worker scheduling."""

import sqlalchemy as sa
from alembic import op

revision = "20261104_08"
down_revision = "20261104_07"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "treasury_payout_polls",
        sa.Column(
            "payout_id", sa.String(36), sa.ForeignKey("treasury_payouts.id"), primary_key=True
        ),
        sa.Column("last_checked_at", sa.String(40), nullable=False),
        sa.Column("next_attempt_at", sa.String(40), nullable=False),
        sa.Column("reason", sa.String(100), nullable=False),
    )
    for name in ["last_checked_at", "next_attempt_at"]:
        op.create_index("ix_treasury_payout_polls_" + name, "treasury_payout_polls", [name])


def downgrade():
    raise RuntimeError("Payment retry history must survive financial rollback")
