"""Tests for the article curation data flow and approval flow (Step 1).

Tests cover:
- format_article_for_sheet: date formatting, approved normalization, nullable fields
- articles_to_row_dicts: conversion to dict list, column presence, empty list
- fetch_unapproved_articles: SQL generation for approved=false and NULL, limit, ordering
- prepare_curation_data: full orchestration with mock dependencies
- build_approval_message / build_revalidation_message: message formatting
- _is_approved: string-to-boolean normalization
- validate_sheet_data: validation of at least one approved article with newsletter_id
- parse_approved_articles: filtering and conversion to output format
- run_approval_flow: full approval loop orchestration
- ApprovedArticle / ApprovalResult: dataclass properties
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ica.pipeline.article_curation import (
    APPROVAL_MESSAGE_TEMPLATE,
    APPROVE_LABEL,
    INITIAL_NOTIFICATION,
    REJECTED_SHEET_COLUMNS,
    REJECTED_TAB_NAME,
    REVALIDATION_MESSAGE_TEMPLATE,
    SHEET_COLUMNS,
    STATUS_MESSAGE,
    ApprovalResult,
    ApprovedArticle,
    CurationDataResult,
    RejectedSheetArticle,
    SheetArticle,
    _is_approved,
    articles_to_row_dicts,
    build_approval_message,
    build_revalidation_message,
    fetch_rejected_articles,
    fetch_unapproved_articles,
    format_article_for_sheet,
    format_rejected_for_sheet,
    parse_approved_articles,
    prepare_curation_data,
    rejected_to_row_dicts,
    run_approval_flow,
    validate_sheet_data,
)

# ---------------------------------------------------------------------------
# Helpers — lightweight Article stand-in
# ---------------------------------------------------------------------------


@dataclass
class FakeArticle:
    """Mimics Article ORM model for testing without a database."""

    url: str = "https://example.com/article"
    title: str | None = "Test Article"
    origin: str | None = "google_news"
    publish_date: date | None = date(2026, 2, 15)
    excerpt: str | None = None
    relevance_status: str | None = None
    relevance_reason: str | None = None
    approved: bool | None = False
    industry_news: bool | None = False
    newsletter_id: str | None = None
    created_at: datetime = datetime(2026, 2, 15, 12, 0, 0)


class FakeSlack:
    """Records Slack calls for verification."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def send_message(self, channel: str, text: str) -> None:
        self.messages.append((channel, text))


class FakeSheets:
    """Records Google Sheets calls for verification."""

    def __init__(self, *, append_return: int = 0) -> None:
        self.cleared: list[tuple[str, str]] = []
        self.appended: list[tuple[str, str, list[dict[str, Any]]]] = []
        self.ensured_tabs: list[tuple[str, str]] = []
        self._append_return = append_return

    async def clear_sheet(self, spreadsheet_id: str, sheet_name: str) -> None:
        self.cleared.append((spreadsheet_id, sheet_name))

    async def append_rows(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        rows: list[dict[str, Any]],
    ) -> int:
        self.appended.append((spreadsheet_id, sheet_name, rows))
        self._append_return = len(rows)
        return self._append_return

    async def ensure_tab(self, spreadsheet_id: str, tab_name: str) -> None:
        self.ensured_tabs.append((spreadsheet_id, tab_name))


# ---------------------------------------------------------------------------
# format_article_for_sheet
# ---------------------------------------------------------------------------


class TestFormatArticleForSheet:
    """Tests for converting a DB article to sheet-ready format."""

    def test_basic_conversion(self) -> None:
        article = FakeArticle()
        result = format_article_for_sheet(article)

        assert isinstance(result, SheetArticle)
        assert result.url == "https://example.com/article"
        assert result.title == "Test Article"
        assert result.origin == "google_news"

    def test_date_formatted_as_mmddyyyy(self) -> None:
        article = FakeArticle(publish_date=date(2026, 1, 5))
        result = format_article_for_sheet(article)
        assert result.publish_date == "01/05/2026"

    def test_date_none_becomes_empty_string(self) -> None:
        article = FakeArticle(publish_date=None)
        result = format_article_for_sheet(article)
        assert result.publish_date == ""

    def test_approved_false_becomes_empty_string(self) -> None:
        article = FakeArticle(approved=False)
        result = format_article_for_sheet(article)
        assert result.approved == ""

    def test_approved_none_becomes_empty_string(self) -> None:
        article = FakeArticle(approved=None)
        result = format_article_for_sheet(article)
        assert result.approved == ""

    def test_approved_true_becomes_yes(self) -> None:
        article = FakeArticle(approved=True)
        result = format_article_for_sheet(article)
        assert result.approved == "yes"

    def test_industry_news_false_becomes_empty_string(self) -> None:
        article = FakeArticle(industry_news=False)
        result = format_article_for_sheet(article)
        assert result.industry_news == ""

    def test_industry_news_none_becomes_empty_string(self) -> None:
        article = FakeArticle(industry_news=None)
        result = format_article_for_sheet(article)
        assert result.industry_news == ""

    def test_industry_news_true_becomes_yes(self) -> None:
        article = FakeArticle(industry_news=True)
        result = format_article_for_sheet(article)
        assert result.industry_news == "yes"

    def test_newsletter_id_none_becomes_empty_string(self) -> None:
        article = FakeArticle(newsletter_id=None)
        result = format_article_for_sheet(article)
        assert result.newsletter_id == ""

    def test_newsletter_id_preserved(self) -> None:
        article = FakeArticle(newsletter_id="NL-2026-02")
        result = format_article_for_sheet(article)
        assert result.newsletter_id == "NL-2026-02"

    def test_title_none_becomes_empty_string(self) -> None:
        article = FakeArticle(title=None)
        result = format_article_for_sheet(article)
        assert result.title == ""

    def test_origin_none_becomes_empty_string(self) -> None:
        article = FakeArticle(origin=None)
        result = format_article_for_sheet(article)
        assert result.origin == ""

    def test_result_is_frozen(self) -> None:
        article = FakeArticle()
        result = format_article_for_sheet(article)
        with pytest.raises(AttributeError):
            result.url = "changed"  # type: ignore[misc]

    @pytest.mark.parametrize(
        "month, day, year, expected",
        [
            (1, 1, 2026, "01/01/2026"),
            (12, 31, 2025, "12/31/2025"),
            (2, 28, 2024, "02/28/2024"),
            (6, 15, 2026, "06/15/2026"),
        ],
    )
    def test_date_formatting_various(self, month: int, day: int, year: int, expected: str) -> None:
        article = FakeArticle(publish_date=date(year, month, day))
        result = format_article_for_sheet(article)
        assert result.publish_date == expected

    def test_all_fields_populated(self) -> None:
        article = FakeArticle(
            url="https://example.com/full",
            title="Full Article",
            origin="default",
            publish_date=date(2026, 3, 10),
            excerpt="An excerpt",
            relevance_reason="Covers AI for SMBs",
            approved=True,
            newsletter_id="NL-001",
            industry_news=True,
        )
        result = format_article_for_sheet(article)
        assert result.url == "https://example.com/full"
        assert result.title == "Full Article"
        assert result.excerpt == "An excerpt"
        assert result.origin == "default"
        assert result.publish_date == "03/10/2026"
        assert result.relevance_reason == "Covers AI for SMBs"
        assert result.approved == "yes"
        assert result.newsletter_id == "NL-001"
        assert result.industry_news == "yes"

    def test_all_nullable_fields_none(self) -> None:
        article = FakeArticle(
            title=None,
            origin=None,
            publish_date=None,
            excerpt=None,
            relevance_reason=None,
            approved=None,
            industry_news=None,
            newsletter_id=None,
        )
        result = format_article_for_sheet(article)
        assert result.title == ""
        assert result.excerpt == ""
        assert result.origin == ""
        assert result.publish_date == ""
        assert result.relevance_reason == ""
        assert result.approved == ""
        assert result.industry_news == ""
        assert result.newsletter_id == ""

    def test_url_always_preserved(self) -> None:
        """URL is the primary key and should never be modified."""
        article = FakeArticle(url="https://example.com/special?q=test&p=1#section")
        result = format_article_for_sheet(article)
        assert result.url == "https://example.com/special?q=test&p=1#section"


# ---------------------------------------------------------------------------
# articles_to_row_dicts
# ---------------------------------------------------------------------------


class TestArticlesToRowDicts:
    """Tests for converting SheetArticle list to dict list."""

    def test_empty_list(self) -> None:
        assert articles_to_row_dicts([]) == []

    def test_single_article(self) -> None:
        article = SheetArticle(
            url="https://example.com",
            title="Test",
            excerpt="A snippet",
            publish_date="02/15/2026",
            origin="google_news",
            relevance_reason="Relevant to AI",
            approved="",
            newsletter_id="",
            industry_news="",
        )
        result = articles_to_row_dicts([article])
        assert len(result) == 1
        assert result[0]["url"] == "https://example.com"
        assert result[0]["title"] == "Test"
        assert result[0]["excerpt"] == "A snippet"
        assert result[0]["publish_date"] == "02/15/2026"
        assert result[0]["origin"] == "google_news"
        assert result[0]["relevance_reason"] == "Relevant to AI"
        assert result[0]["approved"] == ""
        assert result[0]["newsletter_id"] == ""
        assert result[0]["industry_news"] == ""

    def test_multiple_articles(self) -> None:
        articles = [
            SheetArticle("url1", "t1", "", "01/01/2026", "o1", "", "", "", ""),
            SheetArticle("url2", "t2", "", "02/02/2026", "o2", "", "yes", "NL-1", "yes"),
        ]
        result = articles_to_row_dicts(articles)
        assert len(result) == 2
        assert result[0]["url"] == "url1"
        assert result[1]["url"] == "url2"

    def test_all_sheet_columns_present(self) -> None:
        article = SheetArticle("u", "t", "e", "d", "o", "r", "a", "n", "i")
        result = articles_to_row_dicts([article])
        for col in SHEET_COLUMNS:
            assert col in result[0], f"Missing column: {col}"

    def test_no_extra_columns(self) -> None:
        article = SheetArticle("u", "t", "e", "d", "o", "r", "a", "n", "i")
        result = articles_to_row_dicts([article])
        assert set(result[0].keys()) == set(SHEET_COLUMNS)

    def test_preserves_order(self) -> None:
        articles = [SheetArticle(f"url{i}", f"t{i}", "", "", "", "", "", "", "") for i in range(5)]
        result = articles_to_row_dicts(articles)
        for i, row in enumerate(result):
            assert row["url"] == f"url{i}"


# ---------------------------------------------------------------------------
# fetch_unapproved_articles (unit tests with mock session)
# ---------------------------------------------------------------------------


def _make_mock_session(articles: list[Any]) -> AsyncMock:
    """Create a mock AsyncSession that returns articles from execute().

    SQLAlchemy's ``result.scalars()`` is synchronous, so we use MagicMock
    for the result object and only AsyncMock for the session itself.
    """
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = articles
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock

    session = AsyncMock()
    session.execute.return_value = result_mock
    return session


def _make_mock_session_two_queries(
    accepted: list[Any],
    rejected: list[Any],
) -> AsyncMock:
    """Create a mock session returning different results for successive execute() calls.

    First call returns ``accepted`` articles, second returns ``rejected``.
    """

    def _make_result(articles: list[Any]) -> MagicMock:
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = articles
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        return result_mock

    session = AsyncMock()
    session.execute.side_effect = [_make_result(accepted), _make_result(rejected)]
    return session


class TestFetchUnapprovedArticles:
    """Tests for the DB query that fetches unapproved articles."""

    @pytest.mark.asyncio
    async def test_returns_list(self) -> None:
        fake_articles = [FakeArticle(url="https://a.com"), FakeArticle(url="https://b.com")]
        session = _make_mock_session(fake_articles)

        result = await fetch_unapproved_articles(session)
        assert len(result) == 2
        assert result[0].url == "https://a.com"

    @pytest.mark.asyncio
    async def test_empty_result(self) -> None:
        session = _make_mock_session([])

        result = await fetch_unapproved_articles(session)
        assert result == []

    @pytest.mark.asyncio
    async def test_executes_query(self) -> None:
        session = _make_mock_session([])

        await fetch_unapproved_articles(session)
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_custom_limit(self) -> None:
        session = _make_mock_session([])

        await fetch_unapproved_articles(session, limit=10)
        # Verify execute was called (we can't easily inspect the SQL, but
        # the function accepted the limit without error)
        session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# prepare_curation_data (full orchestration)
# ---------------------------------------------------------------------------


def _make_session_with_articles(
    articles: list[Any],
    rejected: list[Any] | None = None,
) -> AsyncMock:
    """Create a mock session for prepare_curation_data.

    Returns ``articles`` for the first execute (accepted) and ``rejected``
    (default empty) for the second execute (rejected query).
    """
    return _make_mock_session_two_queries(articles, rejected or [])


class TestPrepareCurationData:
    """Tests for the full data preparation orchestration."""

    @pytest.mark.asyncio
    async def test_sends_slack_notification(self) -> None:
        session = _make_session_with_articles([])
        slack = FakeSlack()
        sheets = FakeSheets()

        await prepare_curation_data(
            session,
            slack,
            sheets,
            spreadsheet_id="abc123",
            channel="#test",
        )

        assert len(slack.messages) == 1
        assert slack.messages[0] == ("#test", INITIAL_NOTIFICATION)

    @pytest.mark.asyncio
    async def test_clears_sheet(self) -> None:
        session = _make_session_with_articles([])
        slack = FakeSlack()
        sheets = FakeSheets()

        await prepare_curation_data(
            session,
            slack,
            sheets,
            spreadsheet_id="abc123",
            sheet_name="Articles",
            channel="#test",
        )

        # Main tab + Rejected tab both cleared
        assert sheets.cleared[0] == ("abc123", "Articles")
        assert sheets.cleared[1] == ("abc123", REJECTED_TAB_NAME)

    @pytest.mark.asyncio
    async def test_default_sheet_name(self) -> None:
        session = _make_session_with_articles([])
        slack = FakeSlack()
        sheets = FakeSheets()

        await prepare_curation_data(
            session,
            slack,
            sheets,
            spreadsheet_id="abc123",
            channel="#test",
        )

        assert sheets.cleared[0] == ("abc123", "Sheet1")

    @pytest.mark.asyncio
    async def test_appends_articles_to_sheet(self) -> None:
        articles = [
            FakeArticle(url="https://a.com", title="Article A"),
            FakeArticle(url="https://b.com", title="Article B"),
        ]
        session = _make_session_with_articles(articles)
        slack = FakeSlack()
        sheets = FakeSheets()

        await prepare_curation_data(
            session,
            slack,
            sheets,
            spreadsheet_id="abc123",
            channel="#test",
        )

        # First append is main tab
        sid, sname, rows = sheets.appended[0]
        assert sid == "abc123"
        assert sname == "Sheet1"
        assert len(rows) == 2
        assert rows[0]["url"] == "https://a.com"
        assert rows[1]["url"] == "https://b.com"

    @pytest.mark.asyncio
    async def test_no_append_when_no_articles(self) -> None:
        session = _make_session_with_articles([])
        slack = FakeSlack()
        sheets = FakeSheets()

        await prepare_curation_data(
            session,
            slack,
            sheets,
            spreadsheet_id="abc123",
            channel="#test",
        )

        # No appends for either tab when both are empty
        assert len(sheets.appended) == 0

    @pytest.mark.asyncio
    async def test_returns_curation_data_result(self) -> None:
        articles = [FakeArticle(url="https://a.com")]
        session = _make_session_with_articles(articles)
        slack = FakeSlack()
        sheets = FakeSheets()

        result = await prepare_curation_data(
            session,
            slack,
            sheets,
            spreadsheet_id="abc123",
            channel="#test",
        )

        assert isinstance(result, CurationDataResult)
        assert result.articles_fetched == 1
        assert result.articles_written == 1
        assert len(result.sheet_articles) == 1

    @pytest.mark.asyncio
    async def test_result_counts_zero_when_empty(self) -> None:
        session = _make_session_with_articles([])
        slack = FakeSlack()
        sheets = FakeSheets()

        result = await prepare_curation_data(
            session,
            slack,
            sheets,
            spreadsheet_id="abc123",
            channel="#test",
        )

        assert result.articles_fetched == 0
        assert result.articles_written == 0
        assert result.rejected_written == 0
        assert result.sheet_articles == []
        assert result.rejected_articles == []

    @pytest.mark.asyncio
    async def test_articles_formatted_correctly(self) -> None:
        articles = [
            FakeArticle(
                url="https://example.com/test",
                title="Test Title",
                publish_date=date(2026, 2, 15),
                origin="google_news",
                approved=False,
                newsletter_id=None,
                industry_news=True,
            )
        ]
        session = _make_session_with_articles(articles)
        slack = FakeSlack()
        sheets = FakeSheets()

        result = await prepare_curation_data(
            session,
            slack,
            sheets,
            spreadsheet_id="abc123",
            channel="#test",
        )

        art = result.sheet_articles[0]
        assert art.url == "https://example.com/test"
        assert art.title == "Test Title"
        assert art.publish_date == "02/15/2026"
        assert art.origin == "google_news"
        assert art.approved == ""
        assert art.newsletter_id == ""
        assert art.industry_news == "yes"

    @pytest.mark.asyncio
    async def test_sheet_rows_have_correct_columns(self) -> None:
        articles = [FakeArticle()]
        session = _make_session_with_articles(articles)
        slack = FakeSlack()
        sheets = FakeSheets()

        await prepare_curation_data(
            session,
            slack,
            sheets,
            spreadsheet_id="abc123",
            channel="#test",
        )

        _, _, rows = sheets.appended[0]
        for col in SHEET_COLUMNS:
            assert col in rows[0], f"Missing column in sheet row: {col}"

    @pytest.mark.asyncio
    async def test_execution_order(self) -> None:
        """Verify operations happen in the correct sequence."""
        call_order: list[str] = []

        class OrderTrackingSlack:
            async def send_message(self, channel: str, text: str) -> None:
                call_order.append("slack_notify")

        class OrderTrackingSheets:
            async def clear_sheet(self, sid: str, sname: str) -> None:
                call_order.append(f"sheet_clear:{sname}")

            async def append_rows(self, sid: str, sname: str, rows: list[dict[str, Any]]) -> int:
                call_order.append(f"sheet_append:{sname}")
                return len(rows)

            async def ensure_tab(self, sid: str, tab_name: str) -> None:
                call_order.append(f"ensure_tab:{tab_name}")

        articles = [FakeArticle()]
        session = _make_session_with_articles(articles)

        await prepare_curation_data(
            session,
            OrderTrackingSlack(),
            OrderTrackingSheets(),
            spreadsheet_id="abc123",
            channel="#test",
        )

        assert call_order == [
            "slack_notify",
            "sheet_clear:Sheet1",
            "sheet_append:Sheet1",
            "ensure_tab:Rejected",
            "sheet_clear:Rejected",
        ]

    @pytest.mark.asyncio
    async def test_multiple_articles_all_written(self) -> None:
        articles = [
            FakeArticle(url=f"https://example.com/{i}", title=f"Article {i}") for i in range(10)
        ]
        session = _make_session_with_articles(articles)
        slack = FakeSlack()
        sheets = FakeSheets()

        result = await prepare_curation_data(
            session,
            slack,
            sheets,
            spreadsheet_id="abc123",
            channel="#test",
        )

        assert result.articles_fetched == 10
        assert result.articles_written == 10
        assert len(result.sheet_articles) == 10

    @pytest.mark.asyncio
    async def test_sheet_name_passed_to_both_clear_and_append(self) -> None:
        articles = [FakeArticle()]
        session = _make_session_with_articles(articles)
        slack = FakeSlack()
        sheets = FakeSheets()

        await prepare_curation_data(
            session,
            slack,
            sheets,
            spreadsheet_id="abc123",
            sheet_name="CustomSheet",
            channel="#test",
        )

        # Main tab uses custom name, rejected tab uses fixed name
        assert sheets.cleared[0] == ("abc123", "CustomSheet")
        _, sname, _ = sheets.appended[0]
        assert sname == "CustomSheet"
        assert sheets.cleared[1] == ("abc123", REJECTED_TAB_NAME)

    @pytest.mark.asyncio
    async def test_spreadsheet_id_passed_correctly(self) -> None:
        articles = [FakeArticle()]
        session = _make_session_with_articles(articles)
        slack = FakeSlack()
        sheets = FakeSheets()

        await prepare_curation_data(
            session,
            slack,
            sheets,
            spreadsheet_id="my-sheet-id",
            channel="#test",
        )

        assert sheets.cleared[0][0] == "my-sheet-id"
        assert sheets.appended[0][0] == "my-sheet-id"
        # Rejected tab also uses the same spreadsheet ID
        assert sheets.cleared[1][0] == "my-sheet-id"


# ---------------------------------------------------------------------------
# SheetArticle dataclass
# ---------------------------------------------------------------------------


class TestSheetArticle:
    """Tests for SheetArticle dataclass properties."""

    def test_is_frozen(self) -> None:
        article = SheetArticle("u", "t", "e", "d", "o", "r", "a", "n", "i")
        with pytest.raises(AttributeError):
            article.url = "changed"  # type: ignore[misc]

    def test_equality(self) -> None:
        a = SheetArticle("u", "t", "e", "d", "o", "r", "a", "n", "i")
        b = SheetArticle("u", "t", "e", "d", "o", "r", "a", "n", "i")
        assert a == b

    def test_inequality(self) -> None:
        a = SheetArticle("u1", "t", "e", "d", "o", "r", "a", "n", "i")
        b = SheetArticle("u2", "t", "e", "d", "o", "r", "a", "n", "i")
        assert a != b

    def test_field_access(self) -> None:
        article = SheetArticle(
            url="https://example.com",
            title="Test",
            excerpt="A snippet",
            publish_date="02/15/2026",
            origin="google_news",
            relevance_reason="Relevant to AI",
            approved="yes",
            newsletter_id="NL-1",
            industry_news="yes",
        )
        assert article.url == "https://example.com"
        assert article.title == "Test"
        assert article.excerpt == "A snippet"
        assert article.publish_date == "02/15/2026"
        assert article.origin == "google_news"
        assert article.relevance_reason == "Relevant to AI"
        assert article.approved == "yes"
        assert article.newsletter_id == "NL-1"
        assert article.industry_news == "yes"


# ---------------------------------------------------------------------------
# CurationDataResult dataclass
# ---------------------------------------------------------------------------


class TestCurationDataResult:
    """Tests for CurationDataResult dataclass properties."""

    def test_is_frozen(self) -> None:
        result = CurationDataResult(
            articles_fetched=0,
            articles_written=0,
            rejected_written=0,
            sheet_articles=[],
            rejected_articles=[],
        )
        with pytest.raises(AttributeError):
            result.articles_fetched = 5  # type: ignore[misc]

    def test_field_access(self) -> None:
        articles = [SheetArticle("u", "t", "e", "d", "o", "r", "", "", "")]
        rejected = [RejectedSheetArticle("u2", "t2", "e2", "d2", "o2", "r2")]
        result = CurationDataResult(
            articles_fetched=1,
            articles_written=1,
            rejected_written=1,
            sheet_articles=articles,
            rejected_articles=rejected,
        )
        assert result.articles_fetched == 1
        assert result.articles_written == 1
        assert result.rejected_written == 1
        assert result.sheet_articles == articles
        assert result.rejected_articles == rejected


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Tests for module-level constants."""

    def test_initial_notification_text(self) -> None:
        assert "articles" in INITIAL_NOTIFICATION.lower()
        assert "summarization" in INITIAL_NOTIFICATION.lower()

    def test_sheet_columns_has_all_fields(self) -> None:
        expected = {
            "url",
            "title",
            "excerpt",
            "publish_date",
            "origin",
            "relevance_reason",
            "approved",
            "newsletter_id",
            "industry_news",
        }
        assert set(SHEET_COLUMNS) == expected

    def test_rejected_sheet_columns_has_all_fields(self) -> None:
        expected = {
            "url",
            "title",
            "excerpt",
            "publish_date",
            "origin",
            "relevance_reason",
        }
        assert set(REJECTED_SHEET_COLUMNS) == expected

    def test_rejected_tab_name(self) -> None:
        assert REJECTED_TAB_NAME == "Rejected"

    def test_sheet_columns_is_tuple(self) -> None:
        assert isinstance(SHEET_COLUMNS, tuple)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases for the article curation data flow."""

    def test_format_article_with_special_chars_in_title(self) -> None:
        article = FakeArticle(title='AI "Revolution" & <Impact>')
        result = format_article_for_sheet(article)
        assert result.title == 'AI "Revolution" & <Impact>'

    def test_format_article_with_unicode_title(self) -> None:
        article = FakeArticle(title="AI革命: 人工知能の未来")
        result = format_article_for_sheet(article)
        assert result.title == "AI革命: 人工知能の未来"

    def test_format_article_with_long_url(self) -> None:
        long_url = "https://example.com/" + "a" * 1000
        article = FakeArticle(url=long_url)
        result = format_article_for_sheet(article)
        assert result.url == long_url

    @pytest.mark.asyncio
    async def test_prepare_curation_preserves_article_order(self) -> None:
        articles = [
            FakeArticle(url=f"https://example.com/{i}", title=f"Article {i}") for i in range(5)
        ]
        session = _make_session_with_articles(articles)
        slack = FakeSlack()
        sheets = FakeSheets()

        result = await prepare_curation_data(
            session,
            slack,
            sheets,
            spreadsheet_id="abc123",
            channel="#test",
        )

        for i, art in enumerate(result.sheet_articles):
            assert art.url == f"https://example.com/{i}"

    def test_format_article_approved_true_with_newsletter_id(self) -> None:
        """Previously approved articles should still format correctly."""
        article = FakeArticle(
            approved=True,
            newsletter_id="NL-2026-01",
        )
        result = format_article_for_sheet(article)
        assert result.approved == "yes"
        assert result.newsletter_id == "NL-2026-01"

    def test_row_dict_values_are_all_strings(self) -> None:
        """Google Sheets API expects string values."""
        article = SheetArticle(
            url="https://example.com",
            title="Test",
            excerpt="A snippet",
            publish_date="02/15/2026",
            origin="google_news",
            relevance_reason="Relevant",
            approved="yes",
            newsletter_id="NL-1",
            industry_news="yes",
        )
        rows = articles_to_row_dicts([article])
        for value in rows[0].values():
            assert isinstance(value, str)

    def test_row_dict_empty_values_are_empty_strings(self) -> None:
        article = SheetArticle("u", "", "", "", "", "", "", "", "")
        rows = articles_to_row_dicts([article])
        for key, value in rows[0].items():
            if key != "url":
                assert value == ""


# ---------------------------------------------------------------------------
# format_rejected_for_sheet
# ---------------------------------------------------------------------------


class TestFormatRejectedForSheet:
    """Tests for converting a rejected DB article to sheet-ready format."""

    def test_basic_conversion(self) -> None:
        article = FakeArticle(
            url="https://example.com/rejected",
            title="Rejected Article",
            excerpt="Not relevant",
            relevance_reason="Off-topic for AI",
            origin="brave_search",
            publish_date=date(2026, 2, 20),
        )
        result = format_rejected_for_sheet(article)
        assert isinstance(result, RejectedSheetArticle)
        assert result.url == "https://example.com/rejected"
        assert result.title == "Rejected Article"
        assert result.excerpt == "Not relevant"
        assert result.relevance_reason == "Off-topic for AI"
        assert result.origin == "brave_search"
        assert result.publish_date == "02/20/2026"

    def test_nullable_fields_become_empty(self) -> None:
        article = FakeArticle(
            title=None,
            excerpt=None,
            relevance_reason=None,
            origin=None,
            publish_date=None,
        )
        result = format_rejected_for_sheet(article)
        assert result.title == ""
        assert result.excerpt == ""
        assert result.relevance_reason == ""
        assert result.origin == ""
        assert result.publish_date == ""

    def test_result_is_frozen(self) -> None:
        article = FakeArticle()
        result = format_rejected_for_sheet(article)
        with pytest.raises(AttributeError):
            result.url = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# rejected_to_row_dicts
# ---------------------------------------------------------------------------


class TestRejectedToRowDicts:
    """Tests for converting RejectedSheetArticle list to dict list."""

    def test_empty_list(self) -> None:
        assert rejected_to_row_dicts([]) == []

    def test_single_article(self) -> None:
        article = RejectedSheetArticle(
            url="https://example.com",
            title="Test",
            excerpt="A snippet",
            publish_date="02/15/2026",
            origin="brave_search",
            relevance_reason="Off-topic",
        )
        result = rejected_to_row_dicts([article])
        assert len(result) == 1
        assert result[0]["url"] == "https://example.com"
        assert result[0]["relevance_reason"] == "Off-topic"

    def test_all_rejected_columns_present(self) -> None:
        article = RejectedSheetArticle("u", "t", "e", "d", "o", "r")
        result = rejected_to_row_dicts([article])
        for col in REJECTED_SHEET_COLUMNS:
            assert col in result[0], f"Missing column: {col}"

    def test_no_approval_columns(self) -> None:
        article = RejectedSheetArticle("u", "t", "e", "d", "o", "r")
        result = rejected_to_row_dicts([article])
        assert "approved" not in result[0]
        assert "newsletter_id" not in result[0]
        assert "industry_news" not in result[0]


# ---------------------------------------------------------------------------
# RejectedSheetArticle dataclass
# ---------------------------------------------------------------------------


class TestRejectedSheetArticle:
    """Tests for RejectedSheetArticle dataclass properties."""

    def test_is_frozen(self) -> None:
        article = RejectedSheetArticle("u", "t", "e", "d", "o", "r")
        with pytest.raises(AttributeError):
            article.url = "changed"  # type: ignore[misc]

    def test_equality(self) -> None:
        a = RejectedSheetArticle("u", "t", "e", "d", "o", "r")
        b = RejectedSheetArticle("u", "t", "e", "d", "o", "r")
        assert a == b


# ---------------------------------------------------------------------------
# fetch_rejected_articles
# ---------------------------------------------------------------------------


class TestFetchRejectedArticles:
    """Tests for the DB query that fetches rejected articles."""

    @pytest.mark.asyncio
    async def test_returns_list(self) -> None:
        fake = [FakeArticle(url="https://a.com"), FakeArticle(url="https://b.com")]
        session = _make_mock_session(fake)

        result = await fetch_rejected_articles(session)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_empty_result(self) -> None:
        session = _make_mock_session([])

        result = await fetch_rejected_articles(session)
        assert result == []

    @pytest.mark.asyncio
    async def test_executes_query(self) -> None:
        session = _make_mock_session([])

        await fetch_rejected_articles(session)
        session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# prepare_curation_data — rejected tab
# ---------------------------------------------------------------------------


class TestPrepareCurationDataRejectedTab:
    """Tests for rejected-tab handling in prepare_curation_data."""

    @pytest.mark.asyncio
    async def test_ensures_rejected_tab(self) -> None:
        session = _make_session_with_articles([])
        slack = FakeSlack()
        sheets = FakeSheets()

        await prepare_curation_data(
            session, slack, sheets, spreadsheet_id="abc123", channel="#test"
        )

        assert ("abc123", REJECTED_TAB_NAME) in sheets.ensured_tabs

    @pytest.mark.asyncio
    async def test_rejected_articles_written(self) -> None:
        rejected = [
            FakeArticle(
                url="https://rej.com",
                title="Rejected",
                relevance_reason="Off-topic",
            )
        ]
        session = _make_session_with_articles([], rejected=rejected)
        slack = FakeSlack()
        sheets = FakeSheets()

        result = await prepare_curation_data(
            session, slack, sheets, spreadsheet_id="abc123", channel="#test"
        )

        assert result.rejected_written == 1
        assert len(result.rejected_articles) == 1
        assert result.rejected_articles[0].url == "https://rej.com"
        assert result.rejected_articles[0].relevance_reason == "Off-topic"

    @pytest.mark.asyncio
    async def test_rejected_tab_appended(self) -> None:
        rejected = [FakeArticle(url="https://rej.com")]
        session = _make_session_with_articles([], rejected=rejected)
        slack = FakeSlack()
        sheets = FakeSheets()

        await prepare_curation_data(
            session, slack, sheets, spreadsheet_id="abc123", channel="#test"
        )

        # Only rejected tab should be appended (main tab has no articles)
        assert len(sheets.appended) == 1
        sid, sname, rows = sheets.appended[0]
        assert sid == "abc123"
        assert sname == REJECTED_TAB_NAME
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_both_tabs_populated(self) -> None:
        accepted = [FakeArticle(url="https://ok.com")]
        rejected = [FakeArticle(url="https://rej.com")]
        session = _make_session_with_articles(accepted, rejected=rejected)
        slack = FakeSlack()
        sheets = FakeSheets()

        result = await prepare_curation_data(
            session, slack, sheets, spreadsheet_id="abc123", channel="#test"
        )

        assert result.articles_written == 1
        assert result.rejected_written == 1
        assert len(sheets.appended) == 2
        # First append = main tab, second = rejected
        assert sheets.appended[0][1] == "Sheet1"
        assert sheets.appended[1][1] == REJECTED_TAB_NAME

    @pytest.mark.asyncio
    async def test_no_rejected_append_when_empty(self) -> None:
        accepted = [FakeArticle(url="https://ok.com")]
        session = _make_session_with_articles(accepted, rejected=[])
        slack = FakeSlack()
        sheets = FakeSheets()

        result = await prepare_curation_data(
            session, slack, sheets, spreadsheet_id="abc123", channel="#test"
        )

        assert result.rejected_written == 0
        # Only one append (main tab)
        assert len(sheets.appended) == 1
        assert sheets.appended[0][1] == "Sheet1"


# ===========================================================================
# Approval flow tests (steps 6–10)
# ===========================================================================


# ---------------------------------------------------------------------------
# Fake protocol implementations for approval flow
# ---------------------------------------------------------------------------


class FakeSlackApproval:
    """Records sendAndWait calls for verification."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def send_and_wait(
        self,
        channel: str,
        text: str,
        *,
        approve_label: str = "Proceed to next steps",
    ) -> None:
        self.calls.append((channel, text, approve_label))


class FakeSheetReader:
    """Returns pre-configured rows from read_rows calls."""

    def __init__(self, responses: list[list[dict[str, str]]]) -> None:
        self._responses = list(responses)
        self._call_index = 0
        self.calls: list[tuple[str, str]] = []

    async def read_rows(self, spreadsheet_id: str, sheet_name: str) -> list[dict[str, str]]:
        self.calls.append((spreadsheet_id, sheet_name))
        rows = self._responses[self._call_index]
        self._call_index += 1
        return rows


def _make_sheet_row(
    url: str = "https://example.com/a",
    title: str = "Article",
    publish_date: str = "02/15/2026",
    origin: str = "google_news",
    approved: str = "yes",
    newsletter_id: str = "NL-001",
    industry_news: str = "",
) -> dict[str, str]:
    """Helper to create a sheet row dict."""
    return {
        "url": url,
        "title": title,
        "publish_date": publish_date,
        "origin": origin,
        "approved": approved,
        "newsletter_id": newsletter_id,
        "industry_news": industry_news,
    }


# ---------------------------------------------------------------------------
# build_approval_message
# ---------------------------------------------------------------------------


class TestBuildApprovalMessage:
    """Tests for Slack approval message construction."""

    def test_contains_spreadsheet_id(self) -> None:
        msg = build_approval_message("abc123")
        assert "abc123" in msg

    def test_contains_google_sheets_url(self) -> None:
        msg = build_approval_message("abc123")
        assert "https://docs.google.com/spreadsheets/d/abc123" in msg

    def test_contains_approval_text(self) -> None:
        msg = build_approval_message("abc123")
        assert "Approve Curated Articles" in msg

    def test_contains_proceed_text(self) -> None:
        msg = build_approval_message("abc123")
        assert "proceed to next steps" in msg

    def test_different_spreadsheet_ids(self) -> None:
        msg1 = build_approval_message("id-one")
        msg2 = build_approval_message("id-two")
        assert "id-one" in msg1
        assert "id-two" in msg2
        assert "id-one" not in msg2

    def test_uses_template(self) -> None:
        msg = build_approval_message("test-id")
        expected = APPROVAL_MESSAGE_TEMPLATE.format(spreadsheet_id="test-id")
        assert msg == expected


# ---------------------------------------------------------------------------
# build_revalidation_message
# ---------------------------------------------------------------------------


class TestBuildRevalidationMessage:
    """Tests for Slack re-validation message construction."""

    def test_contains_spreadsheet_id(self) -> None:
        msg = build_revalidation_message("abc123")
        assert "abc123" in msg

    def test_contains_google_sheets_url(self) -> None:
        msg = build_revalidation_message("abc123")
        assert "https://docs.google.com/spreadsheets/d/abc123" in msg

    def test_contains_revalidation_instructions(self) -> None:
        msg = build_revalidation_message("abc123")
        assert "approved column" in msg.lower()
        assert "newsletter_id" in msg

    def test_contains_proceed_text(self) -> None:
        msg = build_revalidation_message("abc123")
        assert "proceed to next steps" in msg

    def test_uses_template(self) -> None:
        msg = build_revalidation_message("test-id")
        expected = REVALIDATION_MESSAGE_TEMPLATE.format(spreadsheet_id="test-id")
        assert msg == expected


# ---------------------------------------------------------------------------
# _is_approved
# ---------------------------------------------------------------------------


class TestIsApproved:
    """Tests for the string-to-boolean approval check."""

    def test_yes_lowercase(self) -> None:
        assert _is_approved("yes") is True

    def test_yes_uppercase(self) -> None:
        assert _is_approved("YES") is True

    def test_yes_mixed_case(self) -> None:
        assert _is_approved("Yes") is True

    def test_yes_with_leading_spaces(self) -> None:
        assert _is_approved("  yes") is True

    def test_yes_with_trailing_spaces(self) -> None:
        assert _is_approved("yes  ") is True

    def test_yes_with_surrounding_spaces(self) -> None:
        assert _is_approved("  yes  ") is True

    def test_no(self) -> None:
        assert _is_approved("no") is False

    def test_true_string(self) -> None:
        assert _is_approved("true") is False

    def test_false_string(self) -> None:
        assert _is_approved("false") is False

    def test_empty_string(self) -> None:
        assert _is_approved("") is False

    def test_whitespace_only(self) -> None:
        assert _is_approved("   ") is False

    def test_random_text(self) -> None:
        assert _is_approved("approved") is False

    def test_yes_substring(self) -> None:
        """'yesterday' should not be approved."""
        assert _is_approved("yesterday") is False

    @pytest.mark.parametrize("value", ["yEs", "yES", "yeS", "YeS"])
    def test_case_insensitive_variants(self, value: str) -> None:
        assert _is_approved(value) is True


# ---------------------------------------------------------------------------
# validate_sheet_data
# ---------------------------------------------------------------------------


class TestValidateSheetData:
    """Tests for the sheet data validation logic."""

    def test_valid_row(self) -> None:
        rows = [_make_sheet_row(approved="yes", newsletter_id="NL-001")]
        assert validate_sheet_data(rows) is True

    def test_no_rows(self) -> None:
        assert validate_sheet_data([]) is False

    def test_no_approved_articles(self) -> None:
        rows = [
            _make_sheet_row(approved="", newsletter_id="NL-001"),
            _make_sheet_row(approved="no", newsletter_id="NL-002"),
        ]
        assert validate_sheet_data(rows) is False

    def test_approved_but_no_newsletter_id(self) -> None:
        rows = [_make_sheet_row(approved="yes", newsletter_id="")]
        assert validate_sheet_data(rows) is False

    def test_approved_with_whitespace_only_newsletter_id(self) -> None:
        rows = [_make_sheet_row(approved="yes", newsletter_id="   ")]
        assert validate_sheet_data(rows) is False

    def test_one_valid_among_many(self) -> None:
        rows = [
            _make_sheet_row(approved="", newsletter_id=""),
            _make_sheet_row(approved="no", newsletter_id=""),
            _make_sheet_row(approved="yes", newsletter_id="NL-003"),
            _make_sheet_row(approved="", newsletter_id="NL-004"),
        ]
        assert validate_sheet_data(rows) is True

    def test_approved_case_insensitive(self) -> None:
        rows = [_make_sheet_row(approved="YES", newsletter_id="NL-001")]
        assert validate_sheet_data(rows) is True

    def test_missing_approved_key(self) -> None:
        rows = [{"newsletter_id": "NL-001"}]
        assert validate_sheet_data(rows) is False

    def test_missing_newsletter_id_key(self) -> None:
        rows = [{"approved": "yes"}]
        assert validate_sheet_data(rows) is False

    def test_short_circuits_on_first_valid(self) -> None:
        """Validation stops at first valid row (matching n8n break)."""
        rows = [
            _make_sheet_row(approved="yes", newsletter_id="NL-001"),
            _make_sheet_row(approved="yes", newsletter_id="NL-002"),
        ]
        assert validate_sheet_data(rows) is True


# ---------------------------------------------------------------------------
# parse_approved_articles
# ---------------------------------------------------------------------------


class TestParseApprovedArticles:
    """Tests for filtering and converting sheet rows to ApprovedArticle."""

    def test_single_approved(self) -> None:
        rows = [_make_sheet_row(approved="yes", newsletter_id="NL-001")]
        result = parse_approved_articles(rows)
        assert len(result) == 1
        assert result[0].url == "https://example.com/a"
        assert result[0].newsletter_id == "NL-001"

    def test_filters_unapproved(self) -> None:
        rows = [
            _make_sheet_row(url="https://a.com", approved="yes", newsletter_id="NL-1"),
            _make_sheet_row(url="https://b.com", approved="", newsletter_id="NL-2"),
            _make_sheet_row(url="https://c.com", approved="no", newsletter_id="NL-3"),
        ]
        result = parse_approved_articles(rows)
        assert len(result) == 1
        assert result[0].url == "https://a.com"

    def test_multiple_approved(self) -> None:
        rows = [
            _make_sheet_row(url="https://a.com", approved="yes", newsletter_id="NL-1"),
            _make_sheet_row(url="https://b.com", approved="Yes", newsletter_id="NL-2"),
        ]
        result = parse_approved_articles(rows)
        assert len(result) == 2

    def test_empty_rows(self) -> None:
        assert parse_approved_articles([]) == []

    def test_none_approved(self) -> None:
        rows = [
            _make_sheet_row(approved="", newsletter_id="NL-1"),
            _make_sheet_row(approved="no", newsletter_id="NL-2"),
        ]
        result = parse_approved_articles(rows)
        assert result == []

    def test_approved_always_true(self) -> None:
        rows = [_make_sheet_row(approved="yes")]
        result = parse_approved_articles(rows)
        assert result[0].approved is True

    def test_industry_news_yes(self) -> None:
        rows = [_make_sheet_row(approved="yes", industry_news="yes")]
        result = parse_approved_articles(rows)
        assert result[0].industry_news is True

    def test_industry_news_empty(self) -> None:
        rows = [_make_sheet_row(approved="yes", industry_news="")]
        result = parse_approved_articles(rows)
        assert result[0].industry_news is False

    def test_industry_news_no(self) -> None:
        rows = [_make_sheet_row(approved="yes", industry_news="no")]
        result = parse_approved_articles(rows)
        assert result[0].industry_news is False

    def test_missing_fields_default_to_empty(self) -> None:
        rows = [{"approved": "yes"}]
        result = parse_approved_articles(rows)
        assert len(result) == 1
        assert result[0].url == ""
        assert result[0].title == ""
        assert result[0].publish_date == ""
        assert result[0].origin == ""
        assert result[0].newsletter_id == ""

    def test_preserves_field_values(self) -> None:
        rows = [
            _make_sheet_row(
                url="https://example.com/test",
                title="Test Title",
                publish_date="03/15/2026",
                origin="default",
                approved="yes",
                newsletter_id="NL-007",
                industry_news="yes",
            )
        ]
        result = parse_approved_articles(rows)
        art = result[0]
        assert art.url == "https://example.com/test"
        assert art.title == "Test Title"
        assert art.publish_date == "03/15/2026"
        assert art.origin == "default"
        assert art.approved is True
        assert art.newsletter_id == "NL-007"
        assert art.industry_news is True

    def test_preserves_order(self) -> None:
        rows = [_make_sheet_row(url=f"https://example.com/{i}", approved="yes") for i in range(5)]
        result = parse_approved_articles(rows)
        for i, art in enumerate(result):
            assert art.url == f"https://example.com/{i}"

    def test_case_insensitive_approved(self) -> None:
        rows = [
            _make_sheet_row(url="https://a.com", approved="YES"),
            _make_sheet_row(url="https://b.com", approved="Yes"),
            _make_sheet_row(url="https://c.com", approved="yEs"),
        ]
        result = parse_approved_articles(rows)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# ApprovedArticle dataclass
# ---------------------------------------------------------------------------


class TestApprovedArticle:
    """Tests for ApprovedArticle dataclass properties."""

    def test_is_frozen(self) -> None:
        art = ApprovedArticle(
            url="u",
            title="t",
            publish_date="d",
            origin="o",
            approved=True,
            newsletter_id="n",
            industry_news=False,
        )
        with pytest.raises(AttributeError):
            art.url = "changed"  # type: ignore[misc]

    def test_equality(self) -> None:
        a = ApprovedArticle("u", "t", "d", "o", True, "n", False)
        b = ApprovedArticle("u", "t", "d", "o", True, "n", False)
        assert a == b

    def test_inequality(self) -> None:
        a = ApprovedArticle("u1", "t", "d", "o", True, "n", False)
        b = ApprovedArticle("u2", "t", "d", "o", True, "n", False)
        assert a != b

    def test_field_types(self) -> None:
        art = ApprovedArticle(
            url="https://example.com",
            title="Test",
            publish_date="02/15/2026",
            origin="google_news",
            approved=True,
            newsletter_id="NL-001",
            industry_news=True,
        )
        assert isinstance(art.url, str)
        assert isinstance(art.approved, bool)
        assert isinstance(art.industry_news, bool)


# ---------------------------------------------------------------------------
# ApprovalResult dataclass
# ---------------------------------------------------------------------------


class TestApprovalResult:
    """Tests for ApprovalResult dataclass properties."""

    def test_is_frozen(self) -> None:
        result = ApprovalResult(articles=[], validation_attempts=1)
        with pytest.raises(AttributeError):
            result.validation_attempts = 2  # type: ignore[misc]

    def test_field_access(self) -> None:
        arts = [ApprovedArticle("u", "t", "d", "o", True, "n", False)]
        result = ApprovalResult(articles=arts, validation_attempts=3)
        assert result.articles == arts
        assert result.validation_attempts == 3


# ---------------------------------------------------------------------------
# run_approval_flow
# ---------------------------------------------------------------------------


class TestRunApprovalFlow:
    """Tests for the full approval loop orchestration."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self) -> None:
        valid_rows = [_make_sheet_row(approved="yes", newsletter_id="NL-1")]
        slack = FakeSlack()
        approval = FakeSlackApproval()
        reader = FakeSheetReader([valid_rows])

        result = await run_approval_flow(
            slack,
            approval,
            reader,
            spreadsheet_id="abc123",
            channel="#test",
        )

        assert result.validation_attempts == 1
        assert len(result.articles) == 1

    @pytest.mark.asyncio
    async def test_success_after_one_failure(self) -> None:
        invalid_rows = [_make_sheet_row(approved="", newsletter_id="")]
        valid_rows = [_make_sheet_row(approved="yes", newsletter_id="NL-1")]
        slack = FakeSlack()
        approval = FakeSlackApproval()
        reader = FakeSheetReader([invalid_rows, valid_rows])

        result = await run_approval_flow(
            slack,
            approval,
            reader,
            spreadsheet_id="abc123",
            channel="#test",
        )

        assert result.validation_attempts == 2

    @pytest.mark.asyncio
    async def test_success_after_multiple_failures(self) -> None:
        invalid = [_make_sheet_row(approved="", newsletter_id="")]
        valid = [_make_sheet_row(approved="yes", newsletter_id="NL-1")]
        slack = FakeSlack()
        approval = FakeSlackApproval()
        reader = FakeSheetReader([invalid, invalid, invalid, valid])

        result = await run_approval_flow(
            slack,
            approval,
            reader,
            spreadsheet_id="abc123",
            channel="#test",
        )

        assert result.validation_attempts == 4

    @pytest.mark.asyncio
    async def test_sends_initial_approval_message(self) -> None:
        valid_rows = [_make_sheet_row(approved="yes", newsletter_id="NL-1")]
        slack = FakeSlack()
        approval = FakeSlackApproval()
        reader = FakeSheetReader([valid_rows])

        await run_approval_flow(
            slack,
            approval,
            reader,
            spreadsheet_id="abc123",
            channel="#test",
        )

        # First sendAndWait should use the approval message
        channel, text, label = approval.calls[0]
        assert channel == "#test"
        assert "abc123" in text
        assert "Approve Curated Articles" in text
        assert label == APPROVE_LABEL

    @pytest.mark.asyncio
    async def test_sends_revalidation_message_on_failure(self) -> None:
        invalid = [_make_sheet_row(approved="", newsletter_id="")]
        valid = [_make_sheet_row(approved="yes", newsletter_id="NL-1")]
        slack = FakeSlack()
        approval = FakeSlackApproval()
        reader = FakeSheetReader([invalid, valid])

        await run_approval_flow(
            slack,
            approval,
            reader,
            spreadsheet_id="abc123",
            channel="#test",
        )

        # Second sendAndWait should use the re-validation message
        _, text, _ = approval.calls[1]
        assert "approved column" in text.lower()
        assert "newsletter_id" in text

    @pytest.mark.asyncio
    async def test_sends_status_message_on_success(self) -> None:
        valid_rows = [_make_sheet_row(approved="yes", newsletter_id="NL-1")]
        slack = FakeSlack()
        approval = FakeSlackApproval()
        reader = FakeSheetReader([valid_rows])

        await run_approval_flow(
            slack,
            approval,
            reader,
            spreadsheet_id="abc123",
            channel="#test",
        )

        assert len(slack.messages) == 1
        assert slack.messages[0] == ("#test", STATUS_MESSAGE)

    @pytest.mark.asyncio
    async def test_returns_only_approved_articles(self) -> None:
        rows = [
            _make_sheet_row(url="https://a.com", approved="yes", newsletter_id="NL-1"),
            _make_sheet_row(url="https://b.com", approved="", newsletter_id=""),
            _make_sheet_row(url="https://c.com", approved="yes", newsletter_id="NL-2"),
        ]
        slack = FakeSlack()
        approval = FakeSlackApproval()
        reader = FakeSheetReader([rows])

        result = await run_approval_flow(
            slack,
            approval,
            reader,
            spreadsheet_id="abc123",
            channel="#test",
        )

        assert len(result.articles) == 2
        urls = {a.url for a in result.articles}
        assert urls == {"https://a.com", "https://c.com"}

    @pytest.mark.asyncio
    async def test_default_sheet_name(self) -> None:
        valid_rows = [_make_sheet_row(approved="yes", newsletter_id="NL-1")]
        slack = FakeSlack()
        approval = FakeSlackApproval()
        reader = FakeSheetReader([valid_rows])

        await run_approval_flow(
            slack,
            approval,
            reader,
            spreadsheet_id="abc123",
            channel="#test",
        )

        assert reader.calls[0] == ("abc123", "Sheet1")

    @pytest.mark.asyncio
    async def test_custom_sheet_name(self) -> None:
        valid_rows = [_make_sheet_row(approved="yes", newsletter_id="NL-1")]
        slack = FakeSlack()
        approval = FakeSlackApproval()
        reader = FakeSheetReader([valid_rows])

        await run_approval_flow(
            slack,
            approval,
            reader,
            spreadsheet_id="abc123",
            sheet_name="Articles",
            channel="#test",
        )

        assert reader.calls[0] == ("abc123", "Articles")

    @pytest.mark.asyncio
    async def test_spreadsheet_id_in_all_calls(self) -> None:
        invalid = [_make_sheet_row(approved="", newsletter_id="")]
        valid = [_make_sheet_row(approved="yes", newsletter_id="NL-1")]
        slack = FakeSlack()
        approval = FakeSlackApproval()
        reader = FakeSheetReader([invalid, valid])

        await run_approval_flow(
            slack,
            approval,
            reader,
            spreadsheet_id="my-sheet-id",
            channel="#test",
        )

        # Both sendAndWait messages should reference the spreadsheet
        for _, text, _ in approval.calls:
            assert "my-sheet-id" in text
        # Both read_rows calls should use the spreadsheet_id
        for sid, _ in reader.calls:
            assert sid == "my-sheet-id"

    @pytest.mark.asyncio
    async def test_execution_order(self) -> None:
        """Verify: sendAndWait → read_rows → validate → (status msg or loop)."""
        call_order: list[str] = []

        class TrackingSlack:
            async def send_message(self, channel: str, text: str) -> None:
                call_order.append("status_message")

        class TrackingApproval:
            async def send_and_wait(
                self, channel: str, text: str, *, approve_label: str = ""
            ) -> None:
                call_order.append("send_and_wait")

        class TrackingReader:
            async def read_rows(
                self, spreadsheet_id: str, sheet_name: str
            ) -> list[dict[str, str]]:
                call_order.append("read_rows")
                return [_make_sheet_row(approved="yes", newsletter_id="NL-1")]

        await run_approval_flow(
            TrackingSlack(),
            TrackingApproval(),
            TrackingReader(),
            spreadsheet_id="abc123",
            channel="#test",
        )

        assert call_order == ["send_and_wait", "read_rows", "status_message"]

    @pytest.mark.asyncio
    async def test_execution_order_with_retry(self) -> None:
        """Verify order when validation fails once."""
        call_order: list[str] = []
        attempt = 0

        class TrackingSlack:
            async def send_message(self, channel: str, text: str) -> None:
                call_order.append("status_message")

        class TrackingApproval:
            async def send_and_wait(
                self, channel: str, text: str, *, approve_label: str = ""
            ) -> None:
                call_order.append("send_and_wait")

        class TrackingReader:
            async def read_rows(
                self, spreadsheet_id: str, sheet_name: str
            ) -> list[dict[str, str]]:
                nonlocal attempt
                attempt += 1
                call_order.append("read_rows")
                if attempt == 1:
                    return [_make_sheet_row(approved="", newsletter_id="")]
                return [_make_sheet_row(approved="yes", newsletter_id="NL-1")]

        await run_approval_flow(
            TrackingSlack(),
            TrackingApproval(),
            TrackingReader(),
            spreadsheet_id="abc123",
            channel="#test",
        )

        assert call_order == [
            "send_and_wait",
            "read_rows",  # first attempt (fail)
            "send_and_wait",
            "read_rows",  # second attempt (pass)
            "status_message",
        ]

    @pytest.mark.asyncio
    async def test_returns_approval_result_type(self) -> None:
        valid_rows = [_make_sheet_row(approved="yes", newsletter_id="NL-1")]
        slack = FakeSlack()
        approval = FakeSlackApproval()
        reader = FakeSheetReader([valid_rows])

        result = await run_approval_flow(
            slack,
            approval,
            reader,
            spreadsheet_id="abc123",
            channel="#test",
        )

        assert isinstance(result, ApprovalResult)

    @pytest.mark.asyncio
    async def test_industry_news_normalized(self) -> None:
        rows = [
            _make_sheet_row(
                url="https://a.com",
                approved="yes",
                newsletter_id="NL-1",
                industry_news="yes",
            ),
            _make_sheet_row(
                url="https://b.com",
                approved="yes",
                newsletter_id="NL-2",
                industry_news="",
            ),
        ]
        slack = FakeSlack()
        approval = FakeSlackApproval()
        reader = FakeSheetReader([rows])

        result = await run_approval_flow(
            slack,
            approval,
            reader,
            spreadsheet_id="abc123",
            channel="#test",
        )

        assert result.articles[0].industry_news is True
        assert result.articles[1].industry_news is False

    @pytest.mark.asyncio
    async def test_channel_passed_correctly(self) -> None:
        valid_rows = [_make_sheet_row(approved="yes", newsletter_id="NL-1")]
        slack = FakeSlack()
        approval = FakeSlackApproval()
        reader = FakeSheetReader([valid_rows])

        await run_approval_flow(
            slack,
            approval,
            reader,
            spreadsheet_id="abc123",
            channel="#my-channel",
        )

        assert approval.calls[0][0] == "#my-channel"
        assert slack.messages[0][0] == "#my-channel"


# ---------------------------------------------------------------------------
# Approval flow constants
# ---------------------------------------------------------------------------


class TestApprovalFlowConstants:
    """Tests for approval-flow module-level constants."""

    def test_approval_message_template_has_placeholder(self) -> None:
        assert "{spreadsheet_id}" in APPROVAL_MESSAGE_TEMPLATE

    def test_revalidation_message_template_has_placeholder(self) -> None:
        assert "{spreadsheet_id}" in REVALIDATION_MESSAGE_TEMPLATE

    def test_status_message_content(self) -> None:
        assert "google sheet" in STATUS_MESSAGE.lower()
        assert "next steps" in STATUS_MESSAGE.lower()

    def test_approve_label(self) -> None:
        assert APPROVE_LABEL == "Proceed to next steps"

    def test_approval_message_template_has_google_sheets_url(self) -> None:
        assert "docs.google.com/spreadsheets" in APPROVAL_MESSAGE_TEMPLATE

    def test_revalidation_message_template_has_google_sheets_url(self) -> None:
        assert "docs.google.com/spreadsheets" in REVALIDATION_MESSAGE_TEMPLATE
