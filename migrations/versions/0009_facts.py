"""Facts: what is true in a story right now, each with the stretch of turns it held for.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("story_id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("valid_from_sequence", sa.Integer(), nullable=False),
        # Null: still true. Set when a later stretch contradicted it — or a person retired it.
        sa.Column("valid_to_sequence", sa.Integer(), nullable=True),
        # Null: a person stated it. A fact a person stated is pinned: the extractor cannot
        # retire it.
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("pinned", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "valid_to_sequence IS NULL OR valid_to_sequence >= valid_from_sequence",
            name="ck_facts_range",
        ),
        sa.ForeignKeyConstraint(
            ["story_id"], ["stories.id"], name="fk_facts_story_id_stories", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_facts"),
    )
    # The world layer asks for a story's live facts on every turn.
    op.create_index("ix_facts_story_live", "facts", ["story_id", "valid_to_sequence"])


def downgrade() -> None:
    op.drop_table("facts")
