"""End-to-end tests for article collection pipeline.

Verifies the full flow: Google CSE query → deduplication → date parsing
→ DB insertion, using mocked external services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pytest

from ica.pipeline.article_collection import (
    DAILY_KEYWORDS,
    EVERY_2_DAYS_KEYWORDS,
    ArticleRecord,
    collect_articles,
    deduplicate_results,
    parse_articles,
)
from ica.services.google_search import GoogleSearchClient, SearchResult
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
    """Records requests and returns canned Google CSE responses."""

    responses: dict[str, dict[str, Any]] = field(default_factory=dict)
    requests: list[dict[str, Any]] = field(default_factory=list)

    async def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.requests.append({"url": url, "params": params})
        keyword = params.get("q", "")
        return self.responses.get(keyword, {"items": []})


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
# Google CSE response fixtures
# ---------------------------------------------------------------------------


def _cse_item(
    link: str, title: str, date: str | None = None
) -> dict[str, Any]:
    """Build a single Google CSE items[] entry."""
    item: dict[str, Any] = {"link": link, "title": title}
    if date is not None:
        item["pagemap"] = {"metatags": [{"article:published_time": date}]}
    return item


CSE_RESPONSE_AGI = {
    "items": [
        _cse_item(
            "https://example.com/agi-breakthrough",
            "AGI Breakthrough Announced",
            "2026-02-19T10:00:00Z",
        ),
        _cse_item(
            "https://example.com/agi-safety",
            "AGI Safety Concerns Rise",
            "2026-02-15T08:00:00Z",
        ),
    ]
}

CSE_RESPONSE_AUTOMATION = {
    "items": [
        _cse_item(
            "https://example.com/automation-smb",
            "Automation Tools for SMBs",
            "2026-02-20T12:00:00Z",
        ),
        # Duplicate URL from AGI search — should be deduplicated
        _cse_item(
            "https://example.com/agi-breakthrough",
            "AGI Breakthrough (duplicate)",
            "2026-02-19T10:00:00Z",
        ),
    ]
}

CSE_RESPONSE_AI = {
    "items": [
        _cse_item(
            "https://example.com/ai-trends",
            "AI Trends 2026",
            "2026-02-17T14:00:00Z",
        ),
    ]
}

CSE_RESPONSE_AI_BREAKTHROUGH = {
    "items": [
        _cse_item(
            "https://example.com/ai-new-model",
            "New AI Model Released",
            "2026-02-21T09:00:00Z",
        ),
    ]
}

CSE_RESPONSE_AI_LATEST = {
    "items": [
        _cse_item(
            "https://example.com/ai-latest-news",
            "Latest AI News Roundup",
            "2026-02-08T16:00:00Z",
        ),
    ]
}


def _build_daily_responses() -> dict[str, dict[str, Any]]:
    """Build Google CSE responses keyed by daily keywords."""
    return {
        "Artificial General Intelligence": CSE_RESPONSE_AGI,
        "Automation": CSE_RESPONSE_AUTOMATION,
        "Artificial Intelligence": CSE_RESPONSE_AI,
    }


def _build_every_2_days_responses() -> dict[str, dict[str, Any]]:
    """Build Google CSE responses keyed by every-2-days keywords."""
    return {
        "AI breakthrough": CSE_RESPONSE_AI_BREAKTHROUGH,
        "AI latest": CSE_RESPONSE_AI_LATEST,
        "AI tutorial": {"items": []},
        "AI case study": {"items": []},
        "AI research": {"items": []},
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
            SearchResult(url="https://a.com", title="First", date=None, origin="daily"),
            SearchResult(url="https://b.com", title="Second", date=None, origin="daily"),
            SearchResult(
                url="https://a.com", title="First Duplicate", date=None, origin="daily"
            ),
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 2
        assert deduped[0].url == "https://a.com"
        assert deduped[1].url == "https://b.com"

    def test_first_occurrence_wins(self):
        results = [
            SearchResult(
                url="https://a.com", title="Original", date="2026-01-15", origin="daily"
            ),
            SearchResult(
                url="https://a.com", title="Duplicate", date="2026-01-14", origin="every_2_days"
            ),
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 1
        assert deduped[0].title == "Original"
        assert deduped[0].origin == "daily"

    def test_preserves_order(self):
        results = [
            SearchResult(url="https://c.com", title="C", date=None, origin="daily"),
            SearchResult(url="https://a.com", title="A", date=None, origin="daily"),
            SearchResult(url="https://b.com", title="B", date=None, origin="daily"),
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
            SearchResult(url="https://a.com", title="A", date=None, origin="daily"),
            SearchResult(url="https://b.com", title="B", date=None, origin="daily"),
        ]
        assert len(deduplicate_results(results)) == 2

    def test_strips_url_whitespace(self):
        results = [
            SearchResult(url="  https://a.com  ", title="A", date=None, origin="daily"),
            SearchResult(url="https://a.com", title="A dup", date=None, origin="daily"),
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 1

    def test_skips_empty_urls(self):
        results = [
            SearchResult(url="", title="Empty", date=None, origin="daily"),
            SearchResult(url="https://a.com", title="Valid", date=None, origin="daily"),
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
            SearchResult(
                url="https://a.com", title="Article A", date="3 days ago", origin="daily"
            ),
            SearchResult(
                url="https://b.com", title="Article B", date="1 week ago", origin="daily"
            ),
        ]
        articles = parse_articles(results, reference_date=REF_DATE)
        assert len(articles) == 2
        assert articles[0].publish_date == date(2026, 2, 19)
        assert articles[1].publish_date == date(2026, 2, 15)

    def test_preserves_url_and_title(self):
        results = [
            SearchResult(url="https://a.com", title="Title A", date=None, origin="daily"),
        ]
        articles = parse_articles(results, reference_date=REF_DATE)
        assert articles[0].url == "https://a.com"
        assert articles[0].title == "Title A"

    def test_preserves_origin(self):
        results = [
            SearchResult(url="https://a.com", title="A", date=None, origin="daily"),
            SearchResult(url="https://b.com", title="B", date=None, origin="every_2_days"),
        ]
        articles = parse_articles(results, reference_date=REF_DATE)
        assert articles[0].origin == "daily"
        assert articles[1].origin == "every_2_days"

    def test_null_date_uses_reference(self):
        results = [
            SearchResult(url="https://a.com", title="A", date=None, origin="daily"),
        ]
        articles = parse_articles(results, reference_date=REF_DATE)
        assert articles[0].publish_date == REF_DATE

    def test_strips_whitespace(self):
        results = [
            SearchResult(
                url="  https://a.com  ", title="  Title  ", date=None, origin="daily"
            ),
        ]
        articles = parse_articles(results, reference_date=REF_DATE)
        assert articles[0].url == "https://a.com"
        assert articles[0].title == "Title"

    def test_empty_input(self):
        assert parse_articles([], reference_date=REF_DATE) == []


# ===========================================================================
# Tests: GoogleSearchClient
# ===========================================================================


class TestGoogleSearchClient:
    """Verify GoogleSearchClient sends correct requests and parses responses."""

    @pytest.fixture()
    def http_client(self) -> MockHttpClient:
        return MockHttpClient(responses=_build_daily_responses())

    @pytest.fixture()
    def client(self, http_client: MockHttpClient) -> GoogleSearchClient:
        return GoogleSearchClient(
            api_key="test-api-key",
            cx="test-cx",
            http_client=http_client,
        )

    async def test_single_keyword_search(
        self, client: GoogleSearchClient, http_client: MockHttpClient
    ):
        results = await client.search(
            "Artificial General Intelligence", sort_by_date=True, num=10
        )
        assert len(results) == 2
        assert results[0].url == "https://example.com/agi-breakthrough"
        assert results[0].origin == "daily"

    async def test_search_passes_correct_params(
        self, client: GoogleSearchClient, http_client: MockHttpClient
    ):
        await client.search(
            "Automation",
            sort_by_date=True,
            num=10,
            date_restrict="d7",
            gl="us",
        )
        req = http_client.requests[0]
        assert req["params"]["q"] == "Automation"
        assert req["params"]["sort"] == "date"
        assert req["params"]["num"] == 10
        assert req["params"]["dateRestrict"] == "d7"
        assert req["params"]["gl"] == "us"
        assert req["params"]["key"] == "test-api-key"
        assert req["params"]["cx"] == "test-cx"

    async def test_relevance_ranking_omits_sort(
        self, client: GoogleSearchClient, http_client: MockHttpClient
    ):
        http_client.responses["test"] = {"items": []}
        await client.search("test", sort_by_date=False, num=10)
        req = http_client.requests[0]
        assert "sort" not in req["params"]

    async def test_search_keywords_aggregates(
        self, client: GoogleSearchClient, http_client: MockHttpClient
    ):
        results = await client.search_keywords(
            DAILY_KEYWORDS, sort_by_date=True, num=10
        )
        # AGI: 2 + Automation: 2 + AI: 1 = 5 total (before dedup)
        assert len(results) == 5
        assert len(http_client.requests) == 3

    async def test_handles_empty_response(
        self, client: GoogleSearchClient, http_client: MockHttpClient
    ):
        http_client.responses["empty"] = {"items": []}
        results = await client.search("empty")
        assert results == []

    async def test_skips_results_without_link(
        self, client: GoogleSearchClient, http_client: MockHttpClient
    ):
        http_client.responses["no-link"] = {
            "items": [
                {"title": "No Link Article"},
                {"link": "https://valid.com", "title": "Valid"},
            ]
        }
        results = await client.search("no-link")
        assert len(results) == 1
        assert results[0].url == "https://valid.com"

    async def test_handles_missing_items_key(
        self, client: GoogleSearchClient, http_client: MockHttpClient
    ):
        http_client.responses["bad"] = {"searchInformation": {"totalResults": "0"}}
        results = await client.search("bad")
        assert results == []


# ===========================================================================
# Tests: Full E2E Flow — Daily Schedule
# ===========================================================================


class TestCollectArticlesDaily:
    """End-to-end test: daily schedule (sort by date, 3 keywords)."""

    @pytest.fixture()
    def http_client(self) -> MockHttpClient:
        return MockHttpClient(responses=_build_daily_responses())

    @pytest.fixture()
    def repository(self) -> MockArticleRepository:
        return MockArticleRepository()

    @pytest.fixture()
    def client(self, http_client: MockHttpClient) -> GoogleSearchClient:
        return GoogleSearchClient(api_key="test-key", cx="test-cx", http_client=http_client)

    async def test_full_daily_flow(
        self,
        client: GoogleSearchClient,
        repository: MockArticleRepository,
        http_client: MockHttpClient,
    ):
        await collect_articles(
            client,
            repository,
            schedule="daily",
            reference_date=REF_DATE,
        )
        # Verify Google CSE was called for each keyword
        assert len(http_client.requests) == 3
        keywords_searched = [r["params"]["q"] for r in http_client.requests]
        assert keywords_searched == DAILY_KEYWORDS

        # Verify sort=date for daily schedule
        for req in http_client.requests:
            assert req["params"]["sort"] == "date"
            assert req["params"]["num"] == 10

    async def test_raw_results_include_all(
        self,
        client: GoogleSearchClient,
        repository: MockArticleRepository,
    ):
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        # AGI: 2, Automation: 2 (including duplicate), AI: 1 = 5
        assert len(result.raw_results) == 5

    async def test_deduplication_removes_duplicate_url(
        self,
        client: GoogleSearchClient,
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
        client: GoogleSearchClient,
        repository: MockArticleRepository,
    ):
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        # ISO dates from pagemap go through parse_relative_date which returns
        # REF_DATE for non-relative strings
        for article in result.articles:
            assert article.publish_date == REF_DATE

    async def test_db_insertion(
        self,
        client: GoogleSearchClient,
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
        client: GoogleSearchClient,
        repository: MockArticleRepository,
    ):
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        for article in result.articles:
            assert article.origin == "daily"

    async def test_article_titles_preserved(
        self,
        client: GoogleSearchClient,
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
    """End-to-end test: every-2-days schedule (relevance ranking, 5 keywords)."""

    @pytest.fixture()
    def http_client(self) -> MockHttpClient:
        return MockHttpClient(responses=_build_every_2_days_responses())

    @pytest.fixture()
    def repository(self) -> MockArticleRepository:
        return MockArticleRepository()

    @pytest.fixture()
    def client(self, http_client: MockHttpClient) -> GoogleSearchClient:
        return GoogleSearchClient(api_key="test-key", cx="test-cx", http_client=http_client)

    async def test_full_every_2_days_flow(
        self,
        client: GoogleSearchClient,
        repository: MockArticleRepository,
        http_client: MockHttpClient,
    ):
        await collect_articles(
            client,
            repository,
            schedule="every_2_days",
            reference_date=REF_DATE,
        )
        # All 5 keywords searched
        assert len(http_client.requests) == 5
        keywords_searched = [r["params"]["q"] for r in http_client.requests]
        assert keywords_searched == EVERY_2_DAYS_KEYWORDS

    async def test_uses_relevance_ranking(
        self,
        client: GoogleSearchClient,
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
            # Relevance ranking should NOT send sort param
            assert "sort" not in req["params"]
            assert req["params"]["num"] == 10

    async def test_results_with_mixed_keywords(
        self,
        client: GoogleSearchClient,
        repository: MockArticleRepository,
    ):
        result = await collect_articles(
            client, repository, schedule="every_2_days", reference_date=REF_DATE
        )
        # AI breakthrough: 1, AI latest: 1, others: 0 = 2 total
        assert len(result.raw_results) == 2
        assert len(result.deduplicated) == 2
        assert len(result.articles) == 2

    async def test_articles_have_every_2_days_origin(
        self,
        client: GoogleSearchClient,
        repository: MockArticleRepository,
    ):
        result = await collect_articles(
            client, repository, schedule="every_2_days", reference_date=REF_DATE
        )
        for article in result.articles:
            assert article.origin == "every_2_days"


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
        client = GoogleSearchClient(api_key="key", cx="cx", http_client=http_client)
        with pytest.raises(ValueError, match="schedule must be"):
            await collect_articles(client, repository, schedule="invalid")

    async def test_no_results_from_search(self, repository: MockArticleRepository):
        http_client = MockHttpClient(responses={})  # All keywords return empty
        client = GoogleSearchClient(api_key="key", cx="cx", http_client=http_client)
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        assert result.raw_results == []
        assert result.deduplicated == []
        assert result.articles == []
        assert result.rows_affected == 0

    async def test_all_duplicates_collapses_to_one(self, repository: MockArticleRepository):
        http_client = MockHttpClient(
            responses={
                kw: {
                    "items": [
                        _cse_item(
                            "https://same-url.com",
                            f"Result for {kw}",
                            "2026-02-21T09:00:00Z",
                        )
                    ]
                }
                for kw in DAILY_KEYWORDS
            }
        )
        client = GoogleSearchClient(api_key="key", cx="cx", http_client=http_client)
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        assert len(result.raw_results) == 3  # 3 keywords, 1 each
        assert len(result.deduplicated) == 1  # All same URL
        assert len(result.articles) == 1
        assert result.rows_affected == 1

    async def test_upsert_called_once_per_collection(self, repository: MockArticleRepository):
        http_client = MockHttpClient(responses=_build_daily_responses())
        client = GoogleSearchClient(api_key="key", cx="cx", http_client=http_client)
        await collect_articles(client, repository, schedule="daily", reference_date=REF_DATE)
        assert len(repository.upsert_calls) == 1

    async def test_subsequent_runs_update_existing(self, repository: MockArticleRepository):
        """Simulate two collection runs — second run should update existing articles."""
        http_client = MockHttpClient(responses=_build_daily_responses())
        client = GoogleSearchClient(api_key="key", cx="cx", http_client=http_client)

        # First run
        await collect_articles(client, repository, schedule="daily", reference_date=REF_DATE)
        assert len(repository.articles) == 4

        # Second run (same data — simulates upsert)
        await collect_articles(client, repository, schedule="daily", reference_date=REF_DATE)
        # Still 4 unique articles in repository (upsert, not insert)
        assert len(repository.articles) == 4
        assert len(repository.upsert_calls) == 2

    async def test_results_with_missing_dates(self, repository: MockArticleRepository):
        http_client = MockHttpClient(
            responses={
                "Artificial General Intelligence": {
                    "items": [
                        {
                            "link": "https://no-date.com",
                            "title": "No Date Article",
                            # No pagemap/metatags → date will be None
                        },
                    ]
                },
            }
        )
        client = GoogleSearchClient(api_key="key", cx="cx", http_client=http_client)
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        assert len(result.articles) == 1
        # Missing date → falls back to reference date
        assert result.articles[0].publish_date == REF_DATE

    async def test_results_with_empty_titles(self, repository: MockArticleRepository):
        http_client = MockHttpClient(
            responses={
                "Artificial General Intelligence": {
                    "items": [
                        {
                            "link": "https://empty-title.com",
                            "title": "",
                            "pagemap": {
                                "metatags": [
                                    {"article:published_time": "2026-02-21T09:00:00Z"}
                                ]
                            },
                        },
                    ]
                },
            }
        )
        client = GoogleSearchClient(api_key="key", cx="cx", http_client=http_client)
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
    def client(self, http_client: MockHttpClient) -> GoogleSearchClient:
        return GoogleSearchClient(api_key="key", cx="cx", http_client=http_client)

    async def test_collection_result_consistency(
        self,
        client: GoogleSearchClient,
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
        client: GoogleSearchClient,
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
        client: GoogleSearchClient,
        repository: MockArticleRepository,
    ):
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        urls = [r.url for r in result.deduplicated]
        assert len(urls) == len(set(urls))

    async def test_article_urls_match_deduplicated(
        self,
        client: GoogleSearchClient,
        repository: MockArticleRepository,
    ):
        result = await collect_articles(
            client, repository, schedule="daily", reference_date=REF_DATE
        )
        dedup_urls = {r.url.strip() for r in result.deduplicated}
        article_urls = {a.url for a in result.articles}
        assert dedup_urls == article_urls
