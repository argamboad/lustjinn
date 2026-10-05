"""Stories and messages, with the characters and personas they point at.

Generated from the models with `alembic revision --autogenerate`, then read and tidied by hand.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "characters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("card", sa.Text(), nullable=False),
        sa.Column("opening", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_characters"),
    )
    # Unique without regard to case: "Elena" and "elena" are the same name.
    op.create_index(
        "uq_characters_name_lower", "characters", [sa.literal_column("lower(name)")], unique=True
    )

    op.create_table(
        "personas",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_personas"),
    )
    op.create_index(
        "uq_personas_name_lower", "personas", [sa.literal_column("lower(name)")], unique=True
    )

    op.create_table(
        "stories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("character_id", sa.Uuid(), nullable=False),
        sa.Column("persona_id", sa.Uuid(), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        # RESTRICT: a character or persona a story uses cannot be deleted.
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["characters.id"],
            name="fk_stories_character_id_characters",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["personas.id"],
            name="fk_stories_persona_id_personas",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stories"),
    )
    op.create_index("ix_stories_character_id", "stories", ["character_id"])
    op.create_index("ix_stories_persona_id", "stories", ["persona_id"])

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("story_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("provider", sa.String(length=200), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("context_audit", sa.Text(), nullable=True),
        sa.Column(
            "sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('user', 'assistant', 'system')", name="ck_messages_role"),
        sa.CheckConstraint("sequence >= 1", name="ck_messages_sequence_positive"),
        sa.ForeignKeyConstraint(
            ["story_id"], ["stories.id"], name="fk_messages_story_id_stories", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
        sa.UniqueConstraint("story_id", "sequence", name="uq_messages_story_sequence"),
    )
    # A partial index: unique only among rows that have a hash.
    op.create_index(
        "uq_messages_story_request_hash",
        "messages",
        ["story_id", "request_hash"],
        unique=True,
        postgresql_where=sa.text("request_hash IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("stories")
    op.drop_table("personas")
    op.drop_table("characters")
