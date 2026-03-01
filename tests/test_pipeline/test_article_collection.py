"""Tests for the article collection pipeline with Brave Search + relevance assessment.

Tests cover:
- ArticleRecord: frozen dataclass, default fields
- CollectionResult: default values, accepted/rejected counts
- deduplicate_results: URL dedup with excerpt preservation
- parse_articles: date parsing, excerpt handling
- collect_articles: full pipeline with BraveSearchClient mocks and
  relevance assessment integration
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from ica.pipeline.article_collection import (
    DAILY_KEYWORDS,
    EVERY_2_DAYS_KEYWORDS,
    ArticleRecord,
    CollectionResult,
    collect_articles,
    deduplicate_results,
    parse_articles,
)
from ica.pipeline.relevance_assessment import RelevanceResult
from ica.services.google_search import SearchResult

# ---------------------------------------------------------------------------
# Reference date for deterministic tests
# ---------------------------------------------------------------------------

REF_DATE = date(2026, 2, 28)


# ---------------------------------------------------------------------------
# Stub HTTP client for Brave Search API
# ---------------------------------------------------------------------------


@dataclass
class StubHttpClient:
    """Records requests and returns canned Brave API responses."""

    responses: dict[str, dict[str, Any]] = field(default_factory=dict)
    requests: list[dict[str, Any]] = field(default_factory=list)

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.requests.append({"url": url, "params": params, "headers": headers})
        keyword = params.get("q", "")
        return self.responses.get(keyword, {"web": {"results": []}})


# ---------------------------------------------------------------------------
# Stub article repository
# ---------------------------------------------------------------------------


@dataclass
class StubArticleRepository:
    """In-memory article store that mimics DB upsert behavior."""

    articles: dict[str, ArticleRecord] = field(default_factory=dict)
    upsert_calls: list[list[ArticleRecord]] = field(default_factory=list)

    async def upsert_articles(self, articles: list[ArticleRecord]) -> int:
        self.upsert_calls.append(articles)
        count = 0
        for a in articles:
            self.articles[a.url] = a
            count += 1
        return count


# ---------------------------------------------------------------------------
# Brave API response fixtures
# ---------------------------------------------------------------------------


def _brave_item(
    url: str,
    title: str = "Title",
    description: str = "Excerpt text",
    page_age: str | None = "3 days ago",
) -> dict[str, Any]:
    """Build a single Brave web.results[] entry."""
    item: dict[str, Any] = {
        "url": url,
        "title": title,
        "description": description,
    }
    if page_age is not None:
        item["page_age"] = page_age
    return item


def _brave_response(*items: dict[str, Any]) -> dict[str, Any]:
    return {"web": {"results": list(items)}}


def _build_daily_brave_responses() -> dict[str, dict[str, Any]]:
    return {
        "Artificial General Intelligence": _brave_response(
            _brave_item("https://example.com/agi", "AGI Breakthrough"),
            _brave_item("https://example.com/agi-safety", "AGI Safety"),
        ),
        "Automation": _brave_response(
            _brave_item("https://example.com/automation", "Automation Tools"),
            _brave_item("https://example.com/agi", "AGI Duplicate"),  # dup
        ),
        "Artificial Intelligence": _brave_response(
            _brave_item("https://example.com/ai-trends", "AI Trends"),
        ),
    }


def _build_every_2_days_brave_responses() -> dict[str, dict[str, Any]]:
    return {
        "AI breakthrough": _brave_response(
            _brave_item("https://example.com/ai-new", "New AI Model"),
        ),
        "AI latest": _brave_response(
            _brave_item("https://example.com/ai-latest", "Latest AI"),
        ),
        "AI tutorial": _brave_response(),
        "AI case study": _brave_response(),
        "AI research": _brave_response(),
    }


# ===========================================================================
# ArticleRecord dataclass
# ===========================================================================


class TestArticleRecord:
    """Tests for the ArticleRecord frozen dataclass."""

    def test_required_fields(self) -> None:
        record = ArticleRecord(
            url="https://a.com",
            title="Title",
            origin="daily",
            publish_date=REF_DATE,
        )
        assert record.url == "https://a.com"
        assert record.title == "Title"
        assert record.origin == "daily"
        assert record.publish_date == REF_DATE

    def test_optional_fields_default_to_none(self) -> None:
        record = ArticleRecord(
            url="https://a.com", title="T", origin="daily", publish_date=REF_DATE
        )
        assert record.excerpt is None
        assert record.relevance_status is None
        assert record.relevance_reason is None

    def test_is_frozen(self) -> None:
        record = ArticleRecord(
            url="https://a.com", title="T", origin="daily", publish_date=REF_DATE
        )
        with pytest.raises(AttributeError):
            record.title = "Changed"  # type: ignore[misc]

    def test_with_all_fields(self) -> None:
        record = ArticleRecord(
            url="https://a.com",
            title="Title",
            origin="daily",
            publish_date=REF_DATE,
            excerpt="Excerpt text",
            relevance_status="accept",
            relevance_reason="Relevant article",
        )
        assert record.excerpt == "Excerpt text"
        assert record.relevance_status == "accept"
        assert record.relevance_reason == "Relevant article"


# ===========================================================================
# CollectionResult dataclass
# ===========================================================================


class TestCollectionResult:
    """Tests for the CollectionResult dataclass."""

    def test_default_values(self) -> None:
        result = CollectionResult()
        assert result.raw_results == []
        assert result.deduplicated == []
        assert result.articles == []
        assert result.rows_affected == 0
        assert result.accepted_count == 0
        assert result.rejected_count == 0


# ===========================================================================
# deduplicate_results with excerpts
# ===========================================================================


class TestDeduplicateResultsWithExcerpts:
    """Verify deduplication preserves excerpt field."""

    def test_excerpt_preserved_after_dedup(self) -> None:
        results = [
            SearchResult(
                url="https://a.com", title="A", date=None, origin="daily",
                excerpt="First excerpt",
            ),
            SearchResult(
                url="https://a.com", title="A dup", date=None, origin="daily",
                excerpt="Second excerpt",
            ),
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 1
        assert deduped[0].excerpt == "First excerpt"

    def test_different_urls_keep_their_excerpts(self) -> None:
        results = [
            SearchResult(
                url="https://a.com", title="A", date=None, origin="daily",
                excerpt="Excerpt A",
            ),
            SearchResult(
                url="https://b.com", title="B", date=None, origin="daily",
                excerpt="Excerpt B",
            ),
        ]
        deduped = deduplicate_results(results)
        assert deduped[0].excerpt == "Excerpt A"
        assert deduped[1].excerpt == "Excerpt B"


# ===========================================================================
# parse_articles with excerpts
# ===========================================================================


class TestParseArticlesWithExcerpts:
    """Verify parse_articles handles the excerpt field."""

    def test_excerpt_from_search_result(self) -> None:
        results = [
            SearchResult(
                url="https://a.com", title="A", date="3 days ago", origin="daily",
                excerpt="Brave snippet",
            ),
        ]
        articles = parse_articles(results, reference_date=REF_DATE)
        assert articles[0].excerpt == "Brave snippet"

    def test_empty_excerpt_becomes_none(self) -> None:
        results = [
            SearchResult(
                url="https://a.com", title="A", date=None, origin="daily",
                excerpt="",
            ),
        ]
        articles = parse_articles(results, reference_date=REF_DATE)
        assert articles[0].excerpt is None

    def test_no_excerpt_defaults_to_none(self) -> None:
        results = [
            SearchResult(url="https://a.com", title="A", date=None, origin="daily"),
        ]
        articles = parse_articles(results, reference_date=REF_DATE)
        assert articles[0].excerpt is None


# ===========================================================================
# collect_articles — full pipeline with Brave + relevance
# ===========================================================================


class TestCollectArticlesDaily:
    """End-to-end test: daily schedule with Brave Search + relevance assessment."""

    @pytest.fixture()
    def http_client(self) -> StubHttpClient:
        return StubHttpClient(responses=_build_daily_brave_responses())

    @pytest.fixture()
    def repository(self) -> StubArticleRepository:
        return StubArticleRepository()

    def _make_client(self, http: StubHttpClient) -> Any:
        from ica.services.brave_search import BraveSearchClient

        return BraveSearchClient(api_key="test-key", http_client=http)

    @patch("ica.pipeline.relevance_assessment.assess_articles")
    async def test_daily_schedule_uses_correct_keywords(
        self,
        mock_assess: AsyncMock,
        http_client: StubHttpClient,
        repository: StubArticleRepository,
    ) -> None:
        mock_assess.return_value = []
        client = self._make_client(http_client)
        await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        keywords_searched = [r["params"]["q"] for r in http_client.requests]
        assert keywords_searched == DAILY_KEYWORDS

    @patch("ica.pipeline.relevance_assessment.assess_articles")
    async def test_daily_origin_label(
        self,
        mock_assess: AsyncMock,
        http_client: StubHttpClient,
        repository: StubArticleRepository,
    ) -> None:
        mock_assess.return_value = [
            RelevanceResult(url=f"https://example.com/{x}", decision="accept", reason="OK")
            for x in ["agi", "agi-safety", "automation", "ai-trends"]
        ]
        client = self._make_client(http_client)
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        for article in result.articles:
            assert article.origin == "daily"

    @patch("ica.pipeline.relevance_assessment.assess_articles")
    async def test_deduplication_applied(
        self,
        mock_assess: AsyncMock,
        http_client: StubHttpClient,
        repository: StubArticleRepository,
    ) -> None:
        mock_assess.return_value = [
            RelevanceResult(url=f"https://example.com/{x}", decision="accept", reason="OK")
            for x in ["agi", "agi-safety", "automation", "ai-trends"]
        ]
        client = self._make_client(http_client)
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        # AGI: 2 + Automation: 2 (incl dup) + AI: 1 = 5 raw, 4 unique
        assert len(result.raw_results) == 5
        assert len(result.deduplicated) == 4

    @patch("ica.pipeline.relevance_assessment.assess_articles")
    async def test_relevance_assessment_called(
        self,
        mock_assess: AsyncMock,
        http_client: StubHttpClient,
        repository: StubArticleRepository,
    ) -> None:
        mock_assess.return_value = [
            RelevanceResult(url=f"https://example.com/{x}", decision="accept", reason="OK")
            for x in ["agi", "agi-safety", "automation", "ai-trends"]
        ]
        client = self._make_client(http_client)
        await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        mock_assess.assert_awaited_once()
        # Should receive 4 deduplicated articles
        input_tuples = mock_assess.call_args.args[0]
        assert len(input_tuples) == 4

    @patch("ica.pipeline.relevance_assessment.assess_articles")
    async def test_accepted_rejected_counts(
        self,
        mock_assess: AsyncMock,
        http_client: StubHttpClient,
        repository: StubArticleRepository,
    ) -> None:
        mock_assess.return_value = [
            RelevanceResult(url="https://example.com/agi", decision="accept", reason="OK"),
            RelevanceResult(url="https://example.com/agi-safety", decision="reject", reason="Bad"),
            RelevanceResult(url="https://example.com/automation", decision="accept", reason="OK"),
            RelevanceResult(url="https://example.com/ai-trends", decision="reject", reason="Nope"),
        ]
        client = self._make_client(http_client)
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        assert result.accepted_count == 2
        assert result.rejected_count == 2

    @patch("ica.pipeline.relevance_assessment.assess_articles")
    async def test_articles_have_relevance_fields(
        self,
        mock_assess: AsyncMock,
        http_client: StubHttpClient,
        repository: StubArticleRepository,
    ) -> None:
        agi = "https://example.com/agi"
        safety = "https://example.com/agi-safety"
        auto = "https://example.com/automation"
        trends = "https://example.com/ai-trends"
        mock_assess.return_value = [
            RelevanceResult(url=agi, decision="accept", reason="Good fit"),
            RelevanceResult(url=safety, decision="reject", reason="Too academic"),
            RelevanceResult(url=auto, decision="accept", reason="Practical"),
            RelevanceResult(url=trends, decision="accept", reason="Timely"),
        ]
        client = self._make_client(http_client)
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        by_url = {a.url: a for a in result.articles}
        assert by_url["https://example.com/agi"].relevance_status == "accept"
        assert by_url["https://example.com/agi"].relevance_reason == "Good fit"
        assert by_url["https://example.com/agi-safety"].relevance_status == "reject"
        assert by_url["https://example.com/agi-safety"].relevance_reason == "Too academic"

    @patch("ica.pipeline.relevance_assessment.assess_articles")
    async def test_all_articles_upserted(
        self,
        mock_assess: AsyncMock,
        http_client: StubHttpClient,
        repository: StubArticleRepository,
    ) -> None:
        """Both accepted and rejected articles are saved to DB."""
        mock_assess.return_value = [
            RelevanceResult(url="https://example.com/agi", decision="accept", reason="OK"),
            RelevanceResult(url="https://example.com/agi-safety", decision="reject", reason="No"),
            RelevanceResult(url="https://example.com/automation", decision="accept", reason="OK"),
            RelevanceResult(url="https://example.com/ai-trends", decision="reject", reason="No"),
        ]
        client = self._make_client(http_client)
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        assert result.rows_affected == 4
        assert len(repository.articles) == 4


class TestCollectArticlesEvery2Days:
    """End-to-end test: every-2-days schedule with Brave Search."""

    @pytest.fixture()
    def http_client(self) -> StubHttpClient:
        return StubHttpClient(responses=_build_every_2_days_brave_responses())

    @pytest.fixture()
    def repository(self) -> StubArticleRepository:
        return StubArticleRepository()

    def _make_client(self, http: StubHttpClient) -> Any:
        from ica.services.brave_search import BraveSearchClient

        return BraveSearchClient(api_key="test-key", http_client=http)

    @patch("ica.pipeline.relevance_assessment.assess_articles")
    async def test_every_2_days_uses_correct_keywords(
        self,
        mock_assess: AsyncMock,
        http_client: StubHttpClient,
        repository: StubArticleRepository,
    ) -> None:
        mock_assess.return_value = [
            RelevanceResult(url="https://example.com/ai-new", decision="accept", reason="OK"),
            RelevanceResult(url="https://example.com/ai-latest", decision="accept", reason="OK"),
        ]
        client = self._make_client(http_client)
        await collect_articles(
            client, repository, schedule="every_2_days", reference_date=REF_DATE
        )
        keywords_searched = [r["params"]["q"] for r in http_client.requests]
        assert keywords_searched == EVERY_2_DAYS_KEYWORDS

    @patch("ica.pipeline.relevance_assessment.assess_articles")
    async def test_every_2_days_origin_label(
        self,
        mock_assess: AsyncMock,
        http_client: StubHttpClient,
        repository: StubArticleRepository,
    ) -> None:
        mock_assess.return_value = [
            RelevanceResult(url="https://example.com/ai-new", decision="accept", reason="OK"),
            RelevanceResult(url="https://example.com/ai-latest", decision="accept", reason="OK"),
        ]
        client = self._make_client(http_client)
        result = await collect_articles(
            client, repository, schedule="every_2_days", reference_date=REF_DATE
        )
        for article in result.articles:
            assert article.origin == "every_2_days"


class TestCollectArticlesEdgeCases:
    """Edge cases and error scenarios for article collection."""

    @pytest.fixture()
    def repository(self) -> StubArticleRepository:
        return StubArticleRepository()

    async def test_invalid_schedule_raises(self, repository: StubArticleRepository) -> None:
        from ica.services.brave_search import BraveSearchClient

        http = StubHttpClient()
        client = BraveSearchClient(api_key="key", http_client=http)
        with pytest.raises(ValueError, match="schedule must be"):
            await collect_articles(client, repository, schedule="invalid")

    @patch("ica.pipeline.relevance_assessment.assess_articles")
    async def test_no_results_from_search(
        self,
        mock_assess: AsyncMock,
        repository: StubArticleRepository,
    ) -> None:
        from ica.services.brave_search import BraveSearchClient

        http = StubHttpClient(responses={})
        client = BraveSearchClient(api_key="key", http_client=http)
        mock_assess.return_value = []
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        assert result.raw_results == []
        assert result.deduplicated == []
        assert result.articles == []
        assert result.rows_affected == 0
        assert result.accepted_count == 0
        assert result.rejected_count == 0

    @patch("ica.pipeline.relevance_assessment.assess_articles")
    async def test_all_duplicates_collapses_to_one(
        self,
        mock_assess: AsyncMock,
        repository: StubArticleRepository,
    ) -> None:
        from ica.services.brave_search import BraveSearchClient

        responses = {
            kw: _brave_response(_brave_item("https://same-url.com", f"Result for {kw}"))
            for kw in DAILY_KEYWORDS
        }
        http = StubHttpClient(responses=responses)
        client = BraveSearchClient(api_key="key", http_client=http)
        mock_assess.return_value = [
            RelevanceResult(url="https://same-url.com", decision="accept", reason="OK"),
        ]
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        assert len(result.raw_results) == 3
        assert len(result.deduplicated) == 1
        assert len(result.articles) == 1
        assert result.rows_affected == 1
