"""End-to-end tests for article collection pipeline.

Verifies the full flow: SearchApi query → deduplication → date parsing
→ DB insertion, using mocked external services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

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
from ica.services.search_api import SearchApiClient, SearchResult
from ica.utils.date_parser import format_date_mmddyyyy, parse_relative_date

# ---------------------------------------------------------------------------
# Reference date for deterministic tests
# ---------------------------------------------------------------------------

REF_DATE = date(2026, 2, 22)

# ---------------------------------------------------------------------------
# Mock HTTP client
# ---------------------------------------------------------------------------


@dataclass
class MockHttpClient:
    """Records requests and returns canned SearchApi responses."""

    responses: dict[str, dict[str, Any]] = field(default_factory=dict)
    requests: list[dict[str, Any]] = field(default_factory=list)

    async def get(
        self, url: str, *, params: dict[str, Any]
    ) -> dict[str, Any]:
        self.requests.append({"url": url, "params": params})
        keyword = params.get("q", "")
        return self.responses.get(keyword, {"organic_results": []})


# ---------------------------------------------------------------------------
# Mock article repository
# ---------------------------------------------------------------------------


@dataclass
class MockArticleRepository:
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
# SearchApi response fixtures
# ---------------------------------------------------------------------------

SEARCHAPI_RESPONSE_AGI = {
    "organic_results": [
        {
            "link": "https://example.com/agi-breakthrough",
            "title": "AGI Breakthrough Announced",
            "date": "3 days ago",
        },
        {
            "link": "https://example.com/agi-safety",
            "title": "AGI Safety Concerns Rise",
            "date": "1 week ago",
        },
    ]
}

SEARCHAPI_RESPONSE_AUTOMATION = {
    "organic_results": [
        {
            "link": "https://example.com/automation-smb",
            "title": "Automation Tools for SMBs",
            "date": "2 days ago",
        },
        # Duplicate URL from AGI search — should be deduplicated
        {
            "link": "https://example.com/agi-breakthrough",
            "title": "AGI Breakthrough (duplicate)",
            "date": "3 days ago",
        },
    ]
}

SEARCHAPI_RESPONSE_AI = {
    "organic_results": [
        {
            "link": "https://example.com/ai-trends",
            "title": "AI Trends 2026",
            "date": "5 days ago",
        },
    ]
}

SEARCHAPI_RESPONSE_AI_BREAKTHROUGH = {
    "organic_results": [
        {
            "link": "https://example.com/ai-new-model",
            "title": "New AI Model Released",
            "date": "1 day ago",
        },
    ]
}

SEARCHAPI_RESPONSE_AI_LATEST = {
    "organic_results": [
        {
            "link": "https://example.com/ai-latest-news",
            "title": "Latest AI News Roundup",
            "date": "2 weeks ago",
        },
    ]
}


def _build_daily_responses() -> dict[str, dict[str, Any]]:
    """Build SearchApi responses keyed by daily keywords."""
    return {
        "Artificial General Intelligence": SEARCHAPI_RESPONSE_AGI,
        "Automation": SEARCHAPI_RESPONSE_AUTOMATION,
        "Artificial Intelligence": SEARCHAPI_RESPONSE_AI,
    }


def _build_every_2_days_responses() -> dict[str, dict[str, Any]]:
    """Build SearchApi responses keyed by every-2-days keywords."""
    return {
        "AI breakthrough": SEARCHAPI_RESPONSE_AI_BREAKTHROUGH,
        "AI latest": SEARCHAPI_RESPONSE_AI_LATEST,
        "AI tutorial": {"organic_results": []},
        "AI case study": {"organic_results": []},
        "AI research": {"organic_results": []},
    }


# ===========================================================================
# Tests: Date Parsing
# ===========================================================================


class TestDateParsing:
    """Verify relative date parsing used in article collection."""

    def test_days_ago(self):
        result = parse_relative_date("3 days ago", reference=REF_DATE)
        assert result == date(2026, 2, 19)

    def test_single_day_ago(self):
        result = parse_relative_date("1 day ago", reference=REF_DATE)
        assert result == date(2026, 2, 21)

    def test_weeks_ago(self):
        result = parse_relative_date("1 week ago", reference=REF_DATE)
        assert result == date(2026, 2, 15)

    def test_two_weeks_ago(self):
        result = parse_relative_date("2 weeks ago", reference=REF_DATE)
        assert result == date(2026, 2, 8)

    def test_hours_ago_resolves_to_today(self):
        result = parse_relative_date("5 hours ago", reference=REF_DATE)
        assert result == REF_DATE

    def test_minutes_ago_resolves_to_today(self):
        result = parse_relative_date("30 minutes ago", reference=REF_DATE)
        assert result == REF_DATE

    def test_none_input_returns_reference(self):
        result = parse_relative_date(None, reference=REF_DATE)
        assert result == REF_DATE

    def test_empty_string_returns_reference(self):
        result = parse_relative_date("", reference=REF_DATE)
        assert result == REF_DATE

    def test_unparseable_string_returns_reference(self):
        result = parse_relative_date("yesterday", reference=REF_DATE)
        assert result == REF_DATE

    def test_case_insensitive(self):
        result = parse_relative_date("3 Days Ago", reference=REF_DATE)
        assert result == date(2026, 2, 19)

    def test_default_reference_is_today(self):
        result = parse_relative_date("0 days ago")
        assert result == date.today()


class TestFormatDateMmddyyyy:
    def test_formats_correctly(self):
        assert format_date_mmddyyyy(date(2026, 2, 22)) == "02/22/2026"

    def test_pads_single_digits(self):
        assert format_date_mmddyyyy(date(2026, 1, 5)) == "01/05/2026"


# ===========================================================================
# Tests: Deduplication
# ===========================================================================


class TestDeduplication:
    """Verify URL-based deduplication logic."""

    def test_removes_duplicate_urls(self):
        results = [
            SearchResult(url="https://a.com", title="First", date=None, origin="google_news"),
            SearchResult(url="https://b.com", title="Second", date=None, origin="google_news"),
            SearchResult(url="https://a.com", title="First Duplicate", date=None, origin="google_news"),
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 2
        assert deduped[0].url == "https://a.com"
        assert deduped[1].url == "https://b.com"

    def test_first_occurrence_wins(self):
        results = [
            SearchResult(url="https://a.com", title="Original", date="1 day ago", origin="google_news"),
            SearchResult(url="https://a.com", title="Duplicate", date="2 days ago", origin="default"),
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 1
        assert deduped[0].title == "Original"
        assert deduped[0].origin == "google_news"

    def test_preserves_order(self):
        results = [
            SearchResult(url="https://c.com", title="C", date=None, origin="google_news"),
            SearchResult(url="https://a.com", title="A", date=None, origin="google_news"),
            SearchResult(url="https://b.com", title="B", date=None, origin="google_news"),
        ]
        deduped = deduplicate_results(results)
        assert [r.url for r in deduped] == [
            "https://c.com",
            "https://a.com",
            "https://b.com",
        ]

    def test_empty_input(self):
        assert deduplicate_results([]) == []

    def test_no_duplicates(self):
        results = [
            SearchResult(url="https://a.com", title="A", date=None, origin="google_news"),
            SearchResult(url="https://b.com", title="B", date=None, origin="google_news"),
        ]
        assert len(deduplicate_results(results)) == 2

    def test_strips_url_whitespace(self):
        results = [
            SearchResult(url="  https://a.com  ", title="A", date=None, origin="google_news"),
            SearchResult(url="https://a.com", title="A dup", date=None, origin="google_news"),
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 1

    def test_skips_empty_urls(self):
        results = [
            SearchResult(url="", title="Empty", date=None, origin="google_news"),
            SearchResult(url="https://a.com", title="Valid", date=None, origin="google_news"),
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 1
        assert deduped[0].url == "https://a.com"


# ===========================================================================
# Tests: Article Parsing (SearchResult → ArticleRecord)
# ===========================================================================


class TestParseArticles:
    """Verify conversion from SearchResult to ArticleRecord with date parsing."""

    def test_parses_relative_dates(self):
        results = [
            SearchResult(url="https://a.com", title="Article A", date="3 days ago", origin="google_news"),
            SearchResult(url="https://b.com", title="Article B", date="1 week ago", origin="google_news"),
        ]
        articles = parse_articles(results, reference_date=REF_DATE)
        assert len(articles) == 2
        assert articles[0].publish_date == date(2026, 2, 19)
        assert articles[1].publish_date == date(2026, 2, 15)

    def test_preserves_url_and_title(self):
        results = [
            SearchResult(url="https://a.com", title="Title A", date=None, origin="google_news"),
        ]
        articles = parse_articles(results, reference_date=REF_DATE)
        assert articles[0].url == "https://a.com"
        assert articles[0].title == "Title A"

    def test_preserves_origin(self):
        results = [
            SearchResult(url="https://a.com", title="A", date=None, origin="google_news"),
            SearchResult(url="https://b.com", title="B", date=None, origin="default"),
        ]
        articles = parse_articles(results, reference_date=REF_DATE)
        assert articles[0].origin == "google_news"
        assert articles[1].origin == "default"

    def test_null_date_uses_reference(self):
        results = [
            SearchResult(url="https://a.com", title="A", date=None, origin="google_news"),
        ]
        articles = parse_articles(results, reference_date=REF_DATE)
        assert articles[0].publish_date == REF_DATE

    def test_strips_whitespace(self):
        results = [
            SearchResult(url="  https://a.com  ", title="  Title  ", date=None, origin="google_news"),
        ]
        articles = parse_articles(results, reference_date=REF_DATE)
        assert articles[0].url == "https://a.com"
        assert articles[0].title == "Title"

    def test_empty_input(self):
        assert parse_articles([], reference_date=REF_DATE) == []


# ===========================================================================
# Tests: SearchApi Client
# ===========================================================================


class TestSearchApiClient:
    """Verify SearchApi client sends correct requests and parses responses."""

    @pytest.fixture()
    def http_client(self) -> MockHttpClient:
        return MockHttpClient(responses=_build_daily_responses())

    @pytest.fixture()
    def client(self, http_client: MockHttpClient) -> SearchApiClient:
        return SearchApiClient(
            api_key="test-api-key",
            http_client=http_client,
        )

    async def test_single_keyword_search(
        self, client: SearchApiClient, http_client: MockHttpClient
    ):
        results = await client.search(
            "Artificial General Intelligence", engine="google_news", num=15
        )
        assert len(results) == 2
        assert results[0].url == "https://example.com/agi-breakthrough"
        assert results[0].origin == "google_news"

    async def test_search_passes_correct_params(
        self, client: SearchApiClient, http_client: MockHttpClient
    ):
        await client.search(
            "Automation",
            engine="google_news",
            num=15,
            time_period="last_week",
            location="United States",
        )
        req = http_client.requests[0]
        assert req["params"]["q"] == "Automation"
        assert req["params"]["engine"] == "google_news"
        assert req["params"]["num"] == 15
        assert req["params"]["time_period"] == "last_week"
        assert req["params"]["location"] == "United States"
        assert req["params"]["api_key"] == "test-api-key"

    async def test_default_engine_omits_engine_param(
        self, client: SearchApiClient, http_client: MockHttpClient
    ):
        http_client.responses["test"] = {"organic_results": []}
        await client.search("test", engine="default", num=10)
        req = http_client.requests[0]
        assert "engine" not in req["params"]

    async def test_search_keywords_aggregates(
        self, client: SearchApiClient, http_client: MockHttpClient
    ):
        results = await client.search_keywords(
            DAILY_KEYWORDS, engine="google_news", num=15
        )
        # AGI: 2 + Automation: 2 + AI: 1 = 5 total (before dedup)
        assert len(results) == 5
        assert len(http_client.requests) == 3

    async def test_handles_empty_response(
        self, client: SearchApiClient, http_client: MockHttpClient
    ):
        http_client.responses["empty"] = {"organic_results": []}
        results = await client.search("empty")
        assert results == []

    async def test_skips_results_without_link(
        self, client: SearchApiClient, http_client: MockHttpClient
    ):
        http_client.responses["no-link"] = {
            "organic_results": [
                {"title": "No Link Article"},
                {"link": "https://valid.com", "title": "Valid"},
            ]
        }
        results = await client.search("no-link")
        assert len(results) == 1
        assert results[0].url == "https://valid.com"

    async def test_handles_missing_organic_results_key(
        self, client: SearchApiClient, http_client: MockHttpClient
    ):
        http_client.responses["bad"] = {"some_other_key": []}
        results = await client.search("bad")
        assert results == []


# ===========================================================================
# Tests: Full E2E Flow — Daily Schedule
# ===========================================================================


class TestCollectArticlesDaily:
    """End-to-end test: daily schedule (google_news, 3 keywords)."""

    @pytest.fixture()
    def http_client(self) -> MockHttpClient:
        return MockHttpClient(responses=_build_daily_responses())

    @pytest.fixture()
    def repository(self) -> MockArticleRepository:
        return MockArticleRepository()

    @pytest.fixture()
    def client(self, http_client: MockHttpClient) -> SearchApiClient:
        return SearchApiClient(
            api_key="test-key", http_client=http_client
        )

    async def test_full_daily_flow(
        self,
        client: SearchApiClient,
        repository: MockArticleRepository,
        http_client: MockHttpClient,
    ):
        result = await collect_articles(
            client,
            repository,
            schedule="daily",
            reference_date=REF_DATE,
        )
        # Verify SearchApi was called for each keyword
        assert len(http_client.requests) == 3
        keywords_searched = [r["params"]["q"] for r in http_client.requests]
        assert keywords_searched == DAILY_KEYWORDS

        # Verify engine was google_news for all requests
        for req in http_client.requests:
            assert req["params"]["engine"] == "google_news"
            assert req["params"]["num"] == 15

    async def test_raw_results_include_all(
        self,
        client: SearchApiClient,
        repository: MockArticleRepository,
    ):
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        # AGI: 2, Automation: 2 (including duplicate), AI: 1 = 5
        assert len(result.raw_results) == 5

    async def test_deduplication_removes_duplicate_url(
        self,
        client: SearchApiClient,
        repository: MockArticleRepository,
    ):
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        # After dedup: 4 unique URLs
        assert len(result.deduplicated) == 4
        urls = [r.url for r in result.deduplicated]
        assert len(set(urls)) == 4
        assert "https://example.com/agi-breakthrough" in urls

    async def test_date_parsing_applied(
        self,
        client: SearchApiClient,
        repository: MockArticleRepository,
    ):
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        by_url = {a.url: a for a in result.articles}
        # "3 days ago" from REF_DATE (2026-02-22) → 2026-02-19
        assert by_url["https://example.com/agi-breakthrough"].publish_date == date(
            2026, 2, 19
        )
        # "1 week ago" → 2026-02-15
        assert by_url["https://example.com/agi-safety"].publish_date == date(
            2026, 2, 15
        )
        # "2 days ago" → 2026-02-20
        assert by_url["https://example.com/automation-smb"].publish_date == date(
            2026, 2, 20
        )
        # "5 days ago" → 2026-02-17
        assert by_url["https://example.com/ai-trends"].publish_date == date(
            2026, 2, 17
        )

    async def test_db_insertion(
        self,
        client: SearchApiClient,
        repository: MockArticleRepository,
    ):
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        # 4 unique articles upserted
        assert result.rows_affected == 4
        assert len(repository.articles) == 4
        assert len(repository.upsert_calls) == 1

    async def test_articles_have_correct_origin(
        self,
        client: SearchApiClient,
        repository: MockArticleRepository,
    ):
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        for article in result.articles:
            assert article.origin == "google_news"

    async def test_article_titles_preserved(
        self,
        client: SearchApiClient,
        repository: MockArticleRepository,
    ):
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        titles = {a.title for a in result.articles}
        assert "AGI Breakthrough Announced" in titles
        assert "AGI Safety Concerns Rise" in titles
        assert "Automation Tools for SMBs" in titles
        assert "AI Trends 2026" in titles


# ===========================================================================
# Tests: Full E2E Flow — Every 2 Days Schedule
# ===========================================================================


class TestCollectArticlesEvery2Days:
    """End-to-end test: every-2-days schedule (default engine, 5 keywords)."""

    @pytest.fixture()
    def http_client(self) -> MockHttpClient:
        return MockHttpClient(responses=_build_every_2_days_responses())

    @pytest.fixture()
    def repository(self) -> MockArticleRepository:
        return MockArticleRepository()

    @pytest.fixture()
    def client(self, http_client: MockHttpClient) -> SearchApiClient:
        return SearchApiClient(
            api_key="test-key", http_client=http_client
        )

    async def test_full_every_2_days_flow(
        self,
        client: SearchApiClient,
        repository: MockArticleRepository,
        http_client: MockHttpClient,
    ):
        result = await collect_articles(
            client,
            repository,
            schedule="every_2_days",
            reference_date=REF_DATE,
        )
        # All 5 keywords searched
        assert len(http_client.requests) == 5
        keywords_searched = [r["params"]["q"] for r in http_client.requests]
        assert keywords_searched == EVERY_2_DAYS_KEYWORDS

    async def test_uses_default_engine(
        self,
        client: SearchApiClient,
        repository: MockArticleRepository,
        http_client: MockHttpClient,
    ):
        await collect_articles(
            client,
            repository,
            schedule="every_2_days",
            reference_date=REF_DATE,
        )
        for req in http_client.requests:
            # Default engine should NOT send engine param
            assert "engine" not in req["params"]
            assert req["params"]["num"] == 10

    async def test_results_with_mixed_keywords(
        self,
        client: SearchApiClient,
        repository: MockArticleRepository,
    ):
        result = await collect_articles(
            client, repository, schedule="every_2_days", reference_date=REF_DATE
        )
        # AI breakthrough: 1, AI latest: 1, others: 0 = 2 total
        assert len(result.raw_results) == 2
        assert len(result.deduplicated) == 2
        assert len(result.articles) == 2

    async def test_date_parsing_for_default_engine(
        self,
        client: SearchApiClient,
        repository: MockArticleRepository,
    ):
        result = await collect_articles(
            client, repository, schedule="every_2_days", reference_date=REF_DATE
        )
        by_url = {a.url: a for a in result.articles}
        # "1 day ago" → 2026-02-21
        assert by_url["https://example.com/ai-new-model"].publish_date == date(
            2026, 2, 21
        )
        # "2 weeks ago" → 2026-02-08
        assert by_url["https://example.com/ai-latest-news"].publish_date == date(
            2026, 2, 8
        )

    async def test_articles_have_default_origin(
        self,
        client: SearchApiClient,
        repository: MockArticleRepository,
    ):
        result = await collect_articles(
            client, repository, schedule="every_2_days", reference_date=REF_DATE
        )
        for article in result.articles:
            assert article.origin == "default"


# ===========================================================================
# Tests: Edge Cases and Error Handling
# ===========================================================================


class TestCollectArticlesEdgeCases:
    """Edge cases and error scenarios for article collection."""

    @pytest.fixture()
    def repository(self) -> MockArticleRepository:
        return MockArticleRepository()

    async def test_invalid_schedule_raises(self, repository: MockArticleRepository):
        http_client = MockHttpClient()
        client = SearchApiClient(api_key="key", http_client=http_client)
        with pytest.raises(ValueError, match="schedule must be"):
            await collect_articles(client, repository, schedule="invalid")

    async def test_no_results_from_search(self, repository: MockArticleRepository):
        http_client = MockHttpClient(responses={})  # All keywords return empty
        client = SearchApiClient(api_key="key", http_client=http_client)
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        assert result.raw_results == []
        assert result.deduplicated == []
        assert result.articles == []
        assert result.rows_affected == 0

    async def test_all_duplicates_collapses_to_one(
        self, repository: MockArticleRepository
    ):
        http_client = MockHttpClient(
            responses={
                kw: {
                    "organic_results": [
                        {
                            "link": "https://same-url.com",
                            "title": f"Result for {kw}",
                            "date": "1 day ago",
                        }
                    ]
                }
                for kw in DAILY_KEYWORDS
            }
        )
        client = SearchApiClient(api_key="key", http_client=http_client)
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        assert len(result.raw_results) == 3  # 3 keywords, 1 each
        assert len(result.deduplicated) == 1  # All same URL
        assert len(result.articles) == 1
        assert result.rows_affected == 1

    async def test_upsert_called_once_per_collection(
        self, repository: MockArticleRepository
    ):
        http_client = MockHttpClient(responses=_build_daily_responses())
        client = SearchApiClient(api_key="key", http_client=http_client)
        await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        assert len(repository.upsert_calls) == 1

    async def test_subsequent_runs_update_existing(
        self, repository: MockArticleRepository
    ):
        """Simulate two collection runs — second run should update existing articles."""
        http_client = MockHttpClient(responses=_build_daily_responses())
        client = SearchApiClient(api_key="key", http_client=http_client)

        # First run
        result1 = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        assert len(repository.articles) == 4

        # Second run (same data — simulates upsert)
        result2 = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        # Still 4 unique articles in repository (upsert, not insert)
        assert len(repository.articles) == 4
        assert len(repository.upsert_calls) == 2

    async def test_results_with_missing_dates(
        self, repository: MockArticleRepository
    ):
        http_client = MockHttpClient(
            responses={
                "Artificial General Intelligence": {
                    "organic_results": [
                        {
                            "link": "https://no-date.com",
                            "title": "No Date Article",
                            # date field missing
                        },
                    ]
                },
            }
        )
        client = SearchApiClient(api_key="key", http_client=http_client)
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        assert len(result.articles) == 1
        # Missing date → falls back to reference date
        assert result.articles[0].publish_date == REF_DATE

    async def test_results_with_empty_titles(
        self, repository: MockArticleRepository
    ):
        http_client = MockHttpClient(
            responses={
                "Artificial General Intelligence": {
                    "organic_results": [
                        {
                            "link": "https://empty-title.com",
                            "title": "",
                            "date": "1 day ago",
                        },
                    ]
                },
            }
        )
        client = SearchApiClient(api_key="key", http_client=http_client)
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        assert len(result.articles) == 1
        assert result.articles[0].title == ""
        assert result.articles[0].url == "https://empty-title.com"


# ===========================================================================
# Tests: Data Integrity Through Full Pipeline
# ===========================================================================


class TestDataIntegrity:
    """Verify data is preserved correctly through the full pipeline."""

    @pytest.fixture()
    def http_client(self) -> MockHttpClient:
        return MockHttpClient(responses=_build_daily_responses())

    @pytest.fixture()
    def repository(self) -> MockArticleRepository:
        return MockArticleRepository()

    @pytest.fixture()
    def client(self, http_client: MockHttpClient) -> SearchApiClient:
        return SearchApiClient(api_key="key", http_client=http_client)

    async def test_collection_result_consistency(
        self,
        client: SearchApiClient,
        repository: MockArticleRepository,
    ):
        """Verify all stages of CollectionResult are consistent."""
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        # deduplicated <= raw_results
        assert len(result.deduplicated) <= len(result.raw_results)
        # articles matches deduplicated (1:1 mapping)
        assert len(result.articles) == len(result.deduplicated)
        # rows_affected matches articles count
        assert result.rows_affected == len(result.articles)

    async def test_repository_matches_result_articles(
        self,
        client: SearchApiClient,
        repository: MockArticleRepository,
    ):
        """Verify DB contents match pipeline output."""
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        for article in result.articles:
            assert article.url in repository.articles
            stored = repository.articles[article.url]
            assert stored.title == article.title
            assert stored.origin == article.origin
            assert stored.publish_date == article.publish_date

    async def test_deduplicated_urls_are_unique(
        self,
        client: SearchApiClient,
        repository: MockArticleRepository,
    ):
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        urls = [r.url for r in result.deduplicated]
        assert len(urls) == len(set(urls))

    async def test_article_urls_match_deduplicated(
        self,
        client: SearchApiClient,
        repository: MockArticleRepository,
    ):
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        dedup_urls = {r.url.strip() for r in result.deduplicated}
        article_urls = {a.url for a in result.articles}
        assert dedup_urls == article_urls
