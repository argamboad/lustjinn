"""Every story plays on the default model: a story's own model, the window it was checked
against and the record of the default stepping in all go (#140).

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("messages", "fell_back_from")
    op.drop_column("stories", "model_context")
    op.drop_column("stories", "model")


def downgrade() -> None:
    op.add_column("stories", sa.Column("model", sa.String(length=200), nullable=True))
    op.add_column("stories", sa.Column("model_context", sa.Integer(), nullable=True))
    op.add_column("messages", sa.Column("fell_back_from", sa.String(length=200), nullable=True))
