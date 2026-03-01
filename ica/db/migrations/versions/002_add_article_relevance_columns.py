"""Add excerpt, relevance_status, relevance_reason to articles.

Revision ID: 002
Revises: 001
Create Date: 2026-02-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: str = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("excerpt", sa.Text(), nullable=True))
    op.add_column(
        "articles", sa.Column("relevance_status", sa.String(20), nullable=True)
    )
    op.add_column(
        "articles", sa.Column("relevance_reason", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("articles", "relevance_reason")
    op.drop_column("articles", "relevance_status")
    op.drop_column("articles", "excerpt")
