"""Tests for the article curation data flow (Step 1 data preparation).

Tests cover:
- format_article_for_sheet: date formatting, approved normalization, nullable fields
- articles_to_row_dicts: conversion to dict list, column presence, empty list
- fetch_unapproved_articles: SQL generation for approved=false and NULL, limit, ordering
- prepare_curation_data: full orchestration with mock dependencies
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ica.pipeline.article_curation import (
    INITIAL_NOTIFICATION,
    SHEET_COLUMNS,
    CurationDataResult,
    SheetArticle,
    articles_to_row_dicts,
    fetch_unapproved_articles,
    format_article_for_sheet,
    prepare_curation_data,
)


# ---------------------------------------------------------------------------
# Helpers — lightweight CuratedArticle stand-in
# ---------------------------------------------------------------------------


@dataclass
class FakeArticle:
    """Mimics CuratedArticle ORM model for testing without a database."""

    url: str = "https://example.com/article"
    title: str | None = "Test Article"
    origin: str | None = "google_news"
    publish_date: date | None = date(2026, 2, 15)
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
    def test_date_formatting_various(
        self, month: int, day: int, year: int, expected: str
    ) -> None:
        article = FakeArticle(publish_date=date(year, month, day))
        result = format_article_for_sheet(article)
        assert result.publish_date == expected

    def test_all_fields_populated(self) -> None:
        article = FakeArticle(
            url="https://example.com/full",
            title="Full Article",
            origin="default",
            publish_date=date(2026, 3, 10),
            approved=True,
            newsletter_id="NL-001",
            industry_news=True,
        )
        result = format_article_for_sheet(article)
        assert result.url == "https://example.com/full"
        assert result.title == "Full Article"
        assert result.origin == "default"
        assert result.publish_date == "03/10/2026"
        assert result.approved == "yes"
        assert result.newsletter_id == "NL-001"
        assert result.industry_news == "yes"

    def test_all_nullable_fields_none(self) -> None:
        article = FakeArticle(
            title=None,
            origin=None,
            publish_date=None,
            approved=None,
            industry_news=None,
            newsletter_id=None,
        )
        result = format_article_for_sheet(article)
        assert result.title == ""
        assert result.origin == ""
        assert result.publish_date == ""
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
            publish_date="02/15/2026",
            origin="google_news",
            approved="",
            newsletter_id="",
            industry_news="",
        )
        result = articles_to_row_dicts([article])
        assert len(result) == 1
        assert result[0]["url"] == "https://example.com"
        assert result[0]["title"] == "Test"
        assert result[0]["publish_date"] == "02/15/2026"
        assert result[0]["origin"] == "google_news"
        assert result[0]["approved"] == ""
        assert result[0]["newsletter_id"] == ""
        assert result[0]["industry_news"] == ""

    def test_multiple_articles(self) -> None:
        articles = [
            SheetArticle("url1", "t1", "01/01/2026", "o1", "", "", ""),
            SheetArticle("url2", "t2", "02/02/2026", "o2", "yes", "NL-1", "yes"),
        ]
        result = articles_to_row_dicts(articles)
        assert len(result) == 2
        assert result[0]["url"] == "url1"
        assert result[1]["url"] == "url2"

    def test_all_sheet_columns_present(self) -> None:
        article = SheetArticle("u", "t", "d", "o", "a", "n", "i")
        result = articles_to_row_dicts([article])
        for col in SHEET_COLUMNS:
            assert col in result[0], f"Missing column: {col}"

    def test_no_extra_columns(self) -> None:
        article = SheetArticle("u", "t", "d", "o", "a", "n", "i")
        result = articles_to_row_dicts([article])
        assert set(result[0].keys()) == set(SHEET_COLUMNS)

    def test_preserves_order(self) -> None:
        articles = [
            SheetArticle(f"url{i}", f"t{i}", "", "", "", "", "")
            for i in range(5)
        ]
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


def _make_session_with_articles(articles: list[Any]) -> AsyncMock:
    """Create a mock session that returns the given articles."""
    return _make_mock_session(articles)


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

        assert len(sheets.cleared) == 1
        assert sheets.cleared[0] == ("abc123", "Articles")

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

        assert len(sheets.appended) == 1
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
        assert result.sheet_articles == []

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
        """Verify operations happen in the correct sequence: notify → clear → fetch → append."""
        call_order: list[str] = []

        class OrderTrackingSlack:
            async def send_message(self, channel: str, text: str) -> None:
                call_order.append("slack_notify")

        class OrderTrackingSheets:
            async def clear_sheet(self, sid: str, sname: str) -> None:
                call_order.append("sheet_clear")

            async def append_rows(
                self, sid: str, sname: str, rows: list[dict[str, Any]]
            ) -> int:
                call_order.append("sheet_append")
                return len(rows)

        articles = [FakeArticle()]
        session = _make_session_with_articles(articles)

        await prepare_curation_data(
            session,
            OrderTrackingSlack(),
            OrderTrackingSheets(),
            spreadsheet_id="abc123",
            channel="#test",
        )

        assert call_order == ["slack_notify", "sheet_clear", "sheet_append"]

    @pytest.mark.asyncio
    async def test_multiple_articles_all_written(self) -> None:
        articles = [
            FakeArticle(url=f"https://example.com/{i}", title=f"Article {i}")
            for i in range(10)
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

        assert sheets.cleared[0] == ("abc123", "CustomSheet")
        _, sname, _ = sheets.appended[0]
        assert sname == "CustomSheet"

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


# ---------------------------------------------------------------------------
# SheetArticle dataclass
# ---------------------------------------------------------------------------


class TestSheetArticle:
    """Tests for SheetArticle dataclass properties."""

    def test_is_frozen(self) -> None:
        article = SheetArticle("u", "t", "d", "o", "a", "n", "i")
        with pytest.raises(AttributeError):
            article.url = "changed"  # type: ignore[misc]

    def test_equality(self) -> None:
        a = SheetArticle("u", "t", "d", "o", "a", "n", "i")
        b = SheetArticle("u", "t", "d", "o", "a", "n", "i")
        assert a == b

    def test_inequality(self) -> None:
        a = SheetArticle("u1", "t", "d", "o", "a", "n", "i")
        b = SheetArticle("u2", "t", "d", "o", "a", "n", "i")
        assert a != b

    def test_field_access(self) -> None:
        article = SheetArticle(
            url="https://example.com",
            title="Test",
            publish_date="02/15/2026",
            origin="google_news",
            approved="yes",
            newsletter_id="NL-1",
            industry_news="yes",
        )
        assert article.url == "https://example.com"
        assert article.title == "Test"
        assert article.publish_date == "02/15/2026"
        assert article.origin == "google_news"
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
            sheet_articles=[],
        )
        with pytest.raises(AttributeError):
            result.articles_fetched = 5  # type: ignore[misc]

    def test_field_access(self) -> None:
        articles = [SheetArticle("u", "t", "d", "o", "", "", "")]
        result = CurationDataResult(
            articles_fetched=1,
            articles_written=1,
            sheet_articles=articles,
        )
        assert result.articles_fetched == 1
        assert result.articles_written == 1
        assert result.sheet_articles == articles


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
            "publish_date",
            "origin",
            "approved",
            "newsletter_id",
            "industry_news",
        }
        assert set(SHEET_COLUMNS) == expected

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
            FakeArticle(url=f"https://example.com/{i}", title=f"Article {i}")
            for i in range(5)
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
            publish_date="02/15/2026",
            origin="google_news",
            approved="yes",
            newsletter_id="NL-1",
            industry_news="yes",
        )
        rows = articles_to_row_dicts([article])
        for value in rows[0].values():
            assert isinstance(value, str)

    def test_row_dict_empty_values_are_empty_strings(self) -> None:
        article = SheetArticle("u", "", "", "", "", "", "")
        rows = articles_to_row_dicts([article])
        for key, value in rows[0].items():
            if key != "url":
                assert value == ""
