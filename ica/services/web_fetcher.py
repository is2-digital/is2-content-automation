"""Web fetcher service for article page content retrieval.

Provides an async HTTP client with browser-like headers for fetching
article pages, plus utility functions for failure detection and
HTML-to-text conversion.

Implements the ``HttpFetcher`` protocol defined in
:mod:`ica.pipeline.summarization` using ``httpx.AsyncClient``.

See PRD Section 2.7.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape

import httpx


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": "Safari/537.36",
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
    "Connection": "keep-alive",
}
"""Browser-like headers for HTTP fetching.

Matches the n8n "Fetch Page Content" httpRequest node configuration.
"""

CAPTCHA_MARKER = "sgcaptcha"
"""String present in captcha challenge pages."""

YOUTUBE_DOMAIN = "youtube.com"
"""YouTube URLs cannot be scraped and require manual fallback."""

DEFAULT_TIMEOUT_SECONDS = 30.0
"""Default request timeout in seconds."""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FetchResult:
    """Result of an HTTP page fetch.

    Attributes:
        content: The response body text (HTML), or ``None`` on failure.
        error: ``None`` on success, or an error description string.
    """

    content: str | None
    error: str | None


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def is_fetch_failure(result: FetchResult, url: str) -> bool:
    """Determine whether an HTTP fetch should be treated as a failure.

    Ports the n8n "If" condition node which checks three conditions (AND):

    1. Error message exists (HTTP request threw an error)
    2. Response contains captcha marker (``sgcaptcha``)
    3. URL is a YouTube link (cannot be scraped)

    In the n8n workflow, all three conditions being *false* means success.
    Here we invert: any single condition being *true* means failure.

    Args:
        result: The :class:`FetchResult` from the HTTP fetch.
        url: The original article URL.

    Returns:
        ``True`` if the fetch failed and manual fallback is needed.
    """
    if result.error is not None:
        return True
    if result.content is not None and CAPTCHA_MARKER in result.content:
        return True
    if YOUTUBE_DOMAIN in url.lower():
        return True
    return False


def strip_html_tags(html: str) -> str:
    """Convert HTML to plain text by stripping tags.

    Provides a simple alternative to the n8n Markdown node (Turndown).
    Removes ``<script>`` and ``<style>`` elements, strips all tags,
    unescapes HTML entities, and normalizes whitespace.

    Args:
        html: Raw HTML string.

    Returns:
        Plain text content suitable for LLM consumption.
    """
    if not html:
        return ""
    # Remove script and style elements entirely
    text = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Replace block-level tags with newlines for readability
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(p|div|h[1-6]|li|tr)\b[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Unescape HTML entities
    text = unescape(text)
    # Normalize whitespace (collapse runs of spaces, preserve newlines)
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r"\n\s*\n", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------


class WebFetcherService:
    """Async HTTP client for fetching article page content.

    Uses ``httpx.AsyncClient`` with browser-like headers to fetch
    web pages. Transport errors are caught and returned in
    :attr:`FetchResult.error` rather than raised, matching the
    ``HttpFetcher`` protocol contract.

    Args:
        client: Optional pre-configured ``httpx.AsyncClient`` (for testing).
            If not provided, a new client is created with default settings.
        timeout: Request timeout in seconds.

    Usage::

        async with WebFetcherService() as fetcher:
            result = await fetcher.get("https://example.com/article")
            if result.error is None:
                print(result.content)
    """

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
        )

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        """Fetch a URL and return the response body.

        Satisfies the ``HttpFetcher`` protocol defined in
        :mod:`ica.pipeline.summarization`.

        Args:
            url: The URL to fetch.
            headers: Optional HTTP headers. Defaults to :data:`BROWSER_HEADERS`.

        Returns:
            A :class:`FetchResult` with ``content`` on success or
            ``error`` on failure.
        """
        request_headers = headers if headers is not None else BROWSER_HEADERS
        try:
            response = await self._client.get(url, headers=request_headers)
            response.raise_for_status()
            return FetchResult(content=response.text, error=None)
        except httpx.HTTPStatusError as exc:
            return FetchResult(
                content=None,
                error=f"{exc.response.status_code} {exc.response.reason_phrase}",
            )
        except httpx.TimeoutException:
            return FetchResult(content=None, error="Request timed out")
        except httpx.HTTPError as exc:
            return FetchResult(content=None, error=str(exc) or type(exc).__name__)

    async def close(self) -> None:
        """Close the underlying HTTP client if owned by this service."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> WebFetcherService:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
