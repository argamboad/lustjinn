"""Library history: every saved version of every entry, insert-only.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "library_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        # No foreign key: the history of a deleted entry is still history.
        sa.Column("entry_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("opening", sa.Text(), nullable=True),
        sa.Column(
            "saved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('character', 'persona', 'snippet')", name="ck_library_history_kind"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_library_history"),
    )
    op.create_index("ix_library_history_entry", "library_history", ["entry_id", "version"])

    # Like the ledger: rows go in and stay as they are.
    op.execute(
        """
        CREATE FUNCTION library_history_insert_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'library_history keeps every version: a row is never changed or deleted'
                USING ERRCODE = 'restrict_violation';
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER library_history_insert_only
        BEFORE UPDATE OR DELETE ON library_history
        FOR EACH ROW EXECUTE FUNCTION library_history_insert_only()
        """
    )
    op.execute(
        """
        CREATE TRIGGER library_history_no_truncate
        BEFORE TRUNCATE ON library_history
        FOR EACH STATEMENT EXECUTE FUNCTION library_history_insert_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER library_history_no_truncate ON library_history")
    op.execute("DROP TRIGGER library_history_insert_only ON library_history")
    op.execute("DROP FUNCTION library_history_insert_only()")
    op.drop_index("ix_library_history_entry", table_name="library_history")
    op.drop_table("library_history")
