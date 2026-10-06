"""Trackers: the meters a story keeps, drawn by the model each reply and read back.

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trackers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("story_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("max", sa.Float(), nullable=False),
        # What the last turn was worth: computed from the value read back, never believed.
        sa.Column("delta", sa.Float(), server_default="0", nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("means", sa.Text(), nullable=True),
        sa.Column("anchors", sa.Text(), nullable=True),
        sa.Column("rule", sa.Text(), nullable=True),
        sa.Column("updated_at_sequence", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("max > 0", name="ck_trackers_max_positive"),
        sa.ForeignKeyConstraint(
            ["story_id"], ["stories.id"], name="fk_trackers_story_id_stories", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_trackers"),
    )
    # One meter of a name per story, whatever the case: the model reads names back loosely.
    op.create_index(
        "uq_trackers_story_name_lower",
        "trackers",
        ["story_id", sa.literal_column("lower(name)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_trackers_story_name_lower", table_name="trackers")
    op.drop_table("trackers")
