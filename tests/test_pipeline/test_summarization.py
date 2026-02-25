"""Tests for summarization data preparation (Step 2, first half).

Tests cover:
- filter_approved_rows: filtering sheet rows by approved=yes
- normalize_article_row: field type normalization (booleans, dates)
- upsert_curated_articles: SQL upsert construction with type='curated'
- prepare_summarization_data: full orchestration with mock dependencies
- CuratedArticle / SummarizationPrepResult: dataclass properties
- parse_date_mmddyyyy: MM/DD/YYYY string to date conversion
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ica.pipeline.summarization import (
    CuratedArticle,
    SummarizationPrepResult,
    filter_approved_rows,
    normalize_article_row,
    upsert_curated_articles,
    prepare_summarization_data,
)
from ica.utils.date_parser import parse_date_mmddyyyy


# ---------------------------------------------------------------------------
# Helpers — fake sheet data
# ---------------------------------------------------------------------------


def _make_row(
    *,
    url: str = "https://example.com/article",
    title: str = "Test Article",
    publish_date: str = "02/15/2026",
    origin: str = "google_news",
    approved: str = "yes",
    newsletter_id: str = "NL-001",
    industry_news: str = "",
) -> dict[str, str]:
    """Build a Google Sheet row dict with defaults."""
    return {
        "url": url,
        "title": title,
        "publish_date": publish_date,
        "origin": origin,
        "approved": approved,
        "newsletter_id": newsletter_id,
        "industry_news": industry_news,
    }


class FakeSheetReader:
    """Records Google Sheets read calls and returns preset data."""

    def __init__(self, rows: list[dict[str, str]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, str]] = []

    async def read_rows(self, spreadsheet_id: str, sheet_name: str) -> list[dict[str, str]]:
        self.calls.append((spreadsheet_id, sheet_name))
        return self.rows


# ===================================================================
# parse_date_mmddyyyy
# ===================================================================


class TestParseDateMmddyyyy:
    """Tests for the MM/DD/YYYY date parser."""

    def test_valid_date(self) -> None:
        assert parse_date_mmddyyyy("02/15/2026") == date(2026, 2, 15)

    def test_leading_zeros(self) -> None:
        assert parse_date_mmddyyyy("01/01/2026") == date(2026, 1, 1)

    def test_december(self) -> None:
        assert parse_date_mmddyyyy("12/31/2025") == date(2025, 12, 31)

    def test_none_returns_none(self) -> None:
        assert parse_date_mmddyyyy(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert parse_date_mmddyyyy("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert parse_date_mmddyyyy("   ") is None

    def test_invalid_format_returns_none(self) -> None:
        assert parse_date_mmddyyyy("2026-02-15") is None

    def test_malformed_returns_none(self) -> None:
        assert parse_date_mmddyyyy("not-a-date") is None

    def test_whitespace_trimmed(self) -> None:
        assert parse_date_mmddyyyy("  02/15/2026  ") == date(2026, 2, 15)

    def test_non_string_returns_none(self) -> None:
        assert parse_date_mmddyyyy(12345) is None  # type: ignore[arg-type]

    def test_february_29_leap_year(self) -> None:
        assert parse_date_mmddyyyy("02/29/2024") == date(2024, 2, 29)

    def test_february_29_non_leap_returns_none(self) -> None:
        assert parse_date_mmddyyyy("02/29/2025") is None

    def test_month_13_returns_none(self) -> None:
        assert parse_date_mmddyyyy("13/01/2026") is None

    def test_day_32_returns_none(self) -> None:
        assert parse_date_mmddyyyy("01/32/2026") is None

    def test_roundtrip_with_format(self) -> None:
        """parse_date_mmddyyyy reverses format_date_mmddyyyy."""
        from ica.utils.date_parser import format_date_mmddyyyy

        d = date(2026, 6, 15)
        assert parse_date_mmddyyyy(format_date_mmddyyyy(d)) == d


# ===================================================================
# filter_approved_rows
# ===================================================================


class TestFilterApprovedRows:
    """Tests for filtering Google Sheet rows by approved status."""

    def test_filters_approved_yes(self) -> None:
        rows = [
            _make_row(url="https://a.com", approved="yes"),
            _make_row(url="https://b.com", approved="no"),
            _make_row(url="https://c.com", approved="yes"),
        ]
        result = filter_approved_rows(rows)
        assert len(result) == 2
        assert result[0]["url"] == "https://a.com"
        assert result[1]["url"] == "https://c.com"

    def test_case_insensitive(self) -> None:
        rows = [
            _make_row(approved="Yes"),
            _make_row(approved="YES"),
            _make_row(approved="yEs"),
        ]
        assert len(filter_approved_rows(rows)) == 3

    def test_empty_approved(self) -> None:
        rows = [_make_row(approved="")]
        assert filter_approved_rows(rows) == []

    def test_approved_missing_key(self) -> None:
        rows = [{"url": "https://a.com", "title": "Test"}]
        assert filter_approved_rows(rows) == []

    def test_false_string(self) -> None:
        rows = [_make_row(approved="false")]
        assert filter_approved_rows(rows) == []

    def test_true_string(self) -> None:
        """'true' is NOT 'yes', so it should be filtered out."""
        rows = [_make_row(approved="true")]
        assert filter_approved_rows(rows) == []

    def test_whitespace_trimmed(self) -> None:
        rows = [_make_row(approved="  yes  ")]
        assert len(filter_approved_rows(rows)) == 1

    def test_empty_list(self) -> None:
        assert filter_approved_rows([]) == []

    def test_all_approved(self) -> None:
        rows = [_make_row(url=f"https://{i}.com", approved="yes") for i in range(5)]
        assert len(filter_approved_rows(rows)) == 5

    def test_none_approved(self) -> None:
        rows = [
            _make_row(approved="no"),
            _make_row(approved=""),
            _make_row(approved="false"),
        ]
        assert filter_approved_rows(rows) == []


# ===================================================================
# normalize_article_row
# ===================================================================


class TestNormalizeArticleRow:
    """Tests for converting a sheet row to a CuratedArticle."""

    def test_basic_normalization(self) -> None:
        row = _make_row()
        article = normalize_article_row(row)
        assert article.url == "https://example.com/article"
        assert article.title == "Test Article"
        assert article.publish_date == date(2026, 2, 15)
        assert article.origin == "google_news"
        assert article.approved is True
        assert article.newsletter_id == "NL-001"
        assert article.industry_news is False

    def test_approved_yes_to_true(self) -> None:
        row = _make_row(approved="yes")
        assert normalize_article_row(row).approved is True

    def test_approved_no_to_false(self) -> None:
        row = _make_row(approved="no")
        assert normalize_article_row(row).approved is False

    def test_approved_empty_to_false(self) -> None:
        row = _make_row(approved="")
        assert normalize_article_row(row).approved is False

    def test_industry_news_yes(self) -> None:
        row = _make_row(industry_news="yes")
        assert normalize_article_row(row).industry_news is True

    def test_industry_news_empty(self) -> None:
        row = _make_row(industry_news="")
        assert normalize_article_row(row).industry_news is False

    def test_industry_news_no(self) -> None:
        row = _make_row(industry_news="no")
        assert normalize_article_row(row).industry_news is False

    def test_industry_news_case_insensitive(self) -> None:
        row = _make_row(industry_news="YES")
        assert normalize_article_row(row).industry_news is True

    def test_publish_date_valid(self) -> None:
        row = _make_row(publish_date="12/25/2025")
        assert normalize_article_row(row).publish_date == date(2025, 12, 25)

    def test_publish_date_empty(self) -> None:
        row = _make_row(publish_date="")
        assert normalize_article_row(row).publish_date is None

    def test_publish_date_invalid(self) -> None:
        row = _make_row(publish_date="not-a-date")
        assert normalize_article_row(row).publish_date is None

    def test_missing_keys_default_to_empty(self) -> None:
        article = normalize_article_row({})
        assert article.url == ""
        assert article.title == ""
        assert article.publish_date is None
        assert article.origin == ""
        assert article.approved is False
        assert article.newsletter_id == ""
        assert article.industry_news is False

    def test_returns_frozen_dataclass(self) -> None:
        row = _make_row()
        article = normalize_article_row(row)
        with pytest.raises(AttributeError):
            article.url = "changed"  # type: ignore[misc]


# ===================================================================
# CuratedArticle dataclass
# ===================================================================


class TestCuratedArticle:
    """Tests for the CuratedArticle frozen dataclass."""

    def test_frozen(self) -> None:
        article = CuratedArticle(
            url="https://a.com",
            title="Title",
            publish_date=date(2026, 1, 1),
            origin="google_news",
            approved=True,
            newsletter_id="NL-001",
            industry_news=False,
        )
        with pytest.raises(AttributeError):
            article.title = "changed"  # type: ignore[misc]

    def test_equality(self) -> None:
        kwargs = dict(
            url="https://a.com",
            title="Title",
            publish_date=date(2026, 1, 1),
            origin="google_news",
            approved=True,
            newsletter_id="NL-001",
            industry_news=False,
        )
        assert CuratedArticle(**kwargs) == CuratedArticle(**kwargs)

    def test_publish_date_none(self) -> None:
        article = CuratedArticle(
            url="https://a.com",
            title="Title",
            publish_date=None,
            origin="google_news",
            approved=True,
            newsletter_id="NL-001",
            industry_news=False,
        )
        assert article.publish_date is None


# ===================================================================
# SummarizationPrepResult dataclass
# ===================================================================


class TestSummarizationPrepResult:
    """Tests for the SummarizationPrepResult frozen dataclass."""

    def test_frozen(self) -> None:
        result = SummarizationPrepResult(articles=[], rows_upserted=0, model="test-model")
        with pytest.raises(AttributeError):
            result.model = "changed"  # type: ignore[misc]

    def test_fields(self) -> None:
        articles = [
            CuratedArticle(
                url="https://a.com",
                title="A",
                publish_date=date(2026, 1, 1),
                origin="google_news",
                approved=True,
                newsletter_id="NL-001",
                industry_news=False,
            )
        ]
        result = SummarizationPrepResult(
            articles=articles, rows_upserted=1, model="anthropic/claude-sonnet-4.5"
        )
        assert len(result.articles) == 1
        assert result.rows_upserted == 1
        assert result.model == "anthropic/claude-sonnet-4.5"


# ===================================================================
# upsert_curated_articles
# ===================================================================


class TestUpsertCuratedArticles:
    """Tests for the curated article upsert (mocked session)."""

    @pytest.mark.asyncio
    async def test_empty_list_returns_zero(self) -> None:
        session = AsyncMock()
        result = await upsert_curated_articles(session, [])
        assert result == 0
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_article(self) -> None:
        session = AsyncMock()
        session.execute.return_value = MagicMock(rowcount=1)

        articles = [
            CuratedArticle(
                url="https://a.com",
                title="Title A",
                publish_date=date(2026, 2, 15),
                origin="google_news",
                approved=True,
                newsletter_id="NL-001",
                industry_news=False,
            )
        ]
        result = await upsert_curated_articles(session, articles)
        assert result == 1
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_articles(self) -> None:
        session = AsyncMock()
        session.execute.return_value = MagicMock(rowcount=3)

        articles = [
            CuratedArticle(
                url=f"https://{i}.com",
                title=f"Title {i}",
                publish_date=date(2026, 2, i + 1),
                origin="google_news",
                approved=True,
                newsletter_id="NL-001",
                industry_news=i == 1,
            )
            for i in range(3)
        ]
        result = await upsert_curated_articles(session, articles)
        assert result == 3

    @pytest.mark.asyncio
    async def test_does_not_commit(self) -> None:
        """Caller manages the transaction, not the upsert function."""
        session = AsyncMock()
        session.execute.return_value = MagicMock(rowcount=1)

        articles = [
            CuratedArticle(
                url="https://a.com",
                title="Title",
                publish_date=None,
                origin="default",
                approved=True,
                newsletter_id="NL-001",
                industry_news=True,
            )
        ]
        await upsert_curated_articles(session, articles)
        session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_null_publish_date(self) -> None:
        """Articles with publish_date=None should still upsert."""
        session = AsyncMock()
        session.execute.return_value = MagicMock(rowcount=1)

        articles = [
            CuratedArticle(
                url="https://a.com",
                title="Title",
                publish_date=None,
                origin="default",
                approved=True,
                newsletter_id="NL-001",
                industry_news=False,
            )
        ]
        result = await upsert_curated_articles(session, articles)
        assert result == 1

    @pytest.mark.asyncio
    async def test_sql_statement_uses_article_table(self) -> None:
        """Verify the upsert targets the Article model."""
        session = AsyncMock()
        session.execute.return_value = MagicMock(rowcount=1)

        articles = [
            CuratedArticle(
                url="https://a.com",
                title="Title",
                publish_date=date(2026, 1, 1),
                origin="google_news",
                approved=True,
                newsletter_id="NL-001",
                industry_news=False,
            )
        ]
        await upsert_curated_articles(session, articles)

        # Extract the SQL statement passed to execute
        call_args = session.execute.call_args
        stmt = call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "articles" in compiled.lower()

    @pytest.mark.asyncio
    async def test_sql_sets_type_curated(self) -> None:
        """Verify the upsert sets type='curated'."""
        session = AsyncMock()
        session.execute.return_value = MagicMock(rowcount=1)

        articles = [
            CuratedArticle(
                url="https://a.com",
                title="Title",
                publish_date=date(2026, 1, 1),
                origin="google_news",
                approved=True,
                newsletter_id="NL-001",
                industry_news=False,
            )
        ]
        await upsert_curated_articles(session, articles)

        call_args = session.execute.call_args
        stmt = call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "'curated'" in compiled


# ===================================================================
# prepare_summarization_data — orchestrator
# ===================================================================


class TestPrepareSummarizationData:
    """Tests for the full orchestration function."""

    @pytest.mark.asyncio
    async def test_basic_flow(self) -> None:
        """Happy path: fetch sheet → filter → normalize → upsert."""
        rows = [
            _make_row(url="https://a.com", approved="yes"),
            _make_row(url="https://b.com", approved="no"),
            _make_row(url="https://c.com", approved="yes", industry_news="yes"),
        ]
        sheets = FakeSheetReader(rows)
        session = AsyncMock()
        session.execute.return_value = MagicMock(rowcount=2)

        with patch(
            "ica.pipeline.summarization.get_model",
            return_value="anthropic/claude-sonnet-4.5",
        ):
            result = await prepare_summarization_data(
                session,
                sheets,
                spreadsheet_id="SHEET_ID",
                sheet_name="Sheet1",
            )

        assert len(result.articles) == 2
        assert result.rows_upserted == 2
        assert result.model == "anthropic/claude-sonnet-4.5"

    @pytest.mark.asyncio
    async def test_filters_non_approved(self) -> None:
        """Only approved=yes rows are included."""
        rows = [
            _make_row(url="https://a.com", approved="no"),
            _make_row(url="https://b.com", approved=""),
            _make_row(url="https://c.com", approved="false"),
        ]
        sheets = FakeSheetReader(rows)
        session = AsyncMock()
        session.execute.return_value = MagicMock(rowcount=0)

        with patch(
            "ica.pipeline.summarization.get_model",
            return_value="test-model",
        ):
            result = await prepare_summarization_data(
                session,
                sheets,
                spreadsheet_id="SHEET_ID",
            )

        assert result.articles == []
        assert result.rows_upserted == 0

    @pytest.mark.asyncio
    async def test_normalizes_booleans(self) -> None:
        """approved and industry_news are normalized from strings."""
        rows = [
            _make_row(approved="YES", industry_news="Yes"),
        ]
        sheets = FakeSheetReader(rows)
        session = AsyncMock()
        session.execute.return_value = MagicMock(rowcount=1)

        with patch(
            "ica.pipeline.summarization.get_model",
            return_value="test-model",
        ):
            result = await prepare_summarization_data(
                session,
                sheets,
                spreadsheet_id="SHEET_ID",
            )

        article = result.articles[0]
        assert article.approved is True
        assert article.industry_news is True

    @pytest.mark.asyncio
    async def test_parses_dates(self) -> None:
        """publish_date strings are parsed to date objects."""
        rows = [_make_row(publish_date="06/15/2026")]
        sheets = FakeSheetReader(rows)
        session = AsyncMock()
        session.execute.return_value = MagicMock(rowcount=1)

        with patch(
            "ica.pipeline.summarization.get_model",
            return_value="test-model",
        ):
            result = await prepare_summarization_data(
                session,
                sheets,
                spreadsheet_id="SHEET_ID",
            )

        assert result.articles[0].publish_date == date(2026, 6, 15)

    @pytest.mark.asyncio
    async def test_empty_sheet(self) -> None:
        """No rows in the sheet → empty result, no upsert."""
        sheets = FakeSheetReader([])
        session = AsyncMock()

        with patch(
            "ica.pipeline.summarization.get_model",
            return_value="test-model",
        ):
            result = await prepare_summarization_data(
                session,
                sheets,
                spreadsheet_id="SHEET_ID",
            )

        assert result.articles == []
        assert result.rows_upserted == 0
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_reads_correct_sheet(self) -> None:
        """Verify the correct spreadsheet_id and sheet_name are used."""
        sheets = FakeSheetReader([])
        session = AsyncMock()

        with patch(
            "ica.pipeline.summarization.get_model",
            return_value="test-model",
        ):
            await prepare_summarization_data(
                session,
                sheets,
                spreadsheet_id="MY_SHEET_ID",
                sheet_name="CustomSheet",
            )

        assert sheets.calls == [("MY_SHEET_ID", "CustomSheet")]

    @pytest.mark.asyncio
    async def test_default_sheet_name(self) -> None:
        """Default sheet_name is 'Sheet1'."""
        sheets = FakeSheetReader([])
        session = AsyncMock()

        with patch(
            "ica.pipeline.summarization.get_model",
            return_value="test-model",
        ):
            await prepare_summarization_data(
                session,
                sheets,
                spreadsheet_id="SHEET_ID",
            )

        assert sheets.calls == [("SHEET_ID", "Sheet1")]

    @pytest.mark.asyncio
    async def test_gets_model_for_summary(self) -> None:
        """The LLM model is fetched for the SUMMARY purpose."""
        sheets = FakeSheetReader([])
        session = AsyncMock()

        with patch(
            "ica.pipeline.summarization.get_model",
            return_value="custom/model-name",
        ) as mock_get_model:
            result = await prepare_summarization_data(
                session,
                sheets,
                spreadsheet_id="SHEET_ID",
            )

        from ica.config.llm_config import LLMPurpose

        mock_get_model.assert_called_once_with(LLMPurpose.SUMMARY)
        assert result.model == "custom/model-name"

    @pytest.mark.asyncio
    async def test_preserves_article_order(self) -> None:
        """Articles are returned in the same order as the sheet rows."""
        rows = [
            _make_row(url="https://first.com", approved="yes"),
            _make_row(url="https://second.com", approved="yes"),
            _make_row(url="https://third.com", approved="yes"),
        ]
        sheets = FakeSheetReader(rows)
        session = AsyncMock()
        session.execute.return_value = MagicMock(rowcount=3)

        with patch(
            "ica.pipeline.summarization.get_model",
            return_value="test-model",
        ):
            result = await prepare_summarization_data(
                session,
                sheets,
                spreadsheet_id="SHEET_ID",
            )

        urls = [a.url for a in result.articles]
        assert urls == [
            "https://first.com",
            "https://second.com",
            "https://third.com",
        ]

    @pytest.mark.asyncio
    async def test_mixed_approved_non_approved(self) -> None:
        """Only approved rows are processed, interleaved with non-approved."""
        rows = [
            _make_row(url="https://a.com", approved="yes"),
            _make_row(url="https://b.com", approved=""),
            _make_row(url="https://c.com", approved="yes"),
            _make_row(url="https://d.com", approved="no"),
            _make_row(url="https://e.com", approved="yes"),
        ]
        sheets = FakeSheetReader(rows)
        session = AsyncMock()
        session.execute.return_value = MagicMock(rowcount=3)

        with patch(
            "ica.pipeline.summarization.get_model",
            return_value="test-model",
        ):
            result = await prepare_summarization_data(
                session,
                sheets,
                spreadsheet_id="SHEET_ID",
            )

        assert len(result.articles) == 3
        assert [a.url for a in result.articles] == [
            "https://a.com",
            "https://c.com",
            "https://e.com",
        ]

    @pytest.mark.asyncio
    async def test_all_fields_normalized(self) -> None:
        """All fields of a complex article row are properly normalized."""
        rows = [
            _make_row(
                url="https://ai-news.com/breakthrough",
                title="AI Breakthrough Announced",
                publish_date="01/20/2026",
                origin="default",
                approved="Yes",
                newsletter_id="NL-042",
                industry_news="yes",
            ),
        ]
        sheets = FakeSheetReader(rows)
        session = AsyncMock()
        session.execute.return_value = MagicMock(rowcount=1)

        with patch(
            "ica.pipeline.summarization.get_model",
            return_value="test-model",
        ):
            result = await prepare_summarization_data(
                session,
                sheets,
                spreadsheet_id="SHEET_ID",
            )

        a = result.articles[0]
        assert a.url == "https://ai-news.com/breakthrough"
        assert a.title == "AI Breakthrough Announced"
        assert a.publish_date == date(2026, 1, 20)
        assert a.origin == "default"
        assert a.approved is True
        assert a.newsletter_id == "NL-042"
        assert a.industry_news is True


# ===================================================================
# Edge cases
# ===================================================================


class TestEdgeCases:
    """Edge cases for normalization and filtering."""

    def test_normalize_row_with_extra_keys(self) -> None:
        """Extra keys in the row dict are ignored."""
        row = _make_row()
        row["extra_field"] = "ignored"
        article = normalize_article_row(row)
        assert article.url == "https://example.com/article"

    def test_normalize_row_preserves_url_exactly(self) -> None:
        """URL is passed through as-is, no trimming."""
        row = _make_row(url="  https://a.com/path?q=1  ")
        article = normalize_article_row(row)
        assert article.url == "  https://a.com/path?q=1  "

    def test_filter_single_row_approved(self) -> None:
        rows = [_make_row(approved="yes")]
        assert len(filter_approved_rows(rows)) == 1

    def test_filter_preserves_all_fields(self) -> None:
        """Filtering doesn't alter the row contents."""
        row = _make_row(
            url="https://x.com",
            title="Special",
            approved="yes",
            industry_news="yes",
        )
        result = filter_approved_rows([row])
        assert result[0] == row

    def test_normalize_newsletter_id_empty(self) -> None:
        row = _make_row(newsletter_id="")
        assert normalize_article_row(row).newsletter_id == ""

    def test_normalize_origin_empty(self) -> None:
        row = _make_row(origin="")
        assert normalize_article_row(row).origin == ""

    @pytest.mark.asyncio
    async def test_upsert_with_empty_strings(self) -> None:
        """Articles with empty string fields should still upsert."""
        session = AsyncMock()
        session.execute.return_value = MagicMock(rowcount=1)

        articles = [
            CuratedArticle(
                url="https://a.com",
                title="",
                publish_date=None,
                origin="",
                approved=True,
                newsletter_id="",
                industry_news=False,
            )
        ]
        result = await upsert_curated_articles(session, articles)
        assert result == 1

    @pytest.mark.asyncio
    async def test_upsert_mixed_industry_news(self) -> None:
        """Upsert handles mix of industry_news True/False."""
        session = AsyncMock()
        session.execute.return_value = MagicMock(rowcount=2)

        articles = [
            CuratedArticle(
                url="https://a.com",
                title="Regular",
                publish_date=date(2026, 1, 1),
                origin="google_news",
                approved=True,
                newsletter_id="NL-001",
                industry_news=False,
            ),
            CuratedArticle(
                url="https://b.com",
                title="Industry",
                publish_date=date(2026, 1, 2),
                origin="default",
                approved=True,
                newsletter_id="NL-001",
                industry_news=True,
            ),
        ]
        result = await upsert_curated_articles(session, articles)
        assert result == 2
