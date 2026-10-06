"""Embeddings of summarised turns, for retrieval — and the pgvector extension that stores them.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DIMENSIONS = 1536  # openai/text-embedding-3-small


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "embeddings",
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("story_id", sa.Uuid(), nullable=False),
        sa.Column("vector", Vector(DIMENSIONS), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # CASCADE: an embedding is derived from its message and has no life of its own. Only a
        # purge deletes messages, and it should not have to remember this table.
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name="fk_embeddings_message_id_messages",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["story_id"],
            ["stories.id"],
            name="fk_embeddings_story_id_stories",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("message_id", name="pk_embeddings"),
    )
    op.create_index("ix_embeddings_story_id", "embeddings", ["story_id"])
    # HNSW: approximate nearest neighbours by cosine distance. Exact search would do for one
    # reader's stories, but the index is what pgvector is for, and it costs nothing to have.
    op.execute(
        "CREATE INDEX ix_embeddings_vector ON embeddings USING hnsw (vector vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_table("embeddings")
    op.execute("DROP EXTENSION IF EXISTS vector")
