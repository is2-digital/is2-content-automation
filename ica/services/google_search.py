"""Google Custom Search client for article discovery.

Wraps the Google Custom Search JSON API to search for AI-related articles.
Daily searches use ``sort=date`` for recency; every-2-days searches use
default relevance ranking.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class SearchResult:
    """A single search result from Google Custom Search."""

    url: str
    title: str
    date: str | None
    origin: str  # "daily" or "every_2_days"


class HttpClient(Protocol):
    """Minimal async HTTP client interface for dependency injection."""

    async def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class GoogleSearchClient:
    """Client for the Google Custom Search JSON API.

    Args:
        api_key: Google API key with Custom Search enabled.
        cx: Programmable Search Engine ID.
        http_client: An async HTTP client implementing :class:`HttpClient`.
        base_url: Override for the Google CSE endpoint.
    """

    api_key: str
    cx: str
    http_client: HttpClient
    base_url: str = "https://www.googleapis.com/customsearch/v1"

    async def search(
        self,
        keyword: str,
        *,
        num: int = 10,
        date_restrict: str = "d7",
        gl: str = "us",
        sort_by_date: bool = False,
    ) -> list[SearchResult]:
        """Execute a single keyword search and return results.

        Automatically paginates when *num* exceeds the per-request
        maximum of 10 (Google CSE limit).

        Args:
            keyword: Search query string.
            num: Maximum number of results to request.
            date_restrict: Recency filter (e.g., ``"d7"`` for 7 days,
                ``"w1"`` for 1 week, ``"m1"`` for 1 month).
            gl: Two-letter country code for geolocation boost.
            sort_by_date: When ``True``, results are sorted by date
                (daily schedule). When ``False``, default relevance
                ranking is used (every-2-days schedule).

        Returns:
            List of :class:`SearchResult` objects parsed from the API response.
        """
        origin = "daily" if sort_by_date else "every_2_days"
        all_results: list[SearchResult] = []
        remaining = min(num, 100)  # Google CSE returns max 100 total
        start = 1

        while remaining > 0:
            page_size = min(remaining, 10)
            params: dict[str, Any] = {
                "key": self.api_key,
                "cx": self.cx,
                "q": keyword,
                "num": page_size,
                "dateRestrict": date_restrict,
                "gl": gl,
                "start": start,
            }
            if sort_by_date:
                params["sort"] = "date"

            data = await self.http_client.get(self.base_url, params=params)
            page_results = self._parse_results(data, origin=origin)
            all_results.extend(page_results)

            # Stop if fewer results returned than requested (no more pages)
            if len(page_results) < page_size:
                break

            remaining -= page_size
            start += page_size

        return all_results

    async def search_keywords(
        self,
        keywords: list[str],
        *,
        num: int = 10,
        date_restrict: str = "d7",
        gl: str = "us",
        sort_by_date: bool = False,
    ) -> list[SearchResult]:
        """Search multiple keywords sequentially and aggregate results.

        Args:
            keywords: List of keyword strings to search.
            num: Maximum results per keyword.
            date_restrict: Recency filter.
            gl: Two-letter country code.
            sort_by_date: Sort results by date when ``True``.

        Returns:
            Combined list of results from all keyword searches.
        """
        all_results: list[SearchResult] = []
        for kw in keywords:
            results = await self.search(
                kw,
                num=num,
                date_restrict=date_restrict,
                gl=gl,
                sort_by_date=sort_by_date,
            )
            all_results.extend(results)
        return all_results

    @staticmethod
    def _parse_results(data: dict[str, Any], *, origin: str) -> list[SearchResult]:
        """Extract results from Google CSE response JSON.

        Looks for dates in ``pagemap.metatags[0]`` using common meta tag
        keys (``article:published_time``, ``og:updated_time``,
        ``date``, ``publishdate``).

        Args:
            data: Raw JSON response dict from Google CSE.
            origin: Label to record as the result origin.

        Returns:
            List of parsed :class:`SearchResult` objects.
        """
        results: list[SearchResult] = []
        for item in data.get("items", []):
            link = item.get("link", "")
            if not link:
                continue
            date = _extract_date(item)
            results.append(
                SearchResult(
                    url=link,
                    title=item.get("title", ""),
                    date=date,
                    origin=origin,
                )
            )
        return results


# Date meta tag keys in priority order
_DATE_META_KEYS = (
    "article:published_time",
    "og:updated_time",
    "date",
    "publishdate",
    "datePublished",
    "dc.date",
)


def _extract_date(item: dict[str, Any]) -> str | None:
    """Extract a publish date from a Google CSE item's pagemap metatags.

    Args:
        item: A single item from the Google CSE ``items`` array.

    Returns:
        The first date string found, or ``None``.
    """
    pagemap = item.get("pagemap", {})
    metatags = pagemap.get("metatags", [])
    if not metatags:
        return None
    tags = metatags[0] if isinstance(metatags, list) else {}
    for key in _DATE_META_KEYS:
        value = tags.get(key)
        if value:
            return str(value)
    return None
