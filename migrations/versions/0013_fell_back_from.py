"""A reply records the story model that could not take the turn, when the default wrote it.

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("fell_back_from", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "fell_back_from")
