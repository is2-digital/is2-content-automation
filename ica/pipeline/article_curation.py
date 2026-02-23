"""Article curation — Step 1 data preparation and approval flow.

**Data preparation** (steps 1–5):

1. Sending initial Slack notification
2. Clearing the Google Sheet
3. Fetching unapproved articles from PostgreSQL
4. Processing dates and normalizing fields for display
5. Appending formatted articles to Google Sheet

**Approval flow** (steps 6–10):

6. Send Slack approval request (sendAndWait) with link to the sheet
7. After user responds, fetch all rows from Google Sheet
8. Validate: at least one article has ``approved=yes`` AND ``newsletter_id``
9. If invalid: send Slack re-validation message and loop back to step 6
10. If valid: filter approved articles and return structured output

See PRD Section 3.1.
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


class SlackApprovalSender(Protocol):
    """Sends a message and blocks until the user clicks the approval button.

    Ports the n8n Slack ``sendAndWait`` operation.
    """

    async def send_and_wait(
        self,
        channel: str,
        text: str,
        *,
        approve_label: str = "Proceed to next steps",
    ) -> None: ...


class SheetWriter(Protocol):
    """Clear and append operations on a Google Sheets spreadsheet."""

    async def clear_sheet(self, spreadsheet_id: str, sheet_name: str) -> None: ...

    async def append_rows(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        rows: list[dict[str, Any]],
    ) -> int: ...


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


@dataclass(frozen=True)
class ApprovedArticle:
    """An article approved by the user during curation.

    Matches the PRD Section 5.1 output schema for Step 1 → Step 2.
    Boolean fields are normalized from the sheet's string values.
    """

    url: str
    title: str
    publish_date: str  # MM/DD/YYYY from sheet
    origin: str
    approved: bool  # always True (filtered)
    newsletter_id: str
    industry_news: bool


@dataclass(frozen=True)
class ApprovalResult:
    """Result of the article curation approval flow."""

    articles: list[ApprovedArticle]
    validation_attempts: int


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INITIAL_NOTIFICATION = (
    "Looking into articles now and starting summarization..."
)

#: Default limit matching n8n ``Fetch data`` Postgres node (limit: 30).
DEFAULT_FETCH_LIMIT = 30

# Slack messages ported from n8n "User message" and "User re-validation message"
# Code nodes.  The ``{spreadsheet_id}`` placeholder is filled at runtime.
APPROVAL_MESSAGE_TEMPLATE = (
    "*Approve Curated Articles Here and click to proceed to next steps when done:* \n"
    "https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit?usp=sharing"
)

REVALIDATION_MESSAGE_TEMPLATE = (
    "* Add yes to approve articles in approved column and add ID in "
    "newsletter_id column to proceed. Re-validate Curated Articles Sheet "
    "and click to proceed to next steps when done:* \n"
    "https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit?usp=sharing"
)

#: Slack message sent when validation passes (n8n "Status Message" node).
STATUS_MESSAGE = "*The google sheet looks good, moving to next steps...*"

#: Button label for the Slack sendAndWait approval form.
APPROVE_LABEL = "Proceed to next steps"


# ---------------------------------------------------------------------------
# Helpers — data preparation (steps 1–5)
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
# Helpers — approval flow (steps 6–10)
# ---------------------------------------------------------------------------


def build_approval_message(spreadsheet_id: str) -> str:
    """Build the initial Slack approval message with link to the sheet.

    Ports the n8n "User message" Code node.
    """
    return APPROVAL_MESSAGE_TEMPLATE.format(spreadsheet_id=spreadsheet_id)


def build_revalidation_message(spreadsheet_id: str) -> str:
    """Build the Slack re-validation message with link to the sheet.

    Ports the n8n "User re-validation message" Code node.
    """
    return REVALIDATION_MESSAGE_TEMPLATE.format(spreadsheet_id=spreadsheet_id)


def _is_approved(value: str) -> bool:
    """Check if a sheet cell value represents approval.

    Ports the n8n validation logic: ``approved.toString().trim().toLowerCase() === 'yes'``.
    """
    return value.strip().lower() == "yes" if value else False


def validate_sheet_data(rows: list[dict[str, str]]) -> bool:
    """Check that at least one row has ``approved=yes`` AND a ``newsletter_id``.

    Ports the n8n "Validate data for required fields" Code node.
    """
    for row in rows:
        approved = row.get("approved", "")
        newsletter_id = row.get("newsletter_id", "")
        if _is_approved(approved) and newsletter_id.strip():
            return True
    return False


def parse_approved_articles(rows: list[dict[str, str]]) -> list[ApprovedArticle]:
    """Filter rows to approved articles and convert to output format.

    Only rows with ``approved=yes`` (case-insensitive) are included.
    String values are normalized to match the PRD Section 5.1 output schema.
    """
    result: list[ApprovedArticle] = []
    for row in rows:
        if not _is_approved(row.get("approved", "")):
            continue
        result.append(
            ApprovedArticle(
                url=row.get("url", ""),
                title=row.get("title", ""),
                publish_date=row.get("publish_date", ""),
                origin=row.get("origin", ""),
                approved=True,
                newsletter_id=row.get("newsletter_id", ""),
                industry_news=_is_approved(row.get("industry_news", "")),
            )
        )
    return result


# ---------------------------------------------------------------------------
# Main orchestration — data preparation (steps 1–5)
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


# ---------------------------------------------------------------------------
# Main orchestration — approval flow (steps 6–10)
# ---------------------------------------------------------------------------


async def run_approval_flow(
    slack: SlackNotifier,
    slack_approval: SlackApprovalSender,
    sheets: SheetReader,
    *,
    spreadsheet_id: str,
    sheet_name: str = "Sheet1",
    channel: str,
) -> ApprovalResult:
    """Run the Slack-based article approval loop.

    Orchestrates PRD Section 3.1 steps 6–10:

    6. Send Slack sendAndWait with approval link
    7. Fetch all rows from Google Sheet
    8. Validate at least one article has ``approved=yes`` AND ``newsletter_id``
    9. If invalid → send re-validation message → loop back to step 6
    10. If valid → send status message → return approved articles

    Args:
        slack: Slack message sender (plain text).
        slack_approval: Slack sendAndWait sender (blocks until user clicks).
        sheets: Google Sheets reader.
        spreadsheet_id: Google Sheets document ID.
        sheet_name: Sheet/tab name within the spreadsheet.
        channel: Slack channel for messages.

    Returns:
        :class:`ApprovalResult` with approved articles and attempt count.
    """
    message = build_approval_message(spreadsheet_id)
    attempts = 0

    while True:
        attempts += 1

        # 6. Send Slack sendAndWait — blocks until user clicks
        await slack_approval.send_and_wait(
            channel, message, approve_label=APPROVE_LABEL,
        )

        # 7. Fetch all rows from Google Sheet
        rows = await sheets.read_rows(spreadsheet_id, sheet_name)

        # 8. Validate
        if validate_sheet_data(rows):
            break

        # 9. Invalid — switch to re-validation message and loop
        message = build_revalidation_message(spreadsheet_id)

    # 10. Notify and return
    await slack.send_message(channel, STATUS_MESSAGE)
    articles = parse_approved_articles(rows)

    return ApprovalResult(
        articles=articles,
        validation_attempts=attempts,
    )
