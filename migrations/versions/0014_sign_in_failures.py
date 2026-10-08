"""Failed sign-ins, counted to throttle guessing.

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sign_in_failures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sign_in_failures")),
    )
    op.create_index(op.f("ix_sign_in_failures_at"), "sign_in_failures", ["at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sign_in_failures_at"), table_name="sign_in_failures")
    op.drop_table("sign_in_failures")
