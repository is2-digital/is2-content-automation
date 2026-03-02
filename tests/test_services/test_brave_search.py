"""Tests for ica.services.brave_search.

Tests cover:
- BraveSearchFlags: frozen dataclass, default values
- BraveSearchClient._parse_results: response parsing, empty responses, missing fields
- BraveSearchClient.search: pagination, origin labeling, freshness, header auth
- BraveSearchClient.search_keywords: multiple keywords, aggregation
- deduplicate_results (via article_collection): excerpt field preserved
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from ica.services.brave_search import (
    DEFAULT_FLAGS,
    BraveSearchClient,
    BraveSearchFlags,
    flags_from_settings,
)
from ica.services.google_search import SearchResult

# ---------------------------------------------------------------------------
# Stub HTTP client
# ---------------------------------------------------------------------------


@dataclass
class StubHttpClient:
    """Records requests and returns canned Brave API responses."""

    responses: list[dict[str, Any]] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    _call_index: int = 0

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.requests.append({"url": url, "params": params, "headers": headers})
        if self._call_index < len(self.responses):
            resp = self.responses[self._call_index]
            self._call_index += 1
            return resp
        return {"web": {"results": []}}


# ---------------------------------------------------------------------------
# Brave API response fixtures
# ---------------------------------------------------------------------------


def _brave_result(
    url: str,
    title: str = "Title",
    description: str = "Description",
    page_age: str | None = None,
    age: str | None = None,
) -> dict[str, Any]:
    """Build a single Brave web.results[] entry."""
    item: dict[str, Any] = {
        "url": url,
        "title": title,
        "description": description,
    }
    if page_age is not None:
        item["page_age"] = page_age
    if age is not None:
        item["age"] = age
    return item


def _brave_response(*items: dict[str, Any]) -> dict[str, Any]:
    """Wrap items in a Brave Web Search response shape."""
    return {"web": {"results": list(items)}}


# ===========================================================================
# BraveSearchFlags
# ===========================================================================


class TestBraveSearchFlags:
    """Tests for the BraveSearchFlags frozen dataclass."""

    def test_default_values(self) -> None:
        flags = BraveSearchFlags()
        assert flags.count == 20
        assert flags.freshness is None
        assert flags.search_lang == "en"
        assert flags.country == "us"
        assert flags.safesearch == "moderate"
        assert flags.extra_snippets is False
        assert flags.result_filter is None
        assert flags.text_decorations is None

    def test_is_frozen(self) -> None:
        flags = BraveSearchFlags()
        with pytest.raises(AttributeError):
            flags.count = 10  # type: ignore[misc]

    def test_custom_values(self) -> None:
        flags = BraveSearchFlags(
            count=10,
            freshness="pw",
            search_lang="fr",
            country="gb",
            safesearch="strict",
            extra_snippets=True,
            result_filter="web",
            text_decorations=False,
        )
        assert flags.count == 10
        assert flags.freshness == "pw"
        assert flags.search_lang == "fr"
        assert flags.country == "gb"
        assert flags.safesearch == "strict"
        assert flags.extra_snippets is True
        assert flags.result_filter == "web"
        assert flags.text_decorations is False

    def test_default_flags_singleton(self) -> None:
        assert isinstance(DEFAULT_FLAGS, BraveSearchFlags)
        assert DEFAULT_FLAGS.count == 20


# ===========================================================================
# _parse_results
# ===========================================================================


class TestParseResults:
    """Tests for BraveSearchClient._parse_results static method."""

    def test_parses_standard_response(self) -> None:
        data = _brave_response(
            _brave_result("https://a.com", "Title A", "Excerpt A", page_age="3 days ago"),
            _brave_result("https://b.com", "Title B", "Excerpt B", age="1 week ago"),
        )
        results = BraveSearchClient._parse_results(data, origin="daily")
        assert len(results) == 2
        assert results[0] == SearchResult(
            url="https://a.com",
            title="Title A",
            date="3 days ago",
            origin="daily",
            excerpt="Excerpt A",
        )
        assert results[1] == SearchResult(
            url="https://b.com",
            title="Title B",
            date="1 week ago",
            origin="daily",
            excerpt="Excerpt B",
        )

    def test_page_age_preferred_over_age(self) -> None:
        data = _brave_response(
            _brave_result("https://a.com", page_age="2 days ago", age="old"),
        )
        results = BraveSearchClient._parse_results(data, origin="daily")
        assert results[0].date == "2 days ago"

    def test_falls_back_to_age(self) -> None:
        data = _brave_response(
            _brave_result("https://a.com", age="5 hours ago"),
        )
        results = BraveSearchClient._parse_results(data, origin="daily")
        assert results[0].date == "5 hours ago"

    def test_no_date_fields(self) -> None:
        data = _brave_response(_brave_result("https://a.com"))
        results = BraveSearchClient._parse_results(data, origin="daily")
        assert results[0].date is None

    def test_skips_results_without_url(self) -> None:
        data = {"web": {"results": [{"title": "No URL", "description": "desc"}]}}
        results = BraveSearchClient._parse_results(data, origin="daily")
        assert len(results) == 0

    def test_skips_empty_url(self) -> None:
        data = {"web": {"results": [{"url": "", "title": "Empty URL"}]}}
        results = BraveSearchClient._parse_results(data, origin="daily")
        assert len(results) == 0

    def test_empty_web_results(self) -> None:
        data = {"web": {"results": []}}
        results = BraveSearchClient._parse_results(data, origin="daily")
        assert results == []

    def test_missing_web_key(self) -> None:
        data = {"query": {"original": "test"}}
        results = BraveSearchClient._parse_results(data, origin="daily")
        assert results == []

    def test_missing_results_key(self) -> None:
        data = {"web": {}}
        results = BraveSearchClient._parse_results(data, origin="daily")
        assert results == []

    def test_origin_label_passed_through(self) -> None:
        data = _brave_response(_brave_result("https://a.com"))
        daily = BraveSearchClient._parse_results(data, origin="daily")
        e2d = BraveSearchClient._parse_results(data, origin="every_2_days")
        assert daily[0].origin == "daily"
        assert e2d[0].origin == "every_2_days"

    def test_missing_title_defaults_to_empty(self) -> None:
        data = {"web": {"results": [{"url": "https://a.com"}]}}
        results = BraveSearchClient._parse_results(data, origin="daily")
        assert results[0].title == ""

    def test_missing_description_defaults_to_empty(self) -> None:
        data = {"web": {"results": [{"url": "https://a.com", "title": "T"}]}}
        results = BraveSearchClient._parse_results(data, origin="daily")
        assert results[0].excerpt == ""

    def test_excerpt_populated_from_description(self) -> None:
        data = _brave_response(
            _brave_result("https://a.com", description="This is the snippet"),
        )
        results = BraveSearchClient._parse_results(data, origin="daily")
        assert results[0].excerpt == "This is the snippet"


# ===========================================================================
# BraveSearchClient.search
# ===========================================================================


class TestSearch:
    """Tests for BraveSearchClient.search method."""

    def _make_client(
        self, http: StubHttpClient, **kwargs: Any
    ) -> BraveSearchClient:
        return BraveSearchClient(
            api_key="test-api-key",
            http_client=http,
            **kwargs,
        )

    async def test_single_page_search(self) -> None:
        http = StubHttpClient(
            responses=[
                _brave_response(
                    _brave_result("https://a.com", "Article A"),
                    _brave_result("https://b.com", "Article B"),
                ),
            ]
        )
        client = self._make_client(http)
        results = await client.search("AI news", num=2)
        assert len(results) == 2
        assert results[0].url == "https://a.com"
        assert results[1].url == "https://b.com"

    async def test_sends_auth_header(self) -> None:
        http = StubHttpClient(responses=[_brave_response()])
        client = self._make_client(http)
        await client.search("test", num=1)
        headers = http.requests[0]["headers"]
        assert headers["X-Subscription-Token"] == "test-api-key"
        assert headers["Accept"] == "application/json"

    async def test_sends_correct_params(self) -> None:
        http = StubHttpClient(responses=[_brave_response()])
        client = self._make_client(http)
        await client.search("AI test", num=5)
        params = http.requests[0]["params"]
        assert params["q"] == "AI test"
        assert params["count"] == 5
        assert params["offset"] == 0
        assert params["search_lang"] == "en"
        assert params["country"] == "us"
        assert params["safesearch"] == "moderate"

    async def test_sort_by_date_sets_daily_origin(self) -> None:
        http = StubHttpClient(
            responses=[_brave_response(_brave_result("https://a.com"))]
        )
        client = self._make_client(http)
        results = await client.search("test", sort_by_date=True)
        assert results[0].origin == "daily"

    async def test_no_sort_sets_every_2_days_origin(self) -> None:
        http = StubHttpClient(
            responses=[_brave_response(_brave_result("https://a.com"))]
        )
        client = self._make_client(http)
        results = await client.search("test", sort_by_date=False)
        assert results[0].origin == "every_2_days"

    async def test_freshness_override(self) -> None:
        http = StubHttpClient(responses=[_brave_response()])
        client = self._make_client(http)
        await client.search("test", freshness="pd")
        params = http.requests[0]["params"]
        assert params["freshness"] == "pd"

    async def test_freshness_from_flags(self) -> None:
        http = StubHttpClient(responses=[_brave_response()])
        flags = BraveSearchFlags(freshness="pw")
        client = self._make_client(http, flags=flags)
        await client.search("test")
        params = http.requests[0]["params"]
        assert params["freshness"] == "pw"

    async def test_freshness_none_omits_param(self) -> None:
        http = StubHttpClient(responses=[_brave_response()])
        client = self._make_client(http)
        await client.search("test")
        params = http.requests[0]["params"]
        assert "freshness" not in params

    async def test_extra_snippets_flag(self) -> None:
        http = StubHttpClient(responses=[_brave_response()])
        flags = BraveSearchFlags(extra_snippets=True)
        client = self._make_client(http, flags=flags)
        await client.search("test")
        params = http.requests[0]["params"]
        assert params["extra_snippets"] is True

    async def test_extra_snippets_false_omits_param(self) -> None:
        http = StubHttpClient(responses=[_brave_response()])
        client = self._make_client(http)
        await client.search("test")
        params = http.requests[0]["params"]
        assert "extra_snippets" not in params

    async def test_result_filter_flag(self) -> None:
        http = StubHttpClient(responses=[_brave_response()])
        flags = BraveSearchFlags(result_filter="web")
        client = self._make_client(http, flags=flags)
        await client.search("test")
        params = http.requests[0]["params"]
        assert params["result_filter"] == "web"

    async def test_result_filter_none_omits_param(self) -> None:
        http = StubHttpClient(responses=[_brave_response()])
        client = self._make_client(http)
        await client.search("test")
        params = http.requests[0]["params"]
        assert "result_filter" not in params

    async def test_text_decorations_false_sends_param(self) -> None:
        http = StubHttpClient(responses=[_brave_response()])
        flags = BraveSearchFlags(text_decorations=False)
        client = self._make_client(http, flags=flags)
        await client.search("test")
        params = http.requests[0]["params"]
        assert params["text_decorations"] is False

    async def test_text_decorations_true_sends_param(self) -> None:
        http = StubHttpClient(responses=[_brave_response()])
        flags = BraveSearchFlags(text_decorations=True)
        client = self._make_client(http, flags=flags)
        await client.search("test")
        params = http.requests[0]["params"]
        assert params["text_decorations"] is True

    async def test_text_decorations_none_omits_param(self) -> None:
        http = StubHttpClient(responses=[_brave_response()])
        client = self._make_client(http)
        await client.search("test")
        params = http.requests[0]["params"]
        assert "text_decorations" not in params

    async def test_pagination_multiple_pages(self) -> None:
        """Request 30 results → 2 pages (20 + 10)."""
        page1 = _brave_response(
            *[_brave_result(f"https://a{i}.com") for i in range(20)]
        )
        page2 = _brave_response(
            *[_brave_result(f"https://b{i}.com") for i in range(10)]
        )
        http = StubHttpClient(responses=[page1, page2])
        client = self._make_client(http)
        results = await client.search("test", num=30)
        assert len(results) == 30
        assert len(http.requests) == 2
        assert http.requests[0]["params"]["offset"] == 0
        assert http.requests[1]["params"]["offset"] == 1

    async def test_stops_early_when_fewer_results(self) -> None:
        """If first page returns fewer than requested, don't fetch more."""
        page1 = _brave_response(
            _brave_result("https://a.com"),
            _brave_result("https://b.com"),
        )
        http = StubHttpClient(responses=[page1])
        client = self._make_client(http)
        results = await client.search("test", num=20)
        assert len(results) == 2
        assert len(http.requests) == 1  # No second page request

    async def test_max_200_results_cap(self) -> None:
        """Requesting more than 200 is capped at 200."""
        # With 20 per page, 10 pages max → 200 results
        pages = [
            _brave_response(*[_brave_result(f"https://p{p}r{i}.com") for i in range(20)])
            for p in range(10)
        ]
        http = StubHttpClient(responses=pages)
        client = self._make_client(http)
        results = await client.search("test", num=500)
        assert len(results) == 200
        assert len(http.requests) == 10

    async def test_empty_search_results(self) -> None:
        http = StubHttpClient(responses=[_brave_response()])
        client = self._make_client(http)
        results = await client.search("nothing")
        assert results == []


# ===========================================================================
# BraveSearchClient.search_keywords
# ===========================================================================


class TestSearchKeywords:
    """Tests for BraveSearchClient.search_keywords method."""

    async def test_aggregates_results_from_multiple_keywords(self) -> None:
        http = StubHttpClient(
            responses=[
                _brave_response(_brave_result("https://a.com")),
                _brave_response(_brave_result("https://b.com")),
                _brave_response(_brave_result("https://c.com")),
            ]
        )
        client = BraveSearchClient(api_key="key", http_client=http)
        results = await client.search_keywords(["kw1", "kw2", "kw3"], num=5)
        assert len(results) == 3

    async def test_passes_params_to_each_search(self) -> None:
        http = StubHttpClient(
            responses=[_brave_response(), _brave_response()]
        )
        client = BraveSearchClient(api_key="key", http_client=http)
        await client.search_keywords(
            ["kw1", "kw2"], num=10, freshness="pd", sort_by_date=True
        )
        assert len(http.requests) == 2
        for req in http.requests:
            assert req["params"]["freshness"] == "pd"

    async def test_empty_keywords_list(self) -> None:
        http = StubHttpClient()
        client = BraveSearchClient(api_key="key", http_client=http)
        results = await client.search_keywords([])
        assert results == []
        assert len(http.requests) == 0

    async def test_sequential_execution_order(self) -> None:
        """Keywords are searched sequentially, not concurrently."""
        call_order: list[str] = []

        @dataclass
        class OrderTrackingClient:
            async def get(
                self, url: str, *, params: dict[str, Any], headers: dict[str, str] | None = None
            ) -> dict[str, Any]:
                call_order.append(params["q"])
                return _brave_response()

        client = BraveSearchClient(api_key="key", http_client=OrderTrackingClient())
        await client.search_keywords(["first", "second", "third"])
        assert call_order == ["first", "second", "third"]


# ===========================================================================
# BraveSearchClient dataclass
# ===========================================================================


class TestBraveSearchClientDataclass:
    """Tests for the BraveSearchClient dataclass fields."""

    def test_default_base_url(self) -> None:
        http = StubHttpClient()
        client = BraveSearchClient(api_key="key", http_client=http)
        assert client.base_url == "https://api.search.brave.com/res/v1/web/search"

    def test_custom_base_url(self) -> None:
        http = StubHttpClient()
        client = BraveSearchClient(
            api_key="key", http_client=http, base_url="https://custom.api/search"
        )
        assert client.base_url == "https://custom.api/search"

    def test_default_flags(self) -> None:
        http = StubHttpClient()
        client = BraveSearchClient(api_key="key", http_client=http)
        assert client.flags == BraveSearchFlags()

    async def test_uses_custom_base_url_for_requests(self) -> None:
        http = StubHttpClient(responses=[_brave_response()])
        client = BraveSearchClient(
            api_key="key",
            http_client=http,
            base_url="https://custom.api/v2/search",
        )
        await client.search("test")
        assert http.requests[0]["url"] == "https://custom.api/v2/search"


# ===========================================================================
# flags_from_settings
# ===========================================================================


class TestFlagsFromSettings:
    """Tests for the flags_from_settings factory function."""

    @staticmethod
    def _mock_settings(**overrides: str) -> MagicMock:
        defaults = {
            "brave_result_filter": "",
            "brave_extra_snippets": "",
            "brave_freshness": "",
            "brave_text_decorations": "",
        }
        defaults.update(overrides)
        settings = MagicMock()
        for k, v in defaults.items():
            setattr(settings, k, v)
        return settings

    def test_all_empty_returns_defaults(self) -> None:
        flags = flags_from_settings(self._mock_settings())
        assert flags.freshness is None
        assert flags.extra_snippets is False
        assert flags.result_filter is None
        assert flags.text_decorations is None

    def test_all_set(self) -> None:
        flags = flags_from_settings(
            self._mock_settings(
                brave_result_filter="web",
                brave_extra_snippets="true",
                brave_freshness="pd",
                brave_text_decorations="false",
            )
        )
        assert flags.result_filter == "web"
        assert flags.extra_snippets is True
        assert flags.freshness == "pd"
        assert flags.text_decorations is False

    def test_extra_snippets_case_insensitive(self) -> None:
        flags = flags_from_settings(self._mock_settings(brave_extra_snippets="True"))
        assert flags.extra_snippets is True

    def test_text_decorations_true(self) -> None:
        flags = flags_from_settings(self._mock_settings(brave_text_decorations="true"))
        assert flags.text_decorations is True

    def test_text_decorations_false(self) -> None:
        flags = flags_from_settings(self._mock_settings(brave_text_decorations="false"))
        assert flags.text_decorations is False

    def test_text_decorations_empty_is_none(self) -> None:
        flags = flags_from_settings(self._mock_settings(brave_text_decorations=""))
        assert flags.text_decorations is None

    def test_extra_snippets_non_true_is_false(self) -> None:
        flags = flags_from_settings(self._mock_settings(brave_extra_snippets="yes"))
        assert flags.extra_snippets is False
