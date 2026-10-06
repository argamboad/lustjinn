"""A story's model carries the window it was checked against, so its budget can be fitted
without reading the list again.

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("stories", sa.Column("model_context", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("stories", "model_context")
