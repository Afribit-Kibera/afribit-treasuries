"""One active clan per account; retain all membership and grant history."""

import sqlalchemy as sa
from alembic import op

revision = "20261103_06"
down_revision = "20261103_05"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    duplicates = connection.execute(
        sa.text(
            "SELECT user_id FROM memberships WHERE active = true "
            "GROUP BY user_id HAVING COUNT(*) > 1"
        )
    ).first()
    if duplicates:
        raise RuntimeError(
            "Review existing multiple-clan memberships before upgrading; none were removed"
        )
    op.create_index(
        "one_active_clan_per_account",
        "memberships",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("active = true"),
        sqlite_where=sa.text("active = 1"),
    )


def downgrade():
    raise RuntimeError("Membership protection must not be removed by financial rollback")
