"""Asides: questions asked about a story out of character, kept apart from its messages.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "asides",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("story_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column(
            "asked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("provider", sa.String(length=200), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("context_audit", sa.Text(), nullable=True),
        sa.CheckConstraint("sequence >= 0", name="ck_asides_sequence_not_negative"),
        sa.ForeignKeyConstraint(
            ["story_id"], ["stories.id"], name="fk_asides_story_id_stories", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_asides"),
    )
    op.create_index("ix_asides_story_id", "asides", ["story_id"])


def downgrade() -> None:
    op.drop_index("ix_asides_story_id", table_name="asides")
    op.drop_table("asides")
