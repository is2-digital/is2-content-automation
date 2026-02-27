"""Tests for :mod:`ica.services.google_search`."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from ica.services.google_search import GoogleSearchClient, SearchResult

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


class StubHttpClient:
    """In-memory HTTP client that records calls and returns canned responses."""

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self._response = response or {"items": []}

    async def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.requests.append({"url": url, "params": params})
        return self._response


@pytest.fixture
def http() -> StubHttpClient:
    return StubHttpClient()


@pytest.fixture
def client(http: StubHttpClient) -> GoogleSearchClient:
    return GoogleSearchClient(api_key="test-key", cx="test-cx", http_client=http)


def _item(
    link: str = "https://example.com/article",
    title: str = "Test Article",
    date: str | None = "2025-01-15T10:00:00Z",
) -> dict[str, Any]:
    """Build a single Google CSE items[] entry with pagemap metatags."""
    item: dict[str, Any] = {"link": link, "title": title}
    if date is not None:
        item["pagemap"] = {"metatags": [{"article:published_time": date}]}
    return item


# ===========================================================================
# SearchResult dataclass
# ===========================================================================


class TestSearchResult:
    """Verify SearchResult dataclass behaviour."""

    def test_fields(self):
        r = SearchResult(url="https://x.com", title="T", date="2025-01-15", origin="daily")
        assert r.url == "https://x.com"
        assert r.title == "T"
        assert r.date == "2025-01-15"
        assert r.origin == "daily"

    def test_frozen(self):
        r = SearchResult(url="https://x.com", title="T", date=None, origin="every_2_days")
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
# GoogleSearchClient construction
# ===========================================================================


class TestGoogleSearchClientInit:
    """Verify constructor defaults and configuration."""

    def test_default_base_url(self, http: StubHttpClient):
        c = GoogleSearchClient(api_key="k", cx="cx", http_client=http)
        assert c.base_url == "https://www.googleapis.com/customsearch/v1"

    def test_custom_base_url(self, http: StubHttpClient):
        c = GoogleSearchClient(
            api_key="k", cx="cx", http_client=http, base_url="https://custom.api/v2"
        )
        assert c.base_url == "https://custom.api/v2"

    def test_api_key_stored(self, http: StubHttpClient):
        c = GoogleSearchClient(api_key="my-secret", cx="cx", http_client=http)
        assert c.api_key == "my-secret"

    def test_cx_stored(self, http: StubHttpClient):
        c = GoogleSearchClient(api_key="k", cx="my-cx-id", http_client=http)
        assert c.cx == "my-cx-id"


# ===========================================================================
# search() method
# ===========================================================================


class TestSearch:
    """Verify single-keyword search method."""

    async def test_passes_api_key(self, client: GoogleSearchClient, http: StubHttpClient):
        await client.search("AI")
        assert http.requests[0]["params"]["key"] == "test-key"

    async def test_passes_cx(self, client: GoogleSearchClient, http: StubHttpClient):
        await client.search("AI")
        assert http.requests[0]["params"]["cx"] == "test-cx"

    async def test_passes_keyword_as_q(self, client: GoogleSearchClient, http: StubHttpClient):
        await client.search("robotics")
        assert http.requests[0]["params"]["q"] == "robotics"

    async def test_default_params(self, client: GoogleSearchClient, http: StubHttpClient):
        await client.search("AI")
        params = http.requests[0]["params"]
        assert params["num"] == 10
        assert params["dateRestrict"] == "d7"
        assert params["gl"] == "us"
        assert params["start"] == 1
        assert "sort" not in params  # sort_by_date=False by default

    async def test_sort_by_date_adds_sort_param(
        self, client: GoogleSearchClient, http: StubHttpClient
    ):
        await client.search("AI", sort_by_date=True)
        assert http.requests[0]["params"]["sort"] == "date"

    async def test_no_sort_by_default(
        self, client: GoogleSearchClient, http: StubHttpClient
    ):
        await client.search("AI", sort_by_date=False)
        assert "sort" not in http.requests[0]["params"]

    async def test_custom_num(self, client: GoogleSearchClient, http: StubHttpClient):
        await client.search("AI", num=5)
        assert http.requests[0]["params"]["num"] == 5

    async def test_custom_date_restrict(
        self, client: GoogleSearchClient, http: StubHttpClient
    ):
        await client.search("AI", date_restrict="m1")
        assert http.requests[0]["params"]["dateRestrict"] == "m1"

    async def test_custom_gl(self, client: GoogleSearchClient, http: StubHttpClient):
        await client.search("AI", gl="gb")
        assert http.requests[0]["params"]["gl"] == "gb"

    async def test_uses_base_url(self, http: StubHttpClient):
        c = GoogleSearchClient(
            api_key="k", cx="cx", http_client=http,
            base_url="https://mock.api/search",
        )
        await c.search("test")
        assert http.requests[0]["url"] == "https://mock.api/search"

    async def test_returns_parsed_results(self, http: StubHttpClient):
        http._response = {
            "items": [
                _item("https://a.com", "Article A", "2025-01-15"),
                _item("https://b.com", "Article B", "2025-01-14"),
            ]
        }
        c = GoogleSearchClient(api_key="k", cx="cx", http_client=http)
        results = await c.search("AI")
        assert len(results) == 2
        assert results[0].url == "https://a.com"
        assert results[0].title == "Article A"
        assert results[0].date == "2025-01-15"
        assert results[1].url == "https://b.com"

    async def test_origin_daily_when_sort_by_date(self, http: StubHttpClient):
        http._response = {"items": [_item()]}
        c = GoogleSearchClient(api_key="k", cx="cx", http_client=http)
        results = await c.search("AI", sort_by_date=True)
        assert results[0].origin == "daily"

    async def test_origin_every_2_days_when_no_sort(self, http: StubHttpClient):
        http._response = {"items": [_item()]}
        c = GoogleSearchClient(api_key="k", cx="cx", http_client=http)
        results = await c.search("AI", sort_by_date=False)
        assert results[0].origin == "every_2_days"

    async def test_empty_items(self, client: GoogleSearchClient):
        results = await client.search("nothing")
        assert results == []

    async def test_missing_items_key(self, http: StubHttpClient):
        http._response = {"searchInformation": {"totalResults": "0"}}
        c = GoogleSearchClient(api_key="k", cx="cx", http_client=http)
        results = await c.search("AI")
        assert results == []


# ===========================================================================
# Pagination
# ===========================================================================


class TestPagination:
    """Verify automatic pagination for num > 10."""

    async def test_single_page_no_extra_request(
        self, client: GoogleSearchClient, http: StubHttpClient
    ):
        await client.search("AI", num=10)
        assert len(http.requests) == 1

    async def test_two_pages_for_15_results(self, http: StubHttpClient):
        call_count = 0

        async def paging_get(url: str, *, params: dict[str, Any]) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            page_size = params["num"]
            return {
                "items": [
                    _item(f"https://r{call_count}-{i}.com", f"R{call_count}-{i}")
                    for i in range(page_size)
                ]
            }

        http.get = paging_get  # type: ignore[assignment]
        c = GoogleSearchClient(api_key="k", cx="cx", http_client=http)
        results = await c.search("AI", num=15)
        assert len(results) == 15
        assert call_count == 2

    async def test_pagination_start_params(self, http: StubHttpClient):
        """Verify start increments correctly across pages."""
        requests: list[dict[str, Any]] = []

        async def paging_get(url: str, *, params: dict[str, Any]) -> dict[str, Any]:
            requests.append({"url": url, "params": params})
            page_size = params["num"]
            return {
                "items": [
                    _item(f"https://r-{i}.com", f"R-{i}")
                    for i in range(page_size)
                ]
            }

        http.get = paging_get  # type: ignore[assignment]
        c = GoogleSearchClient(api_key="k", cx="cx", http_client=http)
        await c.search("AI", num=15)
        assert requests[0]["params"]["start"] == 1
        assert requests[0]["params"]["num"] == 10
        assert requests[1]["params"]["start"] == 11
        assert requests[1]["params"]["num"] == 5

    async def test_stops_early_when_fewer_results(self, http: StubHttpClient):
        """If first page returns fewer than requested, don't make a second request."""
        http._response = {
            "items": [_item("https://only.com", "Only One")]
        }
        c = GoogleSearchClient(api_key="k", cx="cx", http_client=http)
        results = await c.search("AI", num=15)
        assert len(results) == 1
        assert len(http.requests) == 1

    async def test_caps_at_100(self, http: StubHttpClient):
        """num > 100 should be capped at 100 (Google CSE limit)."""
        call_count = 0

        async def paging_get(url: str, *, params: dict[str, Any]) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            page_size = params["num"]
            return {
                "items": [
                    _item(f"https://r{call_count}-{i}.com", f"R{call_count}-{i}")
                    for i in range(page_size)
                ]
            }

        http.get = paging_get  # type: ignore[assignment]
        c = GoogleSearchClient(api_key="k", cx="cx", http_client=http)
        results = await c.search("AI", num=200)
        assert len(results) == 100
        assert call_count == 10  # 10 pages of 10


# ===========================================================================
# _parse_results() static method
# ===========================================================================


class TestParseResults:
    """Verify Google CSE items[] parsing edge cases."""

    def test_basic_parsing(self):
        data = {"items": [_item("https://a.com", "A", "2025-01-15")]}
        results = GoogleSearchClient._parse_results(data, origin="test")
        assert len(results) == 1
        assert results[0].url == "https://a.com"
        assert results[0].title == "A"
        assert results[0].date == "2025-01-15"
        assert results[0].origin == "test"

    def test_skips_missing_link(self):
        data = {"items": [{"title": "No Link"}]}
        results = GoogleSearchClient._parse_results(data, origin="x")
        assert results == []

    def test_skips_empty_link(self):
        data = {"items": [{"link": "", "title": "Empty Link"}]}
        results = GoogleSearchClient._parse_results(data, origin="x")
        assert results == []

    def test_missing_title_defaults_empty(self):
        data = {"items": [{"link": "https://x.com"}]}
        results = GoogleSearchClient._parse_results(data, origin="x")
        assert results[0].title == ""

    def test_no_pagemap_returns_none_date(self):
        data = {"items": [{"link": "https://x.com", "title": "T"}]}
        results = GoogleSearchClient._parse_results(data, origin="x")
        assert results[0].date is None

    def test_empty_metatags_returns_none_date(self):
        data = {"items": [{"link": "https://x.com", "title": "T", "pagemap": {"metatags": []}}]}
        results = GoogleSearchClient._parse_results(data, origin="x")
        assert results[0].date is None

    def test_date_from_article_published_time(self):
        data = {
            "items": [
                {
                    "link": "https://x.com",
                    "title": "T",
                    "pagemap": {
                        "metatags": [{"article:published_time": "2025-01-15T10:00:00Z"}]
                    },
                }
            ]
        }
        results = GoogleSearchClient._parse_results(data, origin="x")
        assert results[0].date == "2025-01-15T10:00:00Z"

    def test_date_from_og_updated_time(self):
        data = {
            "items": [
                {
                    "link": "https://x.com",
                    "title": "T",
                    "pagemap": {"metatags": [{"og:updated_time": "2025-02-20"}]},
                }
            ]
        }
        results = GoogleSearchClient._parse_results(data, origin="x")
        assert results[0].date == "2025-02-20"

    def test_date_from_generic_date_key(self):
        data = {
            "items": [
                {
                    "link": "https://x.com",
                    "title": "T",
                    "pagemap": {"metatags": [{"date": "January 10, 2025"}]},
                }
            ]
        }
        results = GoogleSearchClient._parse_results(data, origin="x")
        assert results[0].date == "January 10, 2025"

    def test_date_priority_order(self):
        """article:published_time takes priority over og:updated_time."""
        data = {
            "items": [
                {
                    "link": "https://x.com",
                    "title": "T",
                    "pagemap": {
                        "metatags": [
                            {
                                "article:published_time": "2025-01-15",
                                "og:updated_time": "2025-02-20",
                                "date": "March 2025",
                            }
                        ]
                    },
                }
            ]
        }
        results = GoogleSearchClient._parse_results(data, origin="x")
        assert results[0].date == "2025-01-15"

    def test_multiple_results_order_preserved(self):
        data = {
            "items": [
                _item("https://first.com", "First"),
                _item("https://second.com", "Second"),
                _item("https://third.com", "Third"),
            ]
        }
        results = GoogleSearchClient._parse_results(data, origin="o")
        assert [r.url for r in results] == [
            "https://first.com",
            "https://second.com",
            "https://third.com",
        ]

    def test_mixed_valid_and_invalid(self):
        data = {
            "items": [
                _item("https://valid.com", "Valid"),
                {"title": "No Link"},
                {"link": "", "title": "Empty"},
                _item("https://also-valid.com", "Also Valid"),
            ]
        }
        results = GoogleSearchClient._parse_results(data, origin="o")
        assert len(results) == 2
        assert results[0].url == "https://valid.com"
        assert results[1].url == "https://also-valid.com"

    def test_empty_items(self):
        data = {"items": []}
        results = GoogleSearchClient._parse_results(data, origin="o")
        assert results == []

    def test_no_items_key(self):
        data = {"searchInformation": {"totalResults": "0"}}
        results = GoogleSearchClient._parse_results(data, origin="o")
        assert results == []

    def test_extra_fields_ignored(self):
        data = {
            "items": [
                {
                    "link": "https://x.com",
                    "title": "T",
                    "snippet": "ignored",
                    "displayLink": "x.com",
                    "cacheId": "abc123",
                }
            ]
        }
        results = GoogleSearchClient._parse_results(data, origin="o")
        assert len(results) == 1
        assert results[0].url == "https://x.com"


# ===========================================================================
# search_keywords() method
# ===========================================================================


class TestSearchKeywords:
    """Verify multi-keyword search aggregation."""

    async def test_calls_search_per_keyword(
        self, client: GoogleSearchClient, http: StubHttpClient
    ):
        await client.search_keywords(["AI", "ML", "DL"])
        assert len(http.requests) == 3
        keywords = [r["params"]["q"] for r in http.requests]
        assert keywords == ["AI", "ML", "DL"]

    async def test_aggregates_results(self, http: StubHttpClient):
        call_count = 0

        async def counting_get(url: str, *, params: dict[str, Any]) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {
                "items": [
                    _item(f"https://result-{call_count}.com", f"Result {call_count}")
                ]
            }

        http.get = counting_get  # type: ignore[assignment]
        c = GoogleSearchClient(api_key="k", cx="cx", http_client=http)
        results = await c.search_keywords(["a", "b", "c"])
        assert len(results) == 3

    async def test_empty_keywords_list(
        self, client: GoogleSearchClient, http: StubHttpClient
    ):
        results = await client.search_keywords([])
        assert results == []
        assert len(http.requests) == 0

    async def test_single_keyword(self, client: GoogleSearchClient, http: StubHttpClient):
        await client.search_keywords(["AI"])
        assert len(http.requests) == 1
        assert http.requests[0]["params"]["q"] == "AI"

    async def test_passes_sort_by_date_to_all(
        self, client: GoogleSearchClient, http: StubHttpClient
    ):
        await client.search_keywords(["a", "b"], sort_by_date=True)
        for req in http.requests:
            assert req["params"]["sort"] == "date"

    async def test_no_sort_when_sort_by_date_false(
        self, client: GoogleSearchClient, http: StubHttpClient
    ):
        await client.search_keywords(["a", "b"], sort_by_date=False)
        for req in http.requests:
            assert "sort" not in req["params"]

    async def test_passes_num_to_all(self, client: GoogleSearchClient, http: StubHttpClient):
        await client.search_keywords(["a", "b"], num=5)
        for req in http.requests:
            assert req["params"]["num"] == 5

    async def test_passes_date_restrict_to_all(
        self, client: GoogleSearchClient, http: StubHttpClient
    ):
        await client.search_keywords(["a"], date_restrict="m1")
        assert http.requests[0]["params"]["dateRestrict"] == "m1"

    async def test_passes_gl_to_all(self, client: GoogleSearchClient, http: StubHttpClient):
        await client.search_keywords(["a"], gl="gb")
        assert http.requests[0]["params"]["gl"] == "gb"


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
        c = GoogleSearchClient(api_key="k", cx="cx", http_client=StubHttpClient())
        assert c.http_client is not None
