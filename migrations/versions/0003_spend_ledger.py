"""The spend ledger: one row per billed call, never changed, never deleted.

The table came from `alembic revision --autogenerate` and was tidied; the trigger is written by
hand, like the one on messages. No foreign key to stories or messages: the ledger survives a
story being erased for good.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "spend",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("story_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("provider", sa.String(length=200), nullable=True),
        sa.Column("generation_id", sa.String(length=200), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=True),
        # Exact, like money. Null means the API did not say what it charged.
        sa.Column("cost", sa.Numeric(precision=18, scale=10), nullable=True),
        sa.CheckConstraint("kind IN ('reply', 'aside', 'summary', 'facts')", name="ck_spend_kind"),
        sa.PrimaryKeyConstraint("id", name="pk_spend"),
    )
    op.create_index("ix_spend_story_id", "spend", ["story_id"])

    # A ledger: rows go in and stay as they are. No purge flag opens this one — erasing a story
    # keeps what it cost.
    op.execute(
        """
        CREATE FUNCTION spend_insert_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'spend is a ledger: a row is never changed or deleted'
                USING ERRCODE = 'restrict_violation';
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER spend_insert_only
        BEFORE UPDATE OR DELETE ON spend
        FOR EACH ROW EXECUTE FUNCTION spend_insert_only()
        """
    )
    op.execute(
        """
        CREATE TRIGGER spend_no_truncate
        BEFORE TRUNCATE ON spend
        FOR EACH STATEMENT EXECUTE FUNCTION spend_insert_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER spend_no_truncate ON spend")
    op.execute("DROP TRIGGER spend_insert_only ON spend")
    op.execute("DROP FUNCTION spend_insert_only()")
    op.drop_index("ix_spend_story_id", table_name="spend")
    op.drop_table("spend")
