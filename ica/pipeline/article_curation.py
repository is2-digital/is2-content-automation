"""Article curation data flow — Step 1 data preparation.

Prepares unapproved articles for human review by:

1. Sending initial Slack notification
2. Clearing the Google Sheet
3. Fetching unapproved articles from PostgreSQL
4. Processing dates and normalizing fields for display
5. Appending formatted articles to Google Sheet

See PRD Section 3.1 (steps 1–5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ica.db.models import CuratedArticle
from ica.utils.date_parser import format_date_mmddyyyy


# ---------------------------------------------------------------------------
# Protocol dependencies (concrete implementations provided by caller)
# ---------------------------------------------------------------------------


class SlackNotifier(Protocol):
    """Sends plain-text messages to a Slack channel."""

    async def send_message(self, channel: str, text: str) -> None: ...


class SheetWriter(Protocol):
    """Clear and append operations on a Google Sheets spreadsheet."""

    async def clear_sheet(self, spreadsheet_id: str, sheet_name: str) -> None: ...

    async def append_rows(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        rows: list[dict[str, Any]],
    ) -> int: ...


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

SHEET_COLUMNS = (
    "url",
    "title",
    "publish_date",
    "origin",
    "approved",
    "newsletter_id",
    "industry_news",
)
"""Column order for the curated-articles Google Sheet."""


@dataclass(frozen=True)
class SheetArticle:
    """Article data formatted for Google Sheet display.

    All fields are strings suitable for direct insertion into the spreadsheet.
    """

    url: str
    title: str
    publish_date: str  # MM/DD/YYYY
    origin: str
    approved: str  # empty string when not approved
    newsletter_id: str  # empty string when unassigned
    industry_news: str  # empty string when false/None


@dataclass(frozen=True)
class CurationDataResult:
    """Result of the curation data preparation step."""

    articles_fetched: int
    articles_written: int
    sheet_articles: list[SheetArticle]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INITIAL_NOTIFICATION = (
    "Looking into articles now and starting summarization..."
)

#: Default limit matching n8n ``Fetch data`` Postgres node (limit: 30).
DEFAULT_FETCH_LIMIT = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def format_article_for_sheet(article: CuratedArticle) -> SheetArticle:
    """Convert a DB article to sheet-ready format.

    Ports the n8n "Process Input" Code node logic:

    - ``publish_date`` is formatted as ``MM/DD/YYYY`` (empty if missing).
    - ``approved`` is converted to empty string when ``False``/``None``
      so the user sees a blank cell to fill in.
    - ``industry_news`` is converted to ``"yes"`` / ``""`` for display.
    - ``newsletter_id`` defaults to empty string when ``None``.
    """
    publish_date = (
        format_date_mmddyyyy(article.publish_date)
        if article.publish_date
        else ""
    )

    return SheetArticle(
        url=article.url,
        title=article.title or "",
        publish_date=publish_date,
        origin=article.origin or "",
        approved="yes" if article.approved else "",
        newsletter_id=article.newsletter_id or "",
        industry_news="yes" if article.industry_news else "",
    )


def articles_to_row_dicts(articles: list[SheetArticle]) -> list[dict[str, str]]:
    """Convert :class:`SheetArticle` list to dicts for the Google Sheets API."""
    return [
        {
            "url": a.url,
            "title": a.title,
            "publish_date": a.publish_date,
            "origin": a.origin,
            "approved": a.approved,
            "newsletter_id": a.newsletter_id,
            "industry_news": a.industry_news,
        }
        for a in articles
    ]


async def fetch_unapproved_articles(
    session: AsyncSession,
    *,
    limit: int = DEFAULT_FETCH_LIMIT,
) -> list[CuratedArticle]:
    """Fetch articles that have not been approved.

    Matches the n8n query ``WHERE approved != TRUE`` which catches both
    ``false`` and ``NULL`` values.  Results are ordered by
    ``publish_date DESC`` with a default limit of 30.
    """
    stmt = (
        select(CuratedArticle)
        .where(
            or_(
                CuratedArticle.approved == False,  # noqa: E712
                CuratedArticle.approved.is_(None),
            )
        )
        .order_by(CuratedArticle.publish_date.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


async def prepare_curation_data(
    session: AsyncSession,
    slack: SlackNotifier,
    sheets: SheetWriter,
    *,
    spreadsheet_id: str,
    sheet_name: str = "Sheet1",
    channel: str,
) -> CurationDataResult:
    """Prepare unapproved articles for human review in Google Sheets.

    Orchestrates PRD Section 3.1 steps 1–5:

    1. Send Slack notification ("Looking into articles now...")
    2. Clear Google Sheet
    3. Fetch unapproved articles from PostgreSQL
    4. Format articles for sheet display (dates, booleans)
    5. Append formatted rows to Google Sheet

    Args:
        session: Async database session.
        slack: Slack message sender.
        sheets: Google Sheets writer.
        spreadsheet_id: Google Sheets document ID.
        sheet_name: Sheet/tab name within the spreadsheet.
        channel: Slack channel for notifications.

    Returns:
        :class:`CurationDataResult` with fetch/write counts and
        formatted articles.
    """
    # 1. Notify Slack
    await slack.send_message(channel, INITIAL_NOTIFICATION)

    # 2. Clear the sheet
    await sheets.clear_sheet(spreadsheet_id, sheet_name)

    # 3. Fetch unapproved articles
    articles = await fetch_unapproved_articles(session)

    # 4. Format for display
    sheet_articles = [format_article_for_sheet(a) for a in articles]

    # 5. Append to sheet
    rows = articles_to_row_dicts(sheet_articles)
    written = (
        await sheets.append_rows(spreadsheet_id, sheet_name, rows)
        if rows
        else 0
    )

    return CurationDataResult(
        articles_fetched=len(articles),
        articles_written=written,
        sheet_articles=sheet_articles,
    )
