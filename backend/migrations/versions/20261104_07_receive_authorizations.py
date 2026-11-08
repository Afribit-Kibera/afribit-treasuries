"""Worker-owned immutable receiving allocation and invoice binding."""

import sqlalchemy as sa
from alembic import op

revision = "20261104_07"
down_revision = "20261103_06"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "treasury_receive_authorizations",
        sa.Column(
            "incoming_id", sa.String(36), sa.ForeignKey("incoming_payments.id"), primary_key=True
        ),
        sa.Column("identity", sa.JSON(), nullable=False),
        sa.Column("authentication_tag", sa.String(64), nullable=False),
    )
    op.create_table(
        "treasury_receive_invoices",
        sa.Column(
            "incoming_id",
            sa.String(36),
            sa.ForeignKey("treasury_receive_authorizations.incoming_id"),
            primary_key=True,
        ),
        sa.Column("provider_invoice_id", sa.String(100), nullable=False, unique=True),
        sa.Column("payment_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("bolt11_digest", sa.String(64), nullable=False),
        sa.Column("authentication_tag", sa.String(64), nullable=False),
    )
    # Older pending invoices have no independent binding. Do not invent one from
    # mutable historical rows. Preserve all evidence and require operator review.
    op.execute(
        "UPDATE incoming_payments SET status='review_required' "
        "WHERE status NOT IN ('settled','failed')"
    )


def downgrade():
    raise RuntimeError("Receiving authorizations must survive financial rollback")
