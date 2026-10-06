"""Summaries: compressed stretches of a story, carried forward once the turns no longer fit.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "summaries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("story_id", sa.Uuid(), nullable=False),
        sa.Column("from_sequence", sa.Integer(), nullable=False),
        sa.Column("to_sequence", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("from_sequence <= to_sequence", name="ck_summaries_range"),
        sa.ForeignKeyConstraint(
            ["story_id"], ["stories.id"], name="fk_summaries_story_id_stories", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_summaries"),
        # One summary per starting point: a stretch is compressed once.
        sa.UniqueConstraint("story_id", "from_sequence", name="uq_summaries_story_from"),
    )


def downgrade() -> None:
    op.drop_table("summaries")
