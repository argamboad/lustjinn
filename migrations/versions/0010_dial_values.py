"""Dial values: what a story has set, one row per dial it changed.

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dial_values",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("story_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        # Stored form: a level index, true/false, an option key, a JSON array, or text. The
        # pack says which; the row does not know.
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["story_id"],
            ["stories.id"],
            name="fk_dial_values_story_id_stories",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dial_values"),
        sa.UniqueConstraint("story_id", "key", name="uq_dial_values_story_key"),
    )


def downgrade() -> None:
    op.drop_table("dial_values")
