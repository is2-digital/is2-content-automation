"""CRUD operations for all database tables.

All functions take an :class:`~sqlalchemy.ext.asyncio.AsyncSession` as the
first argument and do NOT commit — the caller manages the transaction.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ica.db.models import (
    Article,
    Note,
    Theme,
)
from ica.pipeline.article_collection import ArticleRecord

# ---------------------------------------------------------------------------
# articles
# ---------------------------------------------------------------------------


async def upsert_articles(
    session: AsyncSession,
    articles: list[ArticleRecord],
) -> int:
    """Insert or update articles using PostgreSQL ON CONFLICT DO UPDATE.

    On conflict (duplicate ``url``) the ``title``, ``origin``, and
    ``publish_date`` columns are updated to match the incoming data.

    Returns:
        Number of rows affected (inserted + updated).
    """
    if not articles:
        return 0

    values = [
        {
            "url": a.url,
            "title": a.title,
            "origin": a.origin,
            "publish_date": a.publish_date,
        }
        for a in articles
    ]

    stmt = pg_insert(Article).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["url"],
        set_={
            "title": stmt.excluded.title,
            "origin": stmt.excluded.origin,
            "publish_date": stmt.excluded.publish_date,
        },
    )

    result = await session.execute(stmt)
    return result.rowcount  # type: ignore[no-any-return, attr-defined]


async def get_articles(
    session: AsyncSession,
    *,
    approved: bool | None = None,
    newsletter_id: str | None = None,
) -> list[Article]:
    """Retrieve articles with optional filters.

    Args:
        approved: Filter by approval status when not ``None``.
        newsletter_id: Filter by newsletter association when not ``None``.
    """
    stmt = select(Article)
    if approved is not None:
        stmt = stmt.where(Article.approved == approved)
    if newsletter_id is not None:
        stmt = stmt.where(Article.newsletter_id == newsletter_id)
    stmt = stmt.order_by(Article.created_at.desc())

    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# notes (consolidated feedback / learning data)
# ---------------------------------------------------------------------------


async def add_note(
    session: AsyncSession,
    note_type: str,
    text: str,
    *,
    newsletter_id: str | None = None,
) -> Note:
    """Insert a row into the ``notes`` table.

    Args:
        note_type: Discriminator value (e.g. ``"user_newsletter_themes"``).
        text: The feedback / learning-data content.
        newsletter_id: Optional newsletter association.
    """
    row = Note(feedback_text=text, type=note_type, newsletter_id=newsletter_id)
    session.add(row)
    await session.flush()
    return row


async def get_recent_notes(
    session: AsyncSession,
    note_type: str,
    limit: int = 40,
) -> list[Note]:
    """Return the most recent *limit* notes of a given type, newest first.

    The default of 40 matches the "last 40 entries" pattern used by every
    feedback-injection prompt in the pipeline (PRD Sections 3–6).
    """
    stmt = select(Note).where(Note.type == note_type).order_by(Note.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# themes
# ---------------------------------------------------------------------------


async def upsert_theme(
    session: AsyncSession,
    *,
    theme: str,
    theme_body: str | None = None,
    theme_summary: str | None = None,
    newsletter_id: str | None = None,
    approved: bool | None = None,
) -> None:
    """Insert or update a theme.

    On conflict (duplicate ``theme``) all provided non-PK columns are updated.
    """
    values = {
        "theme": theme,
        "theme_body": theme_body,
        "theme_summary": theme_summary,
        "newsletter_id": newsletter_id,
        "approved": approved,
    }

    stmt = pg_insert(Theme).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["theme"],
        set_={
            "theme_body": stmt.excluded.theme_body,
            "theme_summary": stmt.excluded.theme_summary,
            "newsletter_id": stmt.excluded.newsletter_id,
            "approved": stmt.excluded.approved,
        },
    )
    await session.execute(stmt)


async def get_themes(
    session: AsyncSession,
    *,
    newsletter_id: str | None = None,
    approved: bool | None = None,
) -> list[Theme]:
    """Retrieve themes with optional filters."""
    stmt = select(Theme)
    if newsletter_id is not None:
        stmt = stmt.where(Theme.newsletter_id == newsletter_id)
    if approved is not None:
        stmt = stmt.where(Theme.approved == approved)
    stmt = stmt.order_by(Theme.created_at.desc())

    result = await session.execute(stmt)
    return list(result.scalars().all())
