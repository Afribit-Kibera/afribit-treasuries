"""Authenticated worker dispatch and conservative rolling spending budgets."""

import sqlalchemy as sa
from alembic import op

revision = "20261103_04"
down_revision = "20261103_03"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "treasury_dispatch_authorizations",
        sa.Column("payout_id", sa.String(36), primary_key=True),
        sa.Column("clan_id", sa.String(36), nullable=False),
        sa.Column("intent_digest", sa.String(64), nullable=False),
        sa.Column("payment_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("amount_msat", sa.BigInteger(), nullable=False),
        sa.Column("fee_limit_msat", sa.BigInteger(), nullable=False),
        sa.Column("authorized_at", sa.String(40), nullable=False),
        sa.Column("authentication_tag", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["payout_id"], ["treasury_payouts.id"]),
        sa.ForeignKeyConstraint(["clan_id"], ["clans.id"]),
        sa.CheckConstraint("amount_msat > 0 AND fee_limit_msat >= 0"),
    )
    op.create_index(
        "ix_treasury_dispatch_authorizations_clan_id",
        "treasury_dispatch_authorizations",
        ["clan_id"],
    )
    op.create_index(
        "ix_treasury_dispatch_authorizations_authorized_at",
        "treasury_dispatch_authorizations",
        ["authorized_at"],
    )


def downgrade():
    raise RuntimeError("Dispatch records must be preserved; financial downgrade is prohibited.")
