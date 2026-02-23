"""Summarization pipeline — Step 2 of the newsletter pipeline.

Ports the n8n ``summarization_subworkflow.json``:

**Data preparation** (first half):

1. Get LLM model configuration
2. Fetch approved articles from Google Sheet (filter: ``approved=yes``)
3. Normalize field types (``approved`` / ``industry_news`` → boolean)
4. Build and execute SQL UPSERT into ``articles`` table (``type='curated'``)

**Per-article loop** (second half):

6. Loop over each article (splitInBatches, one at a time):
   a. Fetch page content via HTTP GET with browser headers
   b. If fetch fails (error/captcha/YouTube): Slack manual fallback
   c. Convert HTML to text
   d. Fetch learning data from ``notes`` table (last 40, type ``user_summarization``)
   e. Aggregate feedback into bullet-point list
   f. Call LLM with summarization prompt
   g. Parse output into structured :class:`ArticleSummary`
7. Collect all summaries

See PRD Section 3.2.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from html import unescape
from typing import Protocol

import litellm
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ica.config.llm_config import LLMPurpose, get_model
from ica.db.crud import get_recent_notes
from ica.db.models import Article, Note
from ica.prompts.summarization import build_summarization_prompt
from ica.utils.boolean_normalizer import normalize_boolean
from ica.utils.date_parser import parse_date_mmddyyyy


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": "Safari/537.36",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
    "Connection": "keep-alive",
}
"""Browser-like headers for HTTP fetching.

Matches the n8n "Fetch Page Content" httpRequest node configuration.
"""

CAPTCHA_MARKER = "sgcaptcha"
"""String present in captcha challenge pages."""

YOUTUBE_DOMAIN = "youtube.com"
"""YouTube URLs cannot be scraped and require manual fallback."""


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


class HttpFetcher(Protocol):
    """HTTP GET client for fetching article page content.

    Implementations should catch transport errors and return them
    in the ``error`` field of :class:`FetchResult` rather than raising.
    """

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> FetchResult: ...


class SlackManualFallback(Protocol):
    """Slack ``sendAndWait`` for manual article content input.

    Ports the n8n "Manual Article Content" Slack sendAndWait node.
    Blocks until the user submits content via a Slack modal.
    """

    async def send_and_wait_freetext(
        self,
        message: str,
        *,
        button_label: str = "Add Article Content",
        form_title: str = "Please provide article or blog data",
        form_description: str = "",
    ) -> str: ...


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FetchResult:
    """Result of an HTTP page fetch.

    Attributes:
        content: The response body text (HTML), or ``None`` on failure.
        error: ``None`` on success, or an error description string.
    """

    content: str | None
    error: str | None


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
class ArticleSummary:
    """A summarized article ready for downstream pipeline steps.

    Matches the PRD Section 3.2 output format and the n8n "Format output"
    Code node structure.
    """

    url: str
    title: str
    summary: str
    business_relevance: str
    order: int
    newsletter_id: str
    industry_news: bool


@dataclass(frozen=True)
class SummarizationPrepResult:
    """Result of summarization data preparation."""

    articles: list[CuratedArticle]
    rows_upserted: int
    model: str


@dataclass(frozen=True)
class SummarizationLoopResult:
    """Result of the per-article summarization loop.

    Attributes:
        summaries: Ordered list of article summaries.
        model: The LLM model identifier used for summarization.
    """

    summaries: list[ArticleSummary]
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


# ---------------------------------------------------------------------------
# Per-article loop — fetch failure detection
# ---------------------------------------------------------------------------


def is_fetch_failure(
    result: FetchResult,
    url: str,
) -> bool:
    """Determine whether an HTTP fetch should be treated as a failure.

    Ports the n8n "If" condition node which checks three conditions (AND):

    1. Error message exists (HTTP request threw an error)
    2. Response contains captcha marker (``sgcaptcha``)
    3. URL is a YouTube link (cannot be scraped)

    In the n8n workflow, all three conditions being *false* means success.
    Here we invert: any single condition being *true* means failure.

    Args:
        result: The :class:`FetchResult` from the HTTP fetch.
        url: The original article URL.

    Returns:
        ``True`` if the fetch failed and manual fallback is needed.
    """
    if result.error is not None:
        return True
    if result.content is not None and CAPTCHA_MARKER in result.content:
        return True
    if YOUTUBE_DOMAIN in url.lower():
        return True
    return False


# ---------------------------------------------------------------------------
# Per-article loop — Slack manual fallback
# ---------------------------------------------------------------------------


def build_manual_fallback_message(url: str) -> str:
    """Build the Slack message for requesting manual article content.

    Ports the n8n "Manual Article Content" Slack ``sendAndWait`` node
    message template.

    Args:
        url: The article URL that could not be fetched.

    Returns:
        Formatted Slack mrkdwn message string.
    """
    return f"*Please provide article or blog data :*\n\U0001f517 *URL:* {url}"


# ---------------------------------------------------------------------------
# Per-article loop — HTML to text conversion
# ---------------------------------------------------------------------------


def strip_html_tags(html: str) -> str:
    """Convert HTML to plain text by stripping tags.

    Provides a simple alternative to the n8n Markdown node (Turndown).
    Removes ``<script>`` and ``<style>`` elements, strips all tags,
    unescapes HTML entities, and normalizes whitespace.

    Args:
        html: Raw HTML string.

    Returns:
        Plain text content suitable for LLM consumption.
    """
    if not html:
        return ""
    # Remove script and style elements entirely
    text = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Replace block-level tags with newlines for readability
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(p|div|h[1-6]|li|tr)\b[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Unescape HTML entities
    text = unescape(text)
    # Normalize whitespace (collapse runs of spaces, preserve newlines)
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r"\n\s*\n", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Per-article loop — input building and LLM call
# ---------------------------------------------------------------------------


def build_article_input(url: str, title: str, content: str) -> str:
    """Combine URL, title, and page content into LLM input.

    Mirrors the n8n Markdown node output formula::

        {{ url }} {{ title }} {{ content }}

    Args:
        url: The article URL.
        title: The article title.
        content: The page content (text or markdown).

    Returns:
        A single string ready to be passed as ``article_content`` to
        :func:`~ica.prompts.summarization.build_summarization_prompt`.
    """
    return f"{url} {title} {content}"


def aggregate_feedback(notes: list[Note]) -> str | None:
    """Convert Note rows into a bullet-point string for prompt injection.

    Mirrors the n8n "Aggregate Feedback" Code node in the summarization
    subworkflow which formats feedback entries as ``• text`` bullets.

    Args:
        notes: Recent feedback rows from the ``notes`` table.

    Returns:
        A newline-separated bullet list, or ``None`` if no feedback exists.
    """
    if not notes:
        return None
    lines = [f"\u2022 {row.feedback_text}" for row in notes if row.feedback_text]
    return "\n".join(lines) if lines else None


async def call_summary_llm(
    article_input: str,
    aggregated_feedback: str | None = None,
    *,
    model: str | None = None,
) -> str:
    """Call the LLM to summarize a single article.

    Args:
        article_input: Combined URL + title + page content.
        aggregated_feedback: Optional aggregated learning data.
        model: Override model identifier. Defaults to
            ``get_model(LLMPurpose.SUMMARY)``.

    Returns:
        The raw LLM response text.

    Raises:
        RuntimeError: If the LLM returns an empty response.
    """
    model_id = model or get_model(LLMPurpose.SUMMARY)
    system_prompt, user_prompt = build_summarization_prompt(
        article_content=article_input,
        aggregated_feedback=aggregated_feedback,
    )

    response = await litellm.acompletion(
        model=model_id,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    content = response.choices[0].message.content  # type: ignore[union-attr]
    if not content or not content.strip():
        raise RuntimeError("LLM returned an empty response for summarization")

    return content.strip()


# ---------------------------------------------------------------------------
# Per-article loop — output parsing
# ---------------------------------------------------------------------------


def parse_summary_output(raw: str) -> tuple[str, str, str, str]:
    """Parse the LLM summary output into structured fields.

    Ports the regex parsing from the n8n "Format output" Code node::

        URL: ...
        Title: ...
        Summary: ...
        Business Relevance: ...

    Args:
        raw: Raw text response from the summarization LLM.

    Returns:
        A ``(url, title, summary, business_relevance)`` tuple.
        Fields default to placeholder values if not found in the output.
    """
    url_match = re.search(r"URL:\s*(.+)", raw)
    title_match = re.search(r"Title:\s*(.+)", raw)
    summary_match = re.search(r"Summary:\s*([\s\S]*?)Business Relevance:", raw)
    business_match = re.search(r"Business Relevance:\s*([\s\S]*)$", raw)

    url = url_match.group(1).strip() if url_match else "N/A"
    title = title_match.group(1).strip() if title_match else "Untitled"
    summary = summary_match.group(1).strip() if summary_match else "No summary available."
    business = (
        business_match.group(1).strip()
        if business_match
        else "No business relevance available."
    )

    return url, title, summary, business


# ---------------------------------------------------------------------------
# Per-article loop — single article summarization
# ---------------------------------------------------------------------------


async def summarize_single_article(
    article: CuratedArticle,
    order: int,
    *,
    http: HttpFetcher,
    slack: SlackManualFallback | None = None,
    aggregated_feedback: str | None = None,
    model: str | None = None,
) -> ArticleSummary:
    """Fetch, convert, and summarize a single article.

    Ports one iteration of the n8n ``splitInBatches`` loop:

    1. Fetch page content via HTTP GET with browser headers.
    2. If fetch fails (error/captcha/YouTube): use Slack manual fallback.
    3. Convert HTML to text (or use manual content directly).
    4. Call LLM with summarization prompt.
    5. Parse output into :class:`ArticleSummary`.

    Args:
        article: The article to summarize.
        order: 1-based position in the article list.
        http: HTTP client for page fetching.
        slack: Optional Slack fallback for manual content input.
            When ``None`` and fetch fails, raises :class:`RuntimeError`.
        aggregated_feedback: Pre-aggregated learning data string.
        model: LLM model override.

    Returns:
        A structured :class:`ArticleSummary`.

    Raises:
        RuntimeError: If fetch fails and no Slack fallback is available,
            or if the LLM returns an empty response.
    """
    # Step 1: Fetch page content
    result = await http.get(article.url, headers=BROWSER_HEADERS)

    # Step 2: Check for failure and fallback
    if is_fetch_failure(result, article.url):
        if slack is None:
            raise RuntimeError(
                f"HTTP fetch failed for {article.url} and no Slack fallback available"
            )
        message = build_manual_fallback_message(article.url)
        # Manual content from Slack is already text, no HTML conversion needed
        text_content = await slack.send_and_wait_freetext(
            message,
            form_description=article.url,
        )
    else:
        # Step 3: Convert HTML to text
        text_content = strip_html_tags(result.content or "")

    # Step 4: Build input and call LLM
    article_input = build_article_input(article.url, article.title, text_content)
    raw_output = await call_summary_llm(
        article_input,
        aggregated_feedback=aggregated_feedback,
        model=model,
    )

    # Step 5: Parse LLM output
    parsed_url, parsed_title, summary, business = parse_summary_output(raw_output)

    return ArticleSummary(
        url=parsed_url,
        title=parsed_title,
        summary=summary,
        business_relevance=business,
        order=order,
        newsletter_id=article.newsletter_id,
        industry_news=article.industry_news,
    )


# ---------------------------------------------------------------------------
# Per-article loop — main orchestration
# ---------------------------------------------------------------------------


async def summarize_articles(
    articles: list[CuratedArticle],
    *,
    http: HttpFetcher,
    session: AsyncSession | None = None,
    slack: SlackManualFallback | None = None,
    model: str | None = None,
) -> SummarizationLoopResult:
    """Run the per-article summarization loop (PRD Section 3.2 steps 6–7).

    Processes each article sequentially (matching n8n ``splitInBatches``
    with batch size 1):

    1. Fetch learning data from ``notes`` table (last 40, type
       ``user_summarization``).
    2. Aggregate feedback into a prompt-injectable string.
    3. For each article: fetch page → detect failure → fallback or convert
       → call LLM → parse output.
    4. Collect all summaries.

    Args:
        articles: Approved articles from :func:`prepare_summarization_data`.
        http: HTTP client for page fetching.
        session: Optional async database session for learning data.
            When ``None``, no feedback is injected.
        slack: Optional Slack fallback for manual content input.
        model: LLM model override.

    Returns:
        :class:`SummarizationLoopResult` with all article summaries
        and the model used.
    """
    model_id = model or get_model(LLMPurpose.SUMMARY)

    # Fetch and aggregate learning data
    aggregated = None
    if session is not None:
        notes = await get_recent_notes(session, "user_summarization")
        aggregated = aggregate_feedback(notes)

    # Loop over each article (one at a time, like n8n splitInBatches)
    summaries: list[ArticleSummary] = []
    for idx, article in enumerate(articles, start=1):
        summary = await summarize_single_article(
            article,
            order=idx,
            http=http,
            slack=slack,
            aggregated_feedback=aggregated,
            model=model_id,
        )
        summaries.append(summary)

    return SummarizationLoopResult(
        summaries=summaries,
        model=model_id,
    )
