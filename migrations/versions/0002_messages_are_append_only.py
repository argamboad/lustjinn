"""Messages are append-only: the database itself refuses to rewrite or delete a turn.

Written by hand — a trigger is not something the models can describe, so autogenerate never
sees it. Plain SQL through `op.execute`.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Runs before every UPDATE and DELETE of a row in messages. RAISE aborts the statement.
    # The error code is Postgres's own "restrict_violation", so the application sees an
    # integrity error, like any broken constraint.
    op.execute(
        """
        CREATE FUNCTION messages_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                -- The one way through: a purge announces itself for the length of its own
                -- transaction with  SET LOCAL lustjinn.purging = 'on'.
                IF current_setting('lustjinn.purging', true) = 'on' THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION
                    'messages are append-only: a message is hidden with deleted_at, never deleted'
                    USING ERRCODE = 'restrict_violation';
            END IF;

            -- What a turn said, who said it and where it sits never change. Everything else on
            -- the row may: deleted_at (hiding), request_hash, and the columns later steps add.
            IF NEW.text IS DISTINCT FROM OLD.text
               OR NEW.role IS DISTINCT FROM OLD.role
               OR NEW.story_id IS DISTINCT FROM OLD.story_id
               OR NEW.sequence IS DISTINCT FROM OLD.sequence THEN
                RAISE EXCEPTION
                    'messages are append-only: text, role, story and sequence cannot be changed'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER messages_append_only
        BEFORE UPDATE OR DELETE ON messages
        FOR EACH ROW EXECUTE FUNCTION messages_append_only()
        """
    )

    # TRUNCATE empties a table without touching rows one by one, so the trigger above never
    # fires for it. It gets its own.
    op.execute(
        """
        CREATE FUNCTION messages_no_truncate() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'messages are append-only: the table cannot be truncated'
                USING ERRCODE = 'restrict_violation';
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER messages_no_truncate
        BEFORE TRUNCATE ON messages
        FOR EACH STATEMENT EXECUTE FUNCTION messages_no_truncate()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER messages_no_truncate ON messages")
    op.execute("DROP FUNCTION messages_no_truncate()")
    op.execute("DROP TRIGGER messages_append_only ON messages")
    op.execute("DROP FUNCTION messages_append_only()")
