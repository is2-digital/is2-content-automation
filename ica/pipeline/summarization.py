"""Summarization pipeline — Step 2 data preparation.

Ports the first half of the n8n ``summarization_subworkflow.json``:

1. Get LLM model configuration
2. Fetch approved articles from Google Sheet (filter: ``approved=yes``)
3. Normalize field types (``approved`` / ``industry_news`` → boolean)
4. Build and execute SQL UPSERT into ``articles`` table (``type='curated'``)
5. Tables exist via Alembic migrations (no runtime CREATE needed)

See PRD Section 3.2.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ica.config.llm_config import LLMPurpose, get_model
from ica.db.models import Article
from ica.utils.boolean_normalizer import normalize_boolean
from ica.utils.date_parser import parse_date_mmddyyyy


# ---------------------------------------------------------------------------
# Protocol dependencies
# ---------------------------------------------------------------------------


class SheetReader(Protocol):
    """Read operations on a Google Sheets spreadsheet."""

    async def read_rows(
        self,
        spreadsheet_id: str,
        sheet_name: str,
    ) -> list[dict[str, str]]: ...


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CuratedArticle:
    """An article normalized from Google Sheet data, ready for DB upsert.

    Fields match the n8n "Field Mapping" Set node output with boolean
    normalization applied to ``approved`` and ``industry_news``.
    """

    url: str
    title: str
    publish_date: date | None
    origin: str
    approved: bool
    newsletter_id: str
    industry_news: bool


@dataclass(frozen=True)
class SummarizationPrepResult:
    """Result of summarization data preparation."""

    articles: list[CuratedArticle]
    rows_upserted: int
    model: str


# ---------------------------------------------------------------------------
# Helpers — filtering and normalization
# ---------------------------------------------------------------------------


def filter_approved_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Filter sheet rows to only those with ``approved='yes'``.

    Ports the n8n Google Sheets "Fetch Data from Sheet" node filter:
    ``approved = "yes"``.

    Args:
        rows: Raw rows from Google Sheets (all string values).

    Returns:
        Only rows where the ``approved`` field normalizes to ``True``.
    """
    return [
        row for row in rows
        if normalize_boolean(row.get("approved", ""))
    ]


def normalize_article_row(row: dict[str, str]) -> CuratedArticle:
    """Convert a Google Sheet row to a typed :class:`CuratedArticle`.

    Ports the n8n "Field Mapping" Set node which normalizes:

    - ``approved``: string ``"yes"`` → ``True``, everything else → ``False``
    - ``industry_news``: string ``"yes"`` → ``True``, everything else → ``False``
    - ``publish_date``: ``MM/DD/YYYY`` string → :class:`~datetime.date` or ``None``

    Args:
        row: A single row from Google Sheets (all string values).

    Returns:
        A :class:`CuratedArticle` with properly typed fields.
    """
    return CuratedArticle(
        url=row.get("url", ""),
        title=row.get("title", ""),
        publish_date=parse_date_mmddyyyy(row.get("publish_date", "")),
        origin=row.get("origin", ""),
        approved=normalize_boolean(row.get("approved", "")),
        newsletter_id=row.get("newsletter_id", ""),
        industry_news=normalize_boolean(row.get("industry_news", "")),
    )


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------


async def upsert_curated_articles(
    session: AsyncSession,
    articles: list[CuratedArticle],
) -> int:
    """Upsert curated articles into the ``articles`` table with ``type='curated'``.

    Ports the n8n "Structure SQL Insert Query" Code node which builds:

    .. code-block:: sql

        INSERT INTO articles (url, title, origin, publish_date, approved,
                              newsletter_id, industry_news, type)
        VALUES (...)
        ON CONFLICT (url)
        DO UPDATE SET title=EXCLUDED.title, ...

    Args:
        session: Async database session (caller manages transaction).
        articles: Normalized articles from Google Sheet.

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
            "approved": a.approved,
            "newsletter_id": a.newsletter_id,
            "industry_news": a.industry_news,
            "type": "curated",
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
            "approved": stmt.excluded.approved,
            "newsletter_id": stmt.excluded.newsletter_id,
            "industry_news": stmt.excluded.industry_news,
            "type": stmt.excluded.type,
        },
    )

    result = await session.execute(stmt)
    return result.rowcount  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


async def prepare_summarization_data(
    session: AsyncSession,
    sheets: SheetReader,
    *,
    spreadsheet_id: str,
    sheet_name: str = "Sheet1",
) -> SummarizationPrepResult:
    """Orchestrate summarization data preparation (PRD Section 3.2 steps 1–5).

    1. Get LLM model configuration for the summary step.
    2. Fetch all rows from Google Sheet.
    3. Filter to approved articles and normalize field types.
    4. Upsert into ``articles`` table with ``type='curated'``.

    Args:
        session: Async database session.
        sheets: Google Sheets reader.
        spreadsheet_id: Google Sheets document ID.
        sheet_name: Sheet/tab name within the spreadsheet.

    Returns:
        :class:`SummarizationPrepResult` with normalized articles,
        upsert count, and LLM model name.
    """
    # 1. Get LLM model config
    model = get_model(LLMPurpose.SUMMARY)

    # 2. Fetch all rows from sheet
    all_rows = await sheets.read_rows(spreadsheet_id, sheet_name)

    # 3. Filter approved rows and normalize fields
    approved_rows = filter_approved_rows(all_rows)
    articles = [normalize_article_row(row) for row in approved_rows]

    # 4. Upsert to DB
    rows_upserted = await upsert_curated_articles(session, articles)

    return SummarizationPrepResult(
        articles=articles,
        rows_upserted=rows_upserted,
        model=model,
    )
