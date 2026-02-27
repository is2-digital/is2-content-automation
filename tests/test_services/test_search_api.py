"""Tests for :mod:`ica.services.search_api`."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from ica.services.search_api import SearchApiClient, SearchResult

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


class StubHttpClient:
    """In-memory HTTP client that records calls and returns canned responses."""

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self._response = response or {"organic_results": []}

    async def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.requests.append({"url": url, "params": params})
        return self._response


@pytest.fixture
def http() -> StubHttpClient:
    return StubHttpClient()


@pytest.fixture
def client(http: StubHttpClient) -> SearchApiClient:
    return SearchApiClient(api_key="test-key", http_client=http)


def _organic(
    link: str = "https://example.com/article",
    title: str = "Test Article",
    date: str | None = "2 days ago",
) -> dict[str, Any]:
    """Build a single organic_results entry."""
    item: dict[str, Any] = {"link": link, "title": title}
    if date is not None:
        item["date"] = date
    return item


# ===========================================================================
# SearchResult dataclass
# ===========================================================================


class TestSearchResult:
    """Verify SearchResult dataclass behaviour."""

    def test_fields(self):
        r = SearchResult(url="https://x.com", title="T", date="1 day ago", origin="google_news")
        assert r.url == "https://x.com"
        assert r.title == "T"
        assert r.date == "1 day ago"
        assert r.origin == "google_news"

    def test_frozen(self):
        r = SearchResult(url="https://x.com", title="T", date=None, origin="default")
        with pytest.raises(FrozenInstanceError):
            r.url = "changed"  # type: ignore[misc]

    def test_date_none(self):
        r = SearchResult(url="u", title="t", date=None, origin="o")
        assert r.date is None

    def test_equality(self):
        a = SearchResult(url="u", title="t", date="d", origin="o")
        b = SearchResult(url="u", title="t", date="d", origin="o")
        assert a == b

    def test_inequality_different_url(self):
        a = SearchResult(url="u1", title="t", date="d", origin="o")
        b = SearchResult(url="u2", title="t", date="d", origin="o")
        assert a != b


# ===========================================================================
# SearchApiClient construction
# ===========================================================================


class TestSearchApiClientInit:
    """Verify constructor defaults and configuration."""

    def test_default_base_url(self, http: StubHttpClient):
        c = SearchApiClient(api_key="k", http_client=http)
        assert c.base_url == "https://www.searchapi.io/api/v1/search"

    def test_custom_base_url(self, http: StubHttpClient):
        c = SearchApiClient(api_key="k", http_client=http, base_url="https://custom.api/v2")
        assert c.base_url == "https://custom.api/v2"

    def test_api_key_stored(self, http: StubHttpClient):
        c = SearchApiClient(api_key="my-secret", http_client=http)
        assert c.api_key == "my-secret"


# ===========================================================================
# search() method
# ===========================================================================


class TestSearch:
    """Verify single-keyword search method."""

    async def test_passes_api_key(self, client: SearchApiClient, http: StubHttpClient):
        await client.search("AI")
        assert http.requests[0]["params"]["api_key"] == "test-key"

    async def test_passes_keyword_as_q(self, client: SearchApiClient, http: StubHttpClient):
        await client.search("robotics")
        assert http.requests[0]["params"]["q"] == "robotics"

    async def test_default_params(self, client: SearchApiClient, http: StubHttpClient):
        await client.search("AI")
        params = http.requests[0]["params"]
        assert params["engine"] == "google_news"
        assert params["num"] == 15
        assert params["time_period"] == "last_week"
        assert params["location"] == "United States"

    async def test_google_news_engine_included(
        self, client: SearchApiClient, http: StubHttpClient
    ):
        await client.search("AI", engine="google_news")
        assert http.requests[0]["params"]["engine"] == "google_news"

    async def test_default_engine_omits_engine_param(
        self, client: SearchApiClient, http: StubHttpClient
    ):
        await client.search("AI", engine="default")
        assert "engine" not in http.requests[0]["params"]

    async def test_custom_num(self, client: SearchApiClient, http: StubHttpClient):
        await client.search("AI", num=10)
        assert http.requests[0]["params"]["num"] == 10

    async def test_custom_time_period(self, client: SearchApiClient, http: StubHttpClient):
        await client.search("AI", time_period="last_month")
        assert http.requests[0]["params"]["time_period"] == "last_month"

    async def test_custom_location(self, client: SearchApiClient, http: StubHttpClient):
        await client.search("AI", location="Canada")
        assert http.requests[0]["params"]["location"] == "Canada"

    async def test_uses_base_url(self, http: StubHttpClient):
        c = SearchApiClient(api_key="k", http_client=http, base_url="https://mock.api/search")
        await c.search("test")
        assert http.requests[0]["url"] == "https://mock.api/search"

    async def test_returns_parsed_results(self, http: StubHttpClient):
        http._response = {
            "organic_results": [
                _organic("https://a.com", "Article A", "1 day ago"),
                _organic("https://b.com", "Article B", "3 hours ago"),
            ]
        }
        c = SearchApiClient(api_key="k", http_client=http)
        results = await c.search("AI")
        assert len(results) == 2
        assert results[0].url == "https://a.com"
        assert results[0].title == "Article A"
        assert results[0].date == "1 day ago"
        assert results[1].url == "https://b.com"

    async def test_origin_set_to_engine(self, http: StubHttpClient):
        http._response = {"organic_results": [_organic()]}
        c = SearchApiClient(api_key="k", http_client=http)
        results = await c.search("AI", engine="google_news")
        assert results[0].origin == "google_news"

    async def test_origin_default_engine(self, http: StubHttpClient):
        http._response = {"organic_results": [_organic()]}
        c = SearchApiClient(api_key="k", http_client=http)
        results = await c.search("AI", engine="default")
        assert results[0].origin == "default"

    async def test_empty_organic_results(self, client: SearchApiClient):
        results = await client.search("nothing")
        assert results == []

    async def test_missing_organic_results_key(self, http: StubHttpClient):
        http._response = {"other_key": [{"link": "https://x.com"}]}
        c = SearchApiClient(api_key="k", http_client=http)
        results = await c.search("AI")
        assert results == []


# ===========================================================================
# _parse_results() static method
# ===========================================================================


class TestParseResults:
    """Verify organic_results parsing edge cases."""

    def test_basic_parsing(self):
        data = {"organic_results": [_organic("https://a.com", "A", "today")]}
        results = SearchApiClient._parse_results(data, origin="test")
        assert len(results) == 1
        assert results[0].url == "https://a.com"
        assert results[0].title == "A"
        assert results[0].date == "today"
        assert results[0].origin == "test"

    def test_skips_missing_link(self):
        data = {"organic_results": [{"title": "No Link"}]}
        results = SearchApiClient._parse_results(data, origin="x")
        assert results == []

    def test_skips_empty_link(self):
        data = {"organic_results": [{"link": "", "title": "Empty Link"}]}
        results = SearchApiClient._parse_results(data, origin="x")
        assert results == []

    def test_missing_title_defaults_empty(self):
        data = {"organic_results": [{"link": "https://x.com"}]}
        results = SearchApiClient._parse_results(data, origin="x")
        assert results[0].title == ""

    def test_missing_date_returns_none(self):
        data = {"organic_results": [{"link": "https://x.com", "title": "T"}]}
        results = SearchApiClient._parse_results(data, origin="x")
        assert results[0].date is None

    def test_date_present(self):
        data = {"organic_results": [{"link": "https://x.com", "title": "T", "date": "5 min ago"}]}
        results = SearchApiClient._parse_results(data, origin="x")
        assert results[0].date == "5 min ago"

    def test_multiple_results_order_preserved(self):
        data = {
            "organic_results": [
                _organic("https://first.com", "First"),
                _organic("https://second.com", "Second"),
                _organic("https://third.com", "Third"),
            ]
        }
        results = SearchApiClient._parse_results(data, origin="o")
        assert [r.url for r in results] == [
            "https://first.com",
            "https://second.com",
            "https://third.com",
        ]

    def test_mixed_valid_and_invalid(self):
        data = {
            "organic_results": [
                _organic("https://valid.com", "Valid"),
                {"title": "No Link"},
                {"link": "", "title": "Empty"},
                _organic("https://also-valid.com", "Also Valid"),
            ]
        }
        results = SearchApiClient._parse_results(data, origin="o")
        assert len(results) == 2
        assert results[0].url == "https://valid.com"
        assert results[1].url == "https://also-valid.com"

    def test_empty_organic_results(self):
        data = {"organic_results": []}
        results = SearchApiClient._parse_results(data, origin="o")
        assert results == []

    def test_no_organic_results_key(self):
        data = {"search_information": {"total_results": 0}}
        results = SearchApiClient._parse_results(data, origin="o")
        assert results == []

    def test_extra_fields_ignored(self):
        data = {
            "organic_results": [
                {
                    "link": "https://x.com",
                    "title": "T",
                    "date": "d",
                    "snippet": "ignored",
                    "position": 1,
                    "cached_page_link": "https://cache.com",
                }
            ]
        }
        results = SearchApiClient._parse_results(data, origin="o")
        assert len(results) == 1
        assert results[0].url == "https://x.com"


# ===========================================================================
# search_keywords() method
# ===========================================================================


class TestSearchKeywords:
    """Verify multi-keyword search aggregation."""

    async def test_calls_search_per_keyword(self, client: SearchApiClient, http: StubHttpClient):
        await client.search_keywords(["AI", "ML", "DL"])
        assert len(http.requests) == 3
        keywords = [r["params"]["q"] for r in http.requests]
        assert keywords == ["AI", "ML", "DL"]

    async def test_aggregates_results(self, http: StubHttpClient):
        # Return 1 result per call
        call_count = 0

        async def counting_get(url: str, *, params: dict[str, Any]) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {
                "organic_results": [
                    _organic(f"https://result-{call_count}.com", f"Result {call_count}")
                ]
            }

        http.get = counting_get  # type: ignore[assignment]
        c = SearchApiClient(api_key="k", http_client=http)
        results = await c.search_keywords(["a", "b", "c"])
        assert len(results) == 3

    async def test_empty_keywords_list(self, client: SearchApiClient, http: StubHttpClient):
        results = await client.search_keywords([])
        assert results == []
        assert len(http.requests) == 0

    async def test_single_keyword(self, client: SearchApiClient, http: StubHttpClient):
        await client.search_keywords(["AI"])
        assert len(http.requests) == 1
        assert http.requests[0]["params"]["q"] == "AI"

    async def test_passes_engine_to_all(self, client: SearchApiClient, http: StubHttpClient):
        await client.search_keywords(["a", "b"], engine="default")
        for req in http.requests:
            assert "engine" not in req["params"]

    async def test_passes_num_to_all(self, client: SearchApiClient, http: StubHttpClient):
        await client.search_keywords(["a", "b"], num=10)
        for req in http.requests:
            assert req["params"]["num"] == 10

    async def test_passes_time_period_to_all(self, client: SearchApiClient, http: StubHttpClient):
        await client.search_keywords(["a"], time_period="last_month")
        assert http.requests[0]["params"]["time_period"] == "last_month"

    async def test_passes_location_to_all(self, client: SearchApiClient, http: StubHttpClient):
        await client.search_keywords(["a"], location="UK")
        assert http.requests[0]["params"]["location"] == "UK"


# ===========================================================================
# HttpClient protocol
# ===========================================================================


class TestHttpClientProtocol:
    """Verify StubHttpClient structurally satisfies the HttpClient protocol."""

    def test_stub_has_get_method(self):
        stub = StubHttpClient()
        assert callable(getattr(stub, "get", None))

    def test_stub_accepted_by_client(self):
        """StubHttpClient works as http_client argument (structural subtyping)."""
        c = SearchApiClient(api_key="k", http_client=StubHttpClient())
        assert c.http_client is not None
