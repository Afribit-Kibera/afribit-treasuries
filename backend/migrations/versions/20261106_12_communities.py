"""Add communities: groups of clans, each with their own oversight keys and laptops."""

import sqlalchemy as sa
from alembic import op

revision = "20261106_12"
down_revision = "20261105_11"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "clan_communities",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("oversight_keys", sa.JSON, nullable=False),
        sa.Column("token_hashes", sa.JSON, nullable=False),
        sa.Column("join_code_hash", sa.String(64), nullable=True, unique=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    # Existing clans keep NULL: the default community, whose oversight is in the settings.
    with op.batch_alter_table("clans") as table:
        table.add_column(sa.Column("community_id", sa.String(40), nullable=True))
        table.create_foreign_key(
            "fk_clans_community_id", "clan_communities", ["community_id"], ["id"]
        )
        table.create_index("ix_clans_community_id", ["community_id"])


def downgrade():
    with op.batch_alter_table("clans") as table:
        table.drop_index("ix_clans_community_id")
        table.drop_constraint("fk_clans_community_id", type_="foreignkey")
        table.drop_column("community_id")
    op.drop_table("clan_communities")
