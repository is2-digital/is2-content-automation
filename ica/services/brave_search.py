"""Brave Web Search client for article discovery.

Wraps the Brave Web Search API to find AI-related articles.
Replaces Google Custom Search with Brave's search API, which provides
article excerpts (descriptions) and age-based date information.

API reference: https://api.search.brave.com/app/documentation/web-search/query
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from ica.config.settings import Settings

from ica.services.google_search import SearchResult


class HttpClient(Protocol):
    """Async HTTP client interface with header support for Brave API auth."""

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Brave Search API configuration flags
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BraveSearchFlags:
    """Configurable API parameters for Brave Web Search.

    These flags map directly to Brave Web Search API query parameters.

    Attributes:
        count: Results per page (max 20, default 20).
        freshness: Time filter — ``'pd'`` (past day), ``'pw'`` (past week),
            ``'pm'`` (past month), ``'py'`` (past year), or ``None`` for
            no time restriction.
        search_lang: ISO 639-1 language code for results (e.g., ``'en'``).
        country: Two-letter country code for geo-targeting (e.g., ``'us'``).
        safesearch: Content filter: ``'off'``, ``'moderate'``, ``'strict'``.
        extra_snippets: When ``True``, include up to 5 additional excerpts
            per result.
        result_filter: Comma-separated result types to include
            (e.g., ``'web'``). ``None`` omits the parameter.
        text_decorations: When ``False``, strip bold/highlight markers from
            display strings. ``None`` omits the parameter.
    """

    count: int = 20
    freshness: str | None = None
    search_lang: str = "en"
    country: str = "us"
    safesearch: str = "moderate"
    extra_snippets: bool = False
    result_filter: str | None = None
    text_decorations: bool | None = None


# Default flags instance for convenience
DEFAULT_FLAGS = BraveSearchFlags()


def flags_from_settings(settings: Settings) -> BraveSearchFlags:
    """Build :class:`BraveSearchFlags` from application settings.

    Empty/unset env vars are treated as *not configured*, so the
    corresponding API parameter will be omitted from requests.
    """
    extra_snippets = settings.brave_extra_snippets.lower() == "true"
    text_decorations: bool | None = None
    if settings.brave_text_decorations:
        text_decorations = settings.brave_text_decorations.lower() == "true"
    return BraveSearchFlags(
        freshness=settings.brave_freshness or None,
        extra_snippets=extra_snippets,
        result_filter=settings.brave_result_filter or None,
        text_decorations=text_decorations,
    )


@dataclass
class BraveSearchClient:
    """Client for the Brave Web Search API.

    Args:
        api_key: Brave Search API subscription token.
        http_client: An async HTTP client implementing :class:`HttpClient`.
        flags: Default search configuration flags. Individual search calls
            can override ``count`` and ``freshness``.
        base_url: Override for the Brave Search endpoint.
    """

    api_key: str
    http_client: HttpClient
    flags: BraveSearchFlags = field(default_factory=BraveSearchFlags)
    base_url: str = "https://api.search.brave.com/res/v1/web/search"

    async def search(
        self,
        keyword: str,
        *,
        num: int = 20,
        freshness: str | None = None,
        sort_by_date: bool = False,
    ) -> list[SearchResult]:
        """Execute a single keyword search and return results.

        Automatically paginates when *num* exceeds the per-request
        maximum of 20 (Brave API limit).

        Args:
            keyword: Search query string.
            num: Maximum number of results to request.
            freshness: Override the default freshness filter for this search.
                Pass ``'pd'`` for past day, ``'pw'`` for past week, etc.
                ``None`` uses the value from :attr:`flags`.
            sort_by_date: Label control — when ``True``, results get origin
                ``"daily"``; when ``False``, origin is ``"every_2_days"``.

        Returns:
            List of :class:`SearchResult` objects parsed from the API response.
        """
        origin = "daily" if sort_by_date else "every_2_days"
        all_results: list[SearchResult] = []
        remaining = min(num, 200)  # Brave: max offset 9 * 20 = 200
        offset = 0
        page_size = min(self.flags.count, 20)

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.api_key,
        }

        effective_freshness = freshness if freshness is not None else self.flags.freshness

        while remaining > 0 and offset <= 9:
            request_count = min(remaining, page_size)
            params: dict[str, Any] = {
                "q": keyword,
                "count": request_count,
                "offset": offset,
                "search_lang": self.flags.search_lang,
                "country": self.flags.country,
                "safesearch": self.flags.safesearch,
            }
            if effective_freshness:
                params["freshness"] = effective_freshness
            if self.flags.extra_snippets:
                params["extra_snippets"] = True
            if self.flags.result_filter:
                params["result_filter"] = self.flags.result_filter
            if self.flags.text_decorations is not None:
                params["text_decorations"] = self.flags.text_decorations

            data = await self.http_client.get(
                self.base_url, params=params, headers=headers
            )
            page_results = self._parse_results(data, origin=origin)
            all_results.extend(page_results)

            # Stop if fewer results returned than requested (no more pages)
            if len(page_results) < request_count:
                break

            remaining -= len(page_results)
            offset += 1

        return all_results

    async def search_keywords(
        self,
        keywords: list[str],
        *,
        num: int = 20,
        freshness: str | None = None,
        sort_by_date: bool = False,
    ) -> list[SearchResult]:
        """Search multiple keywords sequentially and aggregate results.

        Args:
            keywords: List of keyword strings to search.
            num: Maximum results per keyword.
            freshness: Override the default freshness filter.
            sort_by_date: Label control for origin field.

        Returns:
            Combined list of results from all keyword searches.
        """
        all_results: list[SearchResult] = []
        for kw in keywords:
            results = await self.search(
                kw,
                num=num,
                freshness=freshness,
                sort_by_date=sort_by_date,
            )
            all_results.extend(results)
        return all_results

    @staticmethod
    def _parse_results(data: dict[str, Any], *, origin: str) -> list[SearchResult]:
        """Extract results from Brave Web Search response JSON.

        Parses ``web.results[]`` entries, extracting URL, title, description
        (as excerpt), and age/page_age (as date string).

        Args:
            data: Raw JSON response dict from Brave Web Search API.
            origin: Label to record as the result origin.

        Returns:
            List of parsed :class:`SearchResult` objects.
        """
        results: list[SearchResult] = []
        web = data.get("web", {})
        for item in web.get("results", []):
            url = item.get("url", "")
            if not url:
                continue
            date = item.get("page_age") or item.get("age")
            results.append(
                SearchResult(
                    url=url,
                    title=item.get("title", ""),
                    date=date,
                    origin=origin,
                    excerpt=item.get("description", ""),
                )
            )
        return results
