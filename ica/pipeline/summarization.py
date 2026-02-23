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

**Output and feedback** (third part):

8. Format summaries as Slack Block Kit + mrkdwn text
9. Share in Slack channel
10. Send next-steps form (Yes / Provide Feedback / Restart Chat)
11. Feedback loop: collect feedback → regenerate → extract learning data →
    store in ``notes`` table → re-share → ask again

See PRD Section 3.2.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import litellm
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ica.config.llm_config import LLMPurpose, get_model
from ica.db.crud import add_note, get_recent_notes
from ica.db.models import Article, Note
from ica.prompts.learning_data_extraction import build_learning_data_extraction_prompt
from ica.prompts.summarization import (
    build_summarization_prompt,
    build_summarization_regeneration_prompt,
)
from ica.services.web_fetcher import (
    BROWSER_HEADERS,
    CAPTCHA_MARKER,
    YOUTUBE_DOMAIN,
    FetchResult,
    is_fetch_failure,
    strip_html_tags,
)
from ica.utils.boolean_normalizer import normalize_boolean
from ica.utils.date_parser import parse_date_mmddyyyy
from ica.utils.output_router import (
    UserChoice,
    conditional_output_router,
    normalize_switch_value,
)


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


# ---------------------------------------------------------------------------
# Protocols — output and feedback
# ---------------------------------------------------------------------------


class SlackSummaryReview(Protocol):
    """Slack interactions for the summarization review loop.

    Ports three n8n Slack nodes:

    - "Share summarized content" → :meth:`send_channel_message`
    - "Next steps selection" → :meth:`send_and_wait_form`
    - "Feedback form" → :meth:`send_and_wait_freetext`
    """

    async def send_channel_message(
        self,
        text: str,
        *,
        blocks: list[dict[str, object]] | None = None,
    ) -> None:
        """Send a message to the Slack channel (``chat.postMessage``)."""
        ...

    async def send_and_wait_form(
        self,
        message: str,
        *,
        form_fields: list[dict[str, object]],
        button_label: str = "Proceed to Next Steps",
        form_title: str = "Proceed to next step",
        form_description: str = "",
    ) -> dict[str, str]:
        """Send a form and wait for user response.

        Returns a dict mapping field labels to selected values.
        """
        ...

    async def send_and_wait_freetext(
        self,
        message: str,
        *,
        button_label: str = "Add feedback",
        form_title: str = "Feedback Form",
        form_description: str = "",
    ) -> str:
        """Send a free-text form and wait for user response."""
        ...


# ---------------------------------------------------------------------------
# Data types — output
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SummarizationOutput:
    """Final output of the summarization pipeline step.

    Contains the article data ready for Step 3 (theme generation)
    and the formatted text used for Slack display.

    Attributes:
        articles: List of article dicts in PRD Section 5.2 output format.
        text: The Slack mrkdwn text (original or regenerated).
        model: The LLM model identifier used for summarization.
    """

    articles: list[dict[str, object]]
    text: str
    model: str


# ---------------------------------------------------------------------------
# Constants — Slack form config
# ---------------------------------------------------------------------------

SUMMARY_HEADER = "Article Summaries for Review"
"""Expected header in formatted summary text; used for content validation."""

NEXT_STEPS_FIELD_LABEL = "Ready to proceed to next step ?"
NEXT_STEPS_OPTIONS: list[str] = ["Yes", "Provide Feedback", "Restart Chat"]
NEXT_STEPS_BUTTON_LABEL = "Proceed to Next Steps"
NEXT_STEPS_FORM_TITLE = "Proceed to next step"
NEXT_STEPS_FORM_DESCRIPTION = (
    "All articles have been successfully summarized."
)
NEXT_STEPS_MESSAGE = "*All articles have been successfully summarized.*"

FEEDBACK_MESSAGE = (
    "*Please provide feedback to improve summarized content*"
)
FEEDBACK_BUTTON_LABEL = "Add feedback"
FEEDBACK_FORM_TITLE = "Feedback Form"
FEEDBACK_FORM_DESCRIPTION = (
    "Please provide feedback to improve summarized content"
)

SUMMARY_DIVIDER = "\u2500" * 30
"""Visual divider line used between article summaries."""


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def format_summary_slack_text(summaries: list[ArticleSummary]) -> str:
    """Build Slack mrkdwn text displaying all article summaries.

    Ports the n8n "Format output" Code node ``combinedText`` construction.
    Produces a flat mrkdwn string with a header, article count, and each
    article's title, URL, summary, and business relevance separated by
    divider lines.

    Args:
        summaries: Ordered list of article summaries.

    Returns:
        Slack mrkdwn text ready for ``chat.postMessage``.
    """
    parts: list[str] = [
        f"*{SUMMARY_HEADER}*\n\n_Total Articles:_ {len(summaries)}\n",
    ]

    for summary in summaries:
        parts.append(
            f"*{summary.order}. {summary.title}*\n"
            f"*URL:* {summary.url}\n\n"
            f"*Summary:*\n{summary.summary}\n\n"
            f"*Business Relevance:*\n{summary.business_relevance}\n"
            f"{SUMMARY_DIVIDER}\n"
        )

    return "\n".join(parts)


def build_summary_slack_blocks(
    summaries: list[ArticleSummary],
) -> list[dict[str, object]]:
    """Build Slack Block Kit blocks for article summaries.

    Ports the n8n "Format output" Code node ``blocks`` array
    construction.  Creates a header section, divider, and one section
    per article with a divider between each.

    Args:
        summaries: Ordered list of article summaries.

    Returns:
        List of Slack Block Kit block dicts.
    """
    blocks: list[dict[str, object]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{SUMMARY_HEADER}*\n\n"
                    f"_Total Articles:_ {len(summaries)}"
                ),
            },
        },
        {"type": "divider"},
    ]

    for summary in summaries:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{summary.order}. {summary.title}*\n"
                    f"*URL:* {summary.url}\n\n"
                    f"*Summary:*\n{summary.summary}\n\n"
                    f"*Business Relevance:*\n{summary.business_relevance}"
                ),
            },
        })
        blocks.append({"type": "divider"})

    return blocks


# ---------------------------------------------------------------------------
# Form builders
# ---------------------------------------------------------------------------


def build_next_steps_form() -> list[dict[str, object]]:
    """Build the Slack sendAndWait form for next-steps selection.

    Ports the n8n "Next steps selection" sendAndWait node form
    definition.  Presents a required dropdown with options: Yes /
    Provide Feedback / Restart Chat.

    Returns:
        JSON-serialisable form field list for Slack sendAndWait.
    """
    return [
        {
            "fieldLabel": NEXT_STEPS_FIELD_LABEL,
            "fieldType": "dropdown",
            "fieldOptions": {
                "values": [{"option": opt} for opt in NEXT_STEPS_OPTIONS],
            },
            "requiredField": True,
        },
    ]


def parse_next_steps_response(response: dict[str, str]) -> UserChoice | None:
    """Parse the user's selection from the next-steps form response.

    Extracts the dropdown value from the form response dict and
    normalizes it to a :class:`~ica.utils.output_router.UserChoice`.

    Args:
        response: The raw Slack form response dict mapping field labels
            to selected values.

    Returns:
        The user's choice, or ``None`` if the value is unrecognized.
    """
    value = response.get(NEXT_STEPS_FIELD_LABEL, "")
    return normalize_switch_value(value)


def summaries_to_output_articles(
    summaries: list[ArticleSummary],
) -> list[dict[str, object]]:
    """Convert :class:`ArticleSummary` list to the PRD Section 5.2 format.

    Produces the JSON-compatible dict structure expected by Step 3
    (theme generation)::

        {
            "URL": "...",
            "Title": "...",
            "Summary": "3-4 sentences",
            "BusinessRelevance": "2-3 sentences",
            "order": 1,
            "newsletter_id": "...",
            "industry_news": true
        }

    Args:
        summaries: Ordered list of article summaries.

    Returns:
        List of article dicts in the PRD output format.
    """
    return [
        {
            "URL": s.url,
            "Title": s.title,
            "Summary": s.summary,
            "BusinessRelevance": s.business_relevance,
            "order": s.order,
            "newsletter_id": s.newsletter_id,
            "industry_news": s.industry_news,
        }
        for s in summaries
    ]


# ---------------------------------------------------------------------------
# LLM calls — regeneration and learning data extraction
# ---------------------------------------------------------------------------


async def call_regeneration_llm(
    original_text: str,
    user_feedback: str,
    *,
    model: str | None = None,
) -> str:
    """Call the LLM to regenerate summaries based on user feedback.

    Ports the n8n "Re-Generate Data using LLM" node in the
    summarization subworkflow.

    Args:
        original_text: The original formatted summary text.
        user_feedback: The user's free-text feedback from Slack.
        model: Override model identifier.  Defaults to
            ``get_model(LLMPurpose.SUMMARY_REGENERATION)``.

    Returns:
        The regenerated summary text.

    Raises:
        RuntimeError: If the LLM returns an empty response.
    """
    model_id = model or get_model(LLMPurpose.SUMMARY_REGENERATION)
    system_prompt, user_prompt = build_summarization_regeneration_prompt(
        original_content=original_text,
        user_feedback=user_feedback,
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
        raise RuntimeError(
            "LLM returned an empty response for summarization regeneration"
        )

    return content.strip()


async def extract_summary_learning_data(
    feedback: str,
    input_text: str,
    model_output: str,
    *,
    model: str | None = None,
) -> str:
    """Call the LLM to extract learning data from user feedback.

    Ports the n8n "Learning data extractor" node in the summarization
    subworkflow.  Converts raw user feedback into a concise, structured
    summary that is stored in the ``notes`` table for future prompt
    injection.

    Args:
        feedback: The user's free-text feedback from the Slack form.
        input_text: The original formatted summary text.
        model_output: The regenerated summary text.
        model: Override model identifier.  Defaults to
            ``get_model(LLMPurpose.SUMMARY_LEARNING_DATA)``.

    Returns:
        Extracted ``learning_feedback`` text.  If the LLM returns valid
        JSON with a ``learning_feedback`` key, that value is extracted;
        otherwise the raw response is returned.

    Raises:
        RuntimeError: If the LLM returns an empty response.
    """
    model_id = model or get_model(LLMPurpose.SUMMARY_LEARNING_DATA)
    system_prompt, user_prompt = build_learning_data_extraction_prompt(
        feedback=feedback,
        input_text=input_text,
        model_output=model_output,
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
        raise RuntimeError(
            "LLM returned an empty response for learning data extraction"
        )

    text = content.strip()

    # Try to parse JSON and extract the learning_feedback field.
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "learning_feedback" in data:
            return str(data["learning_feedback"])
    except (json.JSONDecodeError, TypeError):
        pass

    return text


# ---------------------------------------------------------------------------
# Database operations — feedback storage
# ---------------------------------------------------------------------------


async def store_summarization_feedback(
    session: AsyncSession,
    feedback_text: str,
    *,
    newsletter_id: str | None = None,
) -> None:
    """Store processed learning feedback in the ``notes`` table.

    Ports the n8n "Insert user feedback" Postgres node in the
    summarization subworkflow.  Inserts with ``type='user_summarization'``.

    Args:
        session: Active async database session.
        feedback_text: The processed learning note from
            :func:`extract_summary_learning_data`.
        newsletter_id: Optional newsletter association.
    """
    await add_note(
        session,
        "user_summarization",
        feedback_text,
        newsletter_id=newsletter_id,
    )


# ---------------------------------------------------------------------------
# Main orchestration — output sharing and feedback loop
# ---------------------------------------------------------------------------


async def run_summarization_output(
    summaries: list[ArticleSummary],
    *,
    slack: SlackSummaryReview,
    session: AsyncSession | None = None,
    newsletter_id: str | None = None,
) -> SummarizationOutput:
    """Run the summarization output sharing and feedback loop.

    Orchestrates PRD Section 3.2 steps 7-10 and the feedback loop:

    1. Format all summaries as Slack mrkdwn + Block Kit.
    2. Share in Slack channel.
    3. Send next-steps form (Yes / Provide Feedback / Restart Chat).
    4. **Yes** → return final output with article data.
    5. **Provide Feedback** → collect feedback → regenerate via LLM →
       extract learning data → store in ``notes`` → re-share (loop).
    6. **Restart Chat** → reset to original text → re-share (loop).

    Mirrors the n8n loop: "Share summarized content" → "Next steps
    selection" → "Switch" → feedback path / restart path / final output.

    Args:
        summaries: Ordered article summaries from
            :func:`summarize_articles`.
        slack: Slack interaction handler for channel messages, forms,
            and free-text input.
        session: Optional async database session for storing learning
            data.  When ``None``, feedback is not persisted.
        newsletter_id: Optional newsletter association for feedback
            storage.

    Returns:
        :class:`SummarizationOutput` with the final article data, text,
        and model identifier.
    """
    model_id = get_model(LLMPurpose.SUMMARY)

    # Build initial formatted text and output articles
    original_text = format_summary_slack_text(summaries)
    output_articles = summaries_to_output_articles(summaries)
    blocks = build_summary_slack_blocks(summaries)
    form_fields = build_next_steps_form()

    # Loop state
    regenerated_text: str | None = None
    switch_value: str | None = None

    while True:
        # Step 1: Route content via conditional output router
        route = conditional_output_router(
            switch_value=switch_value,
            original_text=original_text,
            re_generated_text=regenerated_text,
            content_valid=(
                SUMMARY_HEADER in regenerated_text
                if regenerated_text is not None
                else True
            ),
        )
        current_text = route.text

        # Step 2: Share in Slack channel
        await slack.send_channel_message(current_text, blocks=blocks)

        # Step 3: Send next-steps form and wait for response
        response = await slack.send_and_wait_form(
            NEXT_STEPS_MESSAGE,
            form_fields=form_fields,
            button_label=NEXT_STEPS_BUTTON_LABEL,
            form_title=NEXT_STEPS_FORM_TITLE,
            form_description=NEXT_STEPS_FORM_DESCRIPTION,
        )

        choice = parse_next_steps_response(response)
        switch_value = response.get(NEXT_STEPS_FIELD_LABEL, "")

        # Step 4: Route based on user selection
        if choice == UserChoice.YES:
            return SummarizationOutput(
                articles=output_articles,
                text=current_text,
                model=model_id,
            )

        if choice == UserChoice.PROVIDE_FEEDBACK:
            # Step 5a: Collect feedback
            user_feedback = await slack.send_and_wait_freetext(
                FEEDBACK_MESSAGE,
                button_label=FEEDBACK_BUTTON_LABEL,
                form_title=FEEDBACK_FORM_TITLE,
                form_description=FEEDBACK_FORM_DESCRIPTION,
            )

            # Step 5b: Regenerate via LLM
            regenerated_text = await call_regeneration_llm(
                original_text=current_text,
                user_feedback=user_feedback,
            )

            # Step 5c: Extract learning data
            learning_note = await extract_summary_learning_data(
                feedback=user_feedback,
                input_text=current_text,
                model_output=regenerated_text,
            )

            # Step 5d: Store learning data
            if session is not None:
                await store_summarization_feedback(
                    session,
                    learning_note,
                    newsletter_id=newsletter_id,
                )

            # Loop back — regenerated_text will be picked up by router
            continue

        # Restart Chat or unrecognized — reset and loop
        regenerated_text = None
