"""The library grows: snippets, and the settings row that names the default persona.

Characters and personas already have the columns the library needs (step 2 made them so).

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "snippets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_snippets"),
    )
    op.create_index(
        "uq_snippets_name_lower", "snippets", [sa.literal_column("lower(name)")], unique=True
    )

    # One row (id = 1), created when something is first set. The default persona is cleared,
    # not kept dangling, if that persona is deleted — the code refuses the delete while a
    # story still needs it.
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("default_persona_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_settings_one_row"),
        sa.ForeignKeyConstraint(
            ["default_persona_id"],
            ["personas.id"],
            name="fk_settings_default_persona_id_personas",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_settings"),
    )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_index("uq_snippets_name_lower", table_name="snippets")
    op.drop_table("snippets")
