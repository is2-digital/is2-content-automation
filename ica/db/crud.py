"""CRUD operations for all 7 database tables.

All functions take an :class:`~sqlalchemy.ext.asyncio.AsyncSession` as the
first argument and do NOT commit — the caller manages the transaction.
"""

from __future__ import annotations

from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ica.db.models import (
    Base,
    CuratedArticle,
    FeedbackMixin,
    NewsletterTheme,
)
from ica.pipeline.article_collection import ArticleRecord

# Generic type for feedback model classes
F = TypeVar("F", bound=FeedbackMixin)


# ---------------------------------------------------------------------------
# curated_articles
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

    stmt = pg_insert(CuratedArticle).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["url"],
        set_={
            "title": stmt.excluded.title,
            "origin": stmt.excluded.origin,
            "publish_date": stmt.excluded.publish_date,
        },
    )

    result = await session.execute(stmt)
    return result.rowcount  # type: ignore[return-value]


async def get_articles(
    session: AsyncSession,
    *,
    approved: bool | None = None,
    newsletter_id: str | None = None,
) -> list[CuratedArticle]:
    """Retrieve curated articles with optional filters.

    Args:
        approved: Filter by approval status when not ``None``.
        newsletter_id: Filter by newsletter association when not ``None``.
    """
    stmt = select(CuratedArticle)
    if approved is not None:
        stmt = stmt.where(CuratedArticle.approved == approved)
    if newsletter_id is not None:
        stmt = stmt.where(CuratedArticle.newsletter_id == newsletter_id)
    stmt = stmt.order_by(CuratedArticle.created_at.desc())

    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Feedback tables (generic)
# ---------------------------------------------------------------------------


async def add_feedback(
    session: AsyncSession,
    model: type[F],
    text: str,
    *,
    newsletter_id: str | None = None,
) -> F:
    """Insert a feedback row into any feedback table.

    Args:
        model: The feedback ORM class (e.g. ``SummarizationUserFeedback``).
        text: The feedback content.
        newsletter_id: Set only for models that have this column
            (``NewsletterThemesUserFeedback``, ``NewsletterEmailSubjectFeedback``).
    """
    kwargs: dict[str, object] = {"feedback_text": text}
    if newsletter_id is not None and hasattr(model, "newsletter_id"):
        kwargs["newsletter_id"] = newsletter_id
    row = model(**kwargs)  # type: ignore[call-arg]
    session.add(row)
    await session.flush()
    return row  # type: ignore[return-value]


async def get_recent_feedback(
    session: AsyncSession,
    model: type[F],
    limit: int = 40,
) -> list[F]:
    """Return the most recent *limit* feedback rows, newest first.

    The default of 40 matches the "last 40 entries" pattern used by every
    feedback-injection prompt in the pipeline (PRD Sections 3–6).
    """
    stmt = (
        select(model)  # type: ignore[arg-type]
        .order_by(model.created_at.desc())  # type: ignore[attr-defined]
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# newsletter_themes
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
    """Insert or update a newsletter theme.

    On conflict (duplicate ``theme``) all provided non-PK columns are updated.
    """
    values = {
        "theme": theme,
        "theme_body": theme_body,
        "theme_summary": theme_summary,
        "newsletter_id": newsletter_id,
        "approved": approved,
    }

    stmt = pg_insert(NewsletterTheme).values(values)
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
) -> list[NewsletterTheme]:
    """Retrieve newsletter themes with optional filters."""
    stmt = select(NewsletterTheme)
    if newsletter_id is not None:
        stmt = stmt.where(NewsletterTheme.newsletter_id == newsletter_id)
    if approved is not None:
        stmt = stmt.where(NewsletterTheme.approved == approved)
    stmt = stmt.order_by(NewsletterTheme.created_at.desc())

    result = await session.execute(stmt)
    return list(result.scalars().all())
