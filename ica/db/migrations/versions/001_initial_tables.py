"""Initial tables.

Revision ID: 001
Revises:
Create Date: 2026-02-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # articles
    op.create_table(
        "articles",
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("origin", sa.Text(), nullable=True),
        sa.Column("publish_date", sa.Date(), nullable=True),
        sa.Column("approved", sa.Boolean(), nullable=True),
        sa.Column("industry_news", sa.Boolean(), nullable=True),
        sa.Column("newsletter_id", sa.Text(), nullable=True),
        sa.Column(
            "type",
            sa.String(50),
            server_default="curated",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("url"),
    )

    # themes
    op.create_table(
        "themes",
        sa.Column("theme", sa.Text(), nullable=False),
        sa.Column("theme_body", sa.Text(), nullable=True),
        sa.Column("theme_summary", sa.Text(), nullable=True),
        sa.Column("newsletter_id", sa.Text(), nullable=True),
        sa.Column("approved", sa.Boolean(), nullable=True),
        sa.Column(
            "type",
            sa.String(50),
            server_default="newsletter",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("theme"),
    )

    # notes (consolidated feedback / learning data)
    op.create_table(
        "notes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("feedback_text", sa.Text(), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("newsletter_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notes_created_at", "notes", ["created_at"])
    op.create_index(
        "ix_notes_type_created_at",
        "notes",
        ["type", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("notes")
    op.drop_table("themes")
    op.drop_table("articles")
