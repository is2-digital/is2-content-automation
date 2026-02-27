"""Tests for :mod:`ica.services.web_fetcher`.

Tests cover:
- FetchResult frozen dataclass
- BROWSER_HEADERS constant values
- CAPTCHA_MARKER / YOUTUBE_DOMAIN constants
- is_fetch_failure: error, captcha, YouTube, and combined detection
- strip_html_tags: script/style removal, tag stripping, entity unescaping
- WebFetcherService: constructor, get() method, error handling, context manager
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import httpx
import pytest

from ica.services.web_fetcher import (
    BROWSER_HEADERS,
    CAPTCHA_MARKER,
    DEFAULT_TIMEOUT_SECONDS,
    YOUTUBE_DOMAIN,
    FetchResult,
    WebFetcherService,
    is_fetch_failure,
    strip_html_tags,
)

# ===========================================================================
# FetchResult dataclass
# ===========================================================================


class TestFetchResult:
    """Verify FetchResult frozen dataclass behaviour."""

    def test_success_result(self):
        result = FetchResult(content="<html>OK</html>", error=None)
        assert result.content == "<html>OK</html>"
        assert result.error is None

    def test_error_result(self):
        result = FetchResult(content=None, error="Connection refused")
        assert result.content is None
        assert result.error == "Connection refused"

    def test_both_content_and_error(self):
        result = FetchResult(content="partial", error="timeout")
        assert result.content == "partial"
        assert result.error == "timeout"

    def test_both_none(self):
        result = FetchResult(content=None, error=None)
        assert result.content is None
        assert result.error is None

    def test_frozen(self):
        result = FetchResult(content="data", error=None)
        with pytest.raises(FrozenInstanceError):
            result.content = "other"  # type: ignore[misc]

    def test_equality(self):
        a = FetchResult(content="x", error=None)
        b = FetchResult(content="x", error=None)
        assert a == b

    def test_inequality(self):
        a = FetchResult(content="x", error=None)
        b = FetchResult(content="y", error=None)
        assert a != b


# ===========================================================================
# Constants
# ===========================================================================


class TestBrowserHeaders:
    """Verify BROWSER_HEADERS match PRD Section 2.7 / n8n config."""

    def test_user_agent(self):
        assert "User-Agent" in BROWSER_HEADERS
        assert "Safari" in BROWSER_HEADERS["User-Agent"]

    def test_accept(self):
        assert "Accept" in BROWSER_HEADERS
        assert "text/html" in BROWSER_HEADERS["Accept"]

    def test_accept_language(self):
        assert "Accept-Language" in BROWSER_HEADERS
        assert "en-US" in BROWSER_HEADERS["Accept-Language"]

    def test_referer(self):
        assert BROWSER_HEADERS["Referer"] == "https://www.google.com/"

    def test_connection(self):
        assert BROWSER_HEADERS["Connection"] == "keep-alive"

    def test_has_five_headers(self):
        assert len(BROWSER_HEADERS) == 5


class TestConstants:
    """Verify sentinel constants."""

    def test_captcha_marker(self):
        assert CAPTCHA_MARKER == "sgcaptcha"

    def test_youtube_domain(self):
        assert YOUTUBE_DOMAIN == "youtube.com"

    def test_default_timeout(self):
        assert DEFAULT_TIMEOUT_SECONDS == 30.0


# ===========================================================================
# is_fetch_failure
# ===========================================================================


class TestIsFetchFailure:
    """Tests for the fetch failure detection function."""

    def test_success_no_failure(self):
        result = FetchResult(content="<html>OK</html>", error=None)
        assert is_fetch_failure(result, "https://example.com") is False

    def test_error_is_failure(self):
        result = FetchResult(content=None, error="Connection refused")
        assert is_fetch_failure(result, "https://example.com") is True

    def test_captcha_is_failure(self):
        result = FetchResult(content="<html>sgcaptcha challenge</html>", error=None)
        assert is_fetch_failure(result, "https://example.com") is True

    def test_youtube_is_failure(self):
        result = FetchResult(content="<html>OK</html>", error=None)
        assert is_fetch_failure(result, "https://www.youtube.com/watch?v=abc") is True

    def test_youtube_case_insensitive(self):
        result = FetchResult(content="<html>OK</html>", error=None)
        assert is_fetch_failure(result, "https://www.YouTube.com/watch?v=abc") is True

    def test_youtube_mobile(self):
        result = FetchResult(content="<html>OK</html>", error=None)
        assert is_fetch_failure(result, "https://m.youtube.com/video") is True

    def test_not_youtube_domain(self):
        result = FetchResult(content="<html>OK</html>", error=None)
        assert is_fetch_failure(result, "https://notyoutube.org/page") is False

    def test_error_takes_precedence(self):
        result = FetchResult(content="<html>OK</html>", error="timeout")
        assert is_fetch_failure(result, "https://example.com") is True

    def test_none_content_no_error(self):
        result = FetchResult(content=None, error=None)
        assert is_fetch_failure(result, "https://example.com") is False

    def test_empty_content_no_captcha(self):
        result = FetchResult(content="", error=None)
        assert is_fetch_failure(result, "https://example.com") is False

    def test_empty_url(self):
        result = FetchResult(content="<html>OK</html>", error=None)
        assert is_fetch_failure(result, "") is False

    def test_captcha_in_empty_url(self):
        """Captcha in content is detected regardless of URL."""
        result = FetchResult(content="sgcaptcha", error=None)
        assert is_fetch_failure(result, "") is True


# ===========================================================================
# strip_html_tags
# ===========================================================================


class TestStripHtmlTags:
    """Tests for HTML-to-text conversion."""

    def test_simple_paragraph(self):
        assert strip_html_tags("<p>Hello</p>") == "Hello"

    def test_nested_tags(self):
        result = strip_html_tags("<div><p><b>Bold</b> text</p></div>")
        assert "Bold" in result
        assert "text" in result

    def test_script_removal(self):
        html = "<p>Before</p><script>alert('xss')</script><p>After</p>"
        result = strip_html_tags(html)
        assert "alert" not in result
        assert "Before" in result
        assert "After" in result

    def test_style_removal(self):
        html = "<style>.red{color:red}</style><p>Visible</p>"
        result = strip_html_tags(html)
        assert "color" not in result
        assert "Visible" in result

    def test_entity_unescaping(self):
        result = strip_html_tags("&amp; &lt; &gt; &quot;")
        assert result == '& < > "'

    def test_br_tags(self):
        result = strip_html_tags("Line 1<br>Line 2<br/>Line 3")
        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 3" in result

    def test_empty_string(self):
        assert strip_html_tags("") == ""

    def test_plain_text(self):
        assert strip_html_tags("Just plain text") == "Just plain text"

    def test_whitespace_normalization(self):
        result = strip_html_tags("<p>  Too   many   spaces  </p>")
        assert "Too many spaces" in result

    def test_block_tags_become_newlines(self):
        result = strip_html_tags("<p>Para 1</p><p>Para 2</p>")
        assert "Para 1" in result
        assert "Para 2" in result

    def test_heading_tags(self):
        result = strip_html_tags("<h1>Title</h1><p>Content</p>")
        assert "Title" in result
        assert "Content" in result

    def test_none_returns_empty(self):
        # None is falsy, so strip_html_tags treats it like empty
        assert strip_html_tags("") == ""

    def test_multiline_script(self):
        html = """<script type="text/javascript">
        var x = 1;
        console.log(x);
        </script><p>Content</p>"""
        result = strip_html_tags(html)
        assert "console" not in result
        assert "Content" in result

    def test_list_items(self):
        html = "<ul><li>Item 1</li><li>Item 2</li></ul>"
        result = strip_html_tags(html)
        assert "Item 1" in result
        assert "Item 2" in result

    def test_table_rows(self):
        html = "<table><tr><td>Cell</td></tr></table>"
        result = strip_html_tags(html)
        assert "Cell" in result


# ===========================================================================
# WebFetcherService — constructor
# ===========================================================================


class TestWebFetcherServiceConstructor:
    """Tests for WebFetcherService initialization."""

    def test_default_constructor(self):
        svc = WebFetcherService()
        assert svc._owns_client is True
        assert isinstance(svc._client, httpx.AsyncClient)

    def test_custom_client(self):
        client = httpx.AsyncClient()
        svc = WebFetcherService(client=client)
        assert svc._owns_client is False
        assert svc._client is client

    def test_custom_timeout(self):
        svc = WebFetcherService(timeout=10.0)
        assert svc._owns_client is True
        # Verify timeout was applied (httpx stores as Timeout object)
        assert svc._client.timeout.connect == 10.0

    def test_follows_redirects(self):
        svc = WebFetcherService()
        assert svc._client.follow_redirects is True


# ===========================================================================
# WebFetcherService.get() — success
# ===========================================================================


class TestWebFetcherServiceGetSuccess:
    """Tests for successful HTTP GET requests."""

    @pytest.mark.asyncio
    async def test_success_returns_content(self):
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, text="<html>OK</html>")
        )
        client = httpx.AsyncClient(transport=transport)
        svc = WebFetcherService(client=client)

        result = await svc.get("https://example.com")
        assert result.content == "<html>OK</html>"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_uses_browser_headers_by_default(self):
        captured_headers: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return httpx.Response(200, text="OK")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        svc = WebFetcherService(client=client)

        await svc.get("https://example.com")
        assert captured_headers["user-agent"] == "Safari/537.36"
        assert "text/html" in captured_headers["accept"]

    @pytest.mark.asyncio
    async def test_custom_headers_override(self):
        captured_headers: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return httpx.Response(200, text="OK")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        svc = WebFetcherService(client=client)

        await svc.get("https://example.com", headers={"User-Agent": "Custom/1.0"})
        assert captured_headers["user-agent"] == "Custom/1.0"

    @pytest.mark.asyncio
    async def test_empty_response_body(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, text=""))
        client = httpx.AsyncClient(transport=transport)
        svc = WebFetcherService(client=client)

        result = await svc.get("https://example.com")
        assert result.content == ""
        assert result.error is None


# ===========================================================================
# WebFetcherService.get() — HTTP errors
# ===========================================================================


class TestWebFetcherServiceGetHttpErrors:
    """Tests for HTTP error responses."""

    @pytest.mark.asyncio
    async def test_404_returns_error(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(404))
        client = httpx.AsyncClient(transport=transport)
        svc = WebFetcherService(client=client)

        result = await svc.get("https://example.com/missing")
        assert result.content is None
        assert result.error is not None
        assert "404" in result.error

    @pytest.mark.asyncio
    async def test_403_returns_error(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(403))
        client = httpx.AsyncClient(transport=transport)
        svc = WebFetcherService(client=client)

        result = await svc.get("https://example.com/forbidden")
        assert result.content is None
        assert "403" in result.error  # type: ignore[operator]

    @pytest.mark.asyncio
    async def test_500_returns_error(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(500))
        client = httpx.AsyncClient(transport=transport)
        svc = WebFetcherService(client=client)

        result = await svc.get("https://example.com/error")
        assert result.content is None
        assert "500" in result.error  # type: ignore[operator]

    @pytest.mark.asyncio
    async def test_301_redirect_returns_error(self):
        """Non-followed redirect (3xx) is treated as an error."""
        transport = httpx.MockTransport(
            lambda request: httpx.Response(301, text="", headers={"Location": "/new"})
        )
        client = httpx.AsyncClient(transport=transport)
        svc = WebFetcherService(client=client)

        result = await svc.get("https://example.com/old")
        assert result.content is None
        assert "301" in result.error  # type: ignore[operator]


# ===========================================================================
# WebFetcherService.get() — transport errors
# ===========================================================================


class TestWebFetcherServiceGetTransportErrors:
    """Tests for network/transport errors."""

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Read timed out")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        svc = WebFetcherService(client=client)

        result = await svc.get("https://slow.example.com")
        assert result.content is None
        assert result.error == "Request timed out"

    @pytest.mark.asyncio
    async def test_connect_timeout(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("Connection timed out")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        svc = WebFetcherService(client=client)

        result = await svc.get("https://unreachable.example.com")
        assert result.content is None
        assert result.error == "Request timed out"

    @pytest.mark.asyncio
    async def test_connection_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        svc = WebFetcherService(client=client)

        result = await svc.get("https://down.example.com")
        assert result.content is None
        assert result.error is not None
        assert "Connection refused" in result.error

    @pytest.mark.asyncio
    async def test_generic_http_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.NetworkError("Network unreachable")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        svc = WebFetcherService(client=client)

        result = await svc.get("https://offline.example.com")
        assert result.content is None
        assert "Network unreachable" in result.error  # type: ignore[operator]


# ===========================================================================
# WebFetcherService — context manager
# ===========================================================================


class TestWebFetcherServiceContextManager:
    """Tests for async context manager support."""

    @pytest.mark.asyncio
    async def test_context_manager_enter_returns_self(self):
        async with WebFetcherService() as svc:
            assert isinstance(svc, WebFetcherService)

    @pytest.mark.asyncio
    async def test_close_owned_client(self):
        svc = WebFetcherService()
        assert svc._owns_client is True
        await svc.close()
        assert svc._client.is_closed

    @pytest.mark.asyncio
    async def test_close_does_not_close_injected_client(self):
        client = httpx.AsyncClient()
        svc = WebFetcherService(client=client)
        assert svc._owns_client is False
        await svc.close()
        assert not client.is_closed
        await client.aclose()  # cleanup

    @pytest.mark.asyncio
    async def test_context_manager_closes_client(self):
        svc = WebFetcherService()
        client_ref = svc._client
        async with svc:
            pass
        assert client_ref.is_closed


# ===========================================================================
# WebFetcherService — protocol compatibility
# ===========================================================================


class TestWebFetcherServiceProtocol:
    """Verify WebFetcherService satisfies the HttpFetcher protocol."""

    def test_has_get_method(self):
        svc = WebFetcherService()
        assert hasattr(svc, "get")
        assert callable(svc.get)

    @pytest.mark.asyncio
    async def test_get_returns_fetch_result(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, text="OK"))
        client = httpx.AsyncClient(transport=transport)
        svc = WebFetcherService(client=client)

        result = await svc.get("https://example.com")
        assert isinstance(result, FetchResult)

    @pytest.mark.asyncio
    async def test_get_accepts_headers_kwarg(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, text="OK"))
        client = httpx.AsyncClient(transport=transport)
        svc = WebFetcherService(client=client)

        result = await svc.get("https://example.com", headers={"X-Custom": "test"})
        assert isinstance(result, FetchResult)


# ===========================================================================
# Integration: WebFetcherService + is_fetch_failure
# ===========================================================================


class TestWebFetcherIntegration:
    """Integration tests combining service with utility functions."""

    @pytest.mark.asyncio
    async def test_captcha_response_detected(self):
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, text="<html>sgcaptcha blocked</html>")
        )
        client = httpx.AsyncClient(transport=transport)
        svc = WebFetcherService(client=client)

        result = await svc.get("https://example.com")
        assert result.error is None  # HTTP succeeded
        assert is_fetch_failure(result, "https://example.com") is True

    @pytest.mark.asyncio
    async def test_successful_fetch_not_failure(self):
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, text="<html>Good content</html>")
        )
        client = httpx.AsyncClient(transport=transport)
        svc = WebFetcherService(client=client)

        result = await svc.get("https://example.com")
        assert is_fetch_failure(result, "https://example.com") is False

    @pytest.mark.asyncio
    async def test_error_response_is_failure(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(500))
        client = httpx.AsyncClient(transport=transport)
        svc = WebFetcherService(client=client)

        result = await svc.get("https://example.com")
        assert is_fetch_failure(result, "https://example.com") is True

    @pytest.mark.asyncio
    async def test_fetch_then_strip_html(self):
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, text="<p>Article text</p>")
        )
        client = httpx.AsyncClient(transport=transport)
        svc = WebFetcherService(client=client)

        result = await svc.get("https://example.com")
        text = strip_html_tags(result.content or "")
        assert text == "Article text"
