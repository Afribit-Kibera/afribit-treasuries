"""Authenticated KES valuation at dispatch, preserving old authorization records."""

import sqlalchemy as sa
from alembic import op

revision = "20261103_05"
down_revision = "20261103_04"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("treasury_dispatch_authorizations") as batch:
        batch.add_column(sa.Column("kes_per_btc", sa.String(60)))
        batch.add_column(sa.Column("kes_cost_minor", sa.BigInteger()))
        batch.add_column(sa.Column("kes_rate_published_at", sa.BigInteger()))
        batch.add_column(sa.Column("signer_trust_digest", sa.String(64)))
        batch.create_check_constraint(
            "dispatch_kes_pair",
            "(kes_per_btc IS NULL AND kes_cost_minor IS NULL AND kes_rate_published_at IS NULL) OR "
            "(kes_per_btc IS NOT NULL AND kes_cost_minor IS NOT NULL AND kes_cost_minor > 0 "
            "AND kes_rate_published_at IS NOT NULL AND kes_rate_published_at > 0)",
        )


def downgrade():
    raise RuntimeError("Preserve dispatch valuations; financial downgrade is prohibited.")
