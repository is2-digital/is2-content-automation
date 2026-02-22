"""SearchApi client for article discovery.

Wraps the SearchApi.io HTTP API to search for AI-related articles
using either the ``google_news`` engine (daily) or the default
search engine (every 2 days).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SearchResult:
    """A single organic search result from SearchApi."""

    url: str
    title: str
    date: str | None
    origin: str  # "google_news" or "default"


class HttpClient(Protocol):
    """Minimal async HTTP client interface for dependency injection."""

    async def get(
        self, url: str, *, params: dict[str, Any]
    ) -> dict[str, Any]: ...


@dataclass
class SearchApiClient:
    """Client for the SearchApi.io article discovery API.

    Args:
        api_key: SearchApi API key.
        http_client: An async HTTP client implementing :class:`HttpClient`.
        base_url: Override for the SearchApi endpoint.
    """

    api_key: str
    http_client: HttpClient
    base_url: str = "https://www.searchapi.io/api/v1/search"

    async def search(
        self,
        keyword: str,
        *,
        engine: str = "google_news",
        num: int = 15,
        time_period: str = "last_week",
        location: str = "United States",
    ) -> list[SearchResult]:
        """Execute a single keyword search and return organic results.

        Args:
            keyword: Search query string.
            engine: SearchApi engine (``"google_news"`` or omit for default).
            num: Maximum number of results to request.
            time_period: Recency filter (e.g., ``"last_week"``).
            location: Geographic location for results.

        Returns:
            List of :class:`SearchResult` objects parsed from the API response.
        """
        params: dict[str, Any] = {
            "api_key": self.api_key,
            "q": keyword,
            "num": num,
            "time_period": time_period,
            "location": location,
        }
        if engine != "default":
            params["engine"] = engine

        data = await self.http_client.get(self.base_url, params=params)
        return self._parse_results(data, origin=engine)

    async def search_keywords(
        self,
        keywords: list[str],
        *,
        engine: str = "google_news",
        num: int = 15,
        time_period: str = "last_week",
        location: str = "United States",
    ) -> list[SearchResult]:
        """Search multiple keywords sequentially and aggregate results.

        Args:
            keywords: List of keyword strings to search.
            engine: SearchApi engine to use.
            num: Maximum results per keyword.
            time_period: Recency filter.
            location: Geographic location.

        Returns:
            Combined list of results from all keyword searches.
        """
        all_results: list[SearchResult] = []
        for kw in keywords:
            results = await self.search(
                kw,
                engine=engine,
                num=num,
                time_period=time_period,
                location=location,
            )
            all_results.extend(results)
        return all_results

    @staticmethod
    def _parse_results(
        data: dict[str, Any], *, origin: str
    ) -> list[SearchResult]:
        """Extract organic results from SearchApi response JSON.

        Args:
            data: Raw JSON response dict from SearchApi.
            origin: Engine name to record as the result origin.

        Returns:
            List of parsed :class:`SearchResult` objects.
        """
        results: list[SearchResult] = []
        for item in data.get("organic_results", []):
            link = item.get("link", "")
            if not link:
                continue
            results.append(
                SearchResult(
                    url=link,
                    title=item.get("title", ""),
                    date=item.get("date"),
                    origin=origin,
                )
            )
        return results
