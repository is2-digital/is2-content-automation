"""Tests for the per-article summarization loop (Step 2, second half).

Tests cover:
- FetchResult / ArticleSummary / SummarizationLoopResult dataclasses
- BROWSER_HEADERS: constants match n8n configuration
- is_fetch_failure: error detection, captcha detection, YouTube detection
- build_manual_fallback_message: Slack message formatting
- strip_html_tags: HTML-to-text conversion
- build_article_input: URL + title + content concatenation
- aggregate_feedback: Note rows to bullet-point list
- parse_summary_output: regex extraction of URL/Title/Summary/BusinessRelevance
- call_summary_llm: LLM invocation with correct prompt building
- summarize_single_article: full single-article flow with mocked dependencies
- summarize_articles: orchestrated loop over multiple articles
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ica.pipeline.summarization import (
    BROWSER_HEADERS,
    ArticleSummary,
    CuratedArticle,
    FetchResult,
    SummarizationLoopResult,
    aggregate_feedback,
    build_article_input,
    build_manual_fallback_message,
    call_summary_llm,
    is_fetch_failure,
    parse_summary_output,
    strip_html_tags,
    summarize_articles,
    summarize_single_article,
)
from ica.services.web_fetcher import CAPTCHA_MARKER, YOUTUBE_DOMAIN

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_article(
    *,
    url: str = "https://example.com/article",
    title: str = "Test Article",
    publish_date: date | None = date(2026, 2, 15),
    origin: str = "google_news",
    approved: bool = True,
    newsletter_id: str = "NL-001",
    industry_news: bool = False,
) -> CuratedArticle:
    return CuratedArticle(
        url=url,
        title=title,
        publish_date=publish_date,
        origin=origin,
        approved=approved,
        newsletter_id=newsletter_id,
        industry_news=industry_news,
    )


def _make_fetch_result(
    content: str | None = "<html><body>Article text</body></html>",
    error: str | None = None,
) -> FetchResult:
    return FetchResult(content=content, error=error)


def _make_note(text: str) -> MagicMock:
    """Create a mock Note with feedback_text."""
    note = MagicMock()
    note.feedback_text = text
    return note


_SAMPLE_LLM_OUTPUT = """\
URL: https://example.com/article
Title: AI Advances in 2026
Summary: Researchers have made significant progress in AI. New models show improved performance.
Business Relevance: These advances could transform business operations. Prepare for integration."""


class FakeHttpFetcher:
    """Records HTTP calls and returns preset data."""

    def __init__(self, result: FetchResult | None = None) -> None:
        self.result = result or _make_fetch_result()
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    async def get(self, url: str, *, headers: dict[str, str] | None = None) -> FetchResult:
        self.calls.append((url, headers))
        return self.result


class FakeSlackFallback:
    """Records Slack calls and returns preset content."""

    def __init__(self, response: str = "Manually pasted article content") -> None:
        self.response = response
        self.calls: list[tuple[str, str, str, str]] = []

    async def send_and_wait_freetext(
        self,
        message: str,
        *,
        button_label: str = "Add Article Content",
        form_title: str = "Please provide article or blog data",
        form_description: str = "",
    ) -> str:
        self.calls.append((message, button_label, form_title, form_description))
        return self.response


# ===================================================================
# Constants
# ===================================================================


class TestBrowserHeaders:
    """Tests for BROWSER_HEADERS constants."""

    def test_has_user_agent(self) -> None:
        assert "User-Agent" in BROWSER_HEADERS

    def test_user_agent_safari(self) -> None:
        assert "Safari" in BROWSER_HEADERS["User-Agent"]

    def test_has_accept(self) -> None:
        assert "Accept" in BROWSER_HEADERS

    def test_has_accept_language(self) -> None:
        assert "Accept-Language" in BROWSER_HEADERS

    def test_has_referer(self) -> None:
        assert BROWSER_HEADERS["Referer"] == "https://www.google.com/"

    def test_has_connection(self) -> None:
        assert BROWSER_HEADERS["Connection"] == "keep-alive"

    def test_captcha_marker(self) -> None:
        assert CAPTCHA_MARKER == "sgcaptcha"

    def test_youtube_domain(self) -> None:
        assert YOUTUBE_DOMAIN == "youtube.com"


# ===================================================================
# FetchResult dataclass
# ===================================================================


class TestFetchResult:
    """Tests for the FetchResult frozen dataclass."""

    def test_frozen(self) -> None:
        result = FetchResult(content="html", error=None)
        with pytest.raises(AttributeError):
            result.content = "changed"  # type: ignore[misc]

    def test_success(self) -> None:
        result = FetchResult(content="<html>data</html>", error=None)
        assert result.content == "<html>data</html>"
        assert result.error is None

    def test_failure(self) -> None:
        result = FetchResult(content=None, error="Connection refused")
        assert result.content is None
        assert result.error == "Connection refused"

    def test_both_set(self) -> None:
        """Captcha case: content exists but contains marker."""
        result = FetchResult(content="<html>sgcaptcha</html>", error=None)
        assert result.content is not None
        assert result.error is None


# ===================================================================
# ArticleSummary dataclass
# ===================================================================


class TestArticleSummary:
    """Tests for the ArticleSummary frozen dataclass."""

    def test_frozen(self) -> None:
        summary = ArticleSummary(
            url="https://a.com",
            title="Title",
            summary="Summary text",
            business_relevance="Relevance text",
            order=1,
            newsletter_id="NL-001",
            industry_news=False,
        )
        with pytest.raises(AttributeError):
            summary.title = "changed"  # type: ignore[misc]

    def test_fields(self) -> None:
        summary = ArticleSummary(
            url="https://a.com",
            title="Title",
            summary="Summary text",
            business_relevance="Relevance text",
            order=3,
            newsletter_id="NL-042",
            industry_news=True,
        )
        assert summary.url == "https://a.com"
        assert summary.title == "Title"
        assert summary.summary == "Summary text"
        assert summary.business_relevance == "Relevance text"
        assert summary.order == 3
        assert summary.newsletter_id == "NL-042"
        assert summary.industry_news is True

    def test_equality(self) -> None:
        kwargs = dict(
            url="https://a.com",
            title="Title",
            summary="Sum",
            business_relevance="Biz",
            order=1,
            newsletter_id="NL-001",
            industry_news=False,
        )
        assert ArticleSummary(**kwargs) == ArticleSummary(**kwargs)


# ===================================================================
# SummarizationLoopResult dataclass
# ===================================================================


class TestSummarizationLoopResult:
    """Tests for the SummarizationLoopResult frozen dataclass."""

    def test_frozen(self) -> None:
        result = SummarizationLoopResult(summaries=[], model="test")
        with pytest.raises(AttributeError):
            result.model = "changed"  # type: ignore[misc]

    def test_fields(self) -> None:
        summaries = [
            ArticleSummary(
                url="https://a.com",
                title="A",
                summary="S",
                business_relevance="B",
                order=1,
                newsletter_id="NL-001",
                industry_news=False,
            )
        ]
        result = SummarizationLoopResult(summaries=summaries, model="test-model")
        assert len(result.summaries) == 1
        assert result.model == "test-model"


# ===================================================================
# is_fetch_failure
# ===================================================================


class TestIsFetchFailure:
    """Tests for fetch failure detection."""

    def test_success(self) -> None:
        result = _make_fetch_result(content="<html>OK</html>", error=None)
        assert is_fetch_failure(result, "https://example.com") is False

    def test_error_present(self) -> None:
        result = _make_fetch_result(content=None, error="Connection refused")
        assert is_fetch_failure(result, "https://example.com") is True

    def test_captcha_in_content(self) -> None:
        result = _make_fetch_result(content="<html>sgcaptcha challenge</html>")
        assert is_fetch_failure(result, "https://example.com") is True

    def test_captcha_case_sensitive(self) -> None:
        """Captcha marker check is case-sensitive (matches n8n)."""
        result = _make_fetch_result(content="<html>SGCAPTCHA</html>")
        assert is_fetch_failure(result, "https://example.com") is False

    def test_youtube_url(self) -> None:
        result = _make_fetch_result(content="<html>OK</html>")
        assert is_fetch_failure(result, "https://www.youtube.com/watch?v=abc") is True

    def test_youtube_case_insensitive(self) -> None:
        result = _make_fetch_result(content="<html>OK</html>")
        assert is_fetch_failure(result, "https://www.YouTube.com/watch?v=abc") is True

    def test_youtube_in_path(self) -> None:
        """URL containing youtube.com anywhere is treated as failure."""
        result = _make_fetch_result(content="<html>OK</html>")
        assert is_fetch_failure(result, "https://m.youtube.com/video") is True

    def test_youtube_partial_domain_ok(self) -> None:
        """A URL with 'youtube' but not 'youtube.com' is OK."""
        result = _make_fetch_result(content="<html>OK</html>")
        assert is_fetch_failure(result, "https://notyoutube.org/page") is False

    def test_error_takes_priority(self) -> None:
        """Error is checked first regardless of content."""
        result = FetchResult(content="<html>OK</html>", error="timeout")
        assert is_fetch_failure(result, "https://example.com") is True

    def test_null_content_no_error(self) -> None:
        """None content without error is still a success (unlikely but safe)."""
        result = FetchResult(content=None, error=None)
        assert is_fetch_failure(result, "https://example.com") is False

    def test_empty_content(self) -> None:
        """Empty string content is not a failure."""
        result = FetchResult(content="", error=None)
        assert is_fetch_failure(result, "https://example.com") is False

    def test_empty_url(self) -> None:
        result = _make_fetch_result(content="<html>OK</html>")
        assert is_fetch_failure(result, "") is False


# ===================================================================
# build_manual_fallback_message
# ===================================================================


class TestBuildManualFallbackMessage:
    """Tests for Slack manual fallback message construction."""

    def test_contains_url(self) -> None:
        msg = build_manual_fallback_message("https://example.com/article")
        assert "https://example.com/article" in msg

    def test_bold_formatting(self) -> None:
        msg = build_manual_fallback_message("https://example.com")
        assert "*URL:*" in msg

    def test_link_emoji(self) -> None:
        msg = build_manual_fallback_message("https://example.com")
        assert "\U0001f517" in msg

    def test_instruction_text(self) -> None:
        msg = build_manual_fallback_message("https://example.com")
        assert "Please provide article or blog data" in msg


# ===================================================================
# strip_html_tags
# ===================================================================


class TestStripHtmlTags:
    """Tests for HTML-to-text conversion."""

    def test_basic_tags(self) -> None:
        assert strip_html_tags("<p>Hello</p>") == "Hello"

    def test_nested_tags(self) -> None:
        result = strip_html_tags("<div><p><b>Bold</b> text</p></div>")
        assert "Bold" in result
        assert "text" in result
        assert "<" not in result

    def test_script_removal(self) -> None:
        html = "<p>Before</p><script>alert('xss')</script><p>After</p>"
        result = strip_html_tags(html)
        assert "alert" not in result
        assert "Before" in result
        assert "After" in result

    def test_style_removal(self) -> None:
        html = "<style>.foo { color: red; }</style><p>Content</p>"
        result = strip_html_tags(html)
        assert "color" not in result
        assert "Content" in result

    def test_entity_unescaping(self) -> None:
        result = strip_html_tags("&amp; &lt; &gt; &quot;")
        assert result == '& < > "'

    def test_br_tags(self) -> None:
        result = strip_html_tags("Line 1<br>Line 2<br/>Line 3")
        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 3" in result

    def test_empty_string(self) -> None:
        assert strip_html_tags("") == ""

    def test_plain_text_passthrough(self) -> None:
        assert strip_html_tags("Just plain text") == "Just plain text"

    def test_whitespace_normalization(self) -> None:
        result = strip_html_tags("<p>  Too   many   spaces  </p>")
        assert "Too many spaces" in result

    def test_preserves_newlines_from_block_tags(self) -> None:
        result = strip_html_tags("<p>Para 1</p><p>Para 2</p>")
        assert "Para 1" in result
        assert "Para 2" in result

    def test_heading_tags(self) -> None:
        result = strip_html_tags("<h1>Title</h1><p>Content</p>")
        assert "Title" in result
        assert "Content" in result
        assert "<h1>" not in result

    def test_none_handled_as_empty(self) -> None:
        """Passing empty string (falsy) returns empty."""
        assert strip_html_tags("") == ""

    def test_complex_real_world(self) -> None:
        """Realistic article HTML snippet."""
        html = """
        <html>
        <head><title>AI News</title></head>
        <body>
            <h1>AI Breakthrough</h1>
            <p>Researchers at MIT have developed a new model
            that achieves <b>95% accuracy</b> on benchmarks.</p>
            <script>tracking();</script>
            <p>Read more about the <a href="/study">full study</a>.</p>
        </body>
        </html>
        """
        result = strip_html_tags(html)
        assert "AI Breakthrough" in result
        assert "95% accuracy" in result
        assert "Researchers at MIT" in result
        assert "<script>" not in result
        assert "<a " not in result


# ===================================================================
# build_article_input
# ===================================================================


class TestBuildArticleInput:
    """Tests for article input construction."""

    def test_combines_fields(self) -> None:
        result = build_article_input("https://a.com", "Title", "Content text")
        assert result == "https://a.com Title Content text"

    def test_empty_content(self) -> None:
        result = build_article_input("https://a.com", "Title", "")
        assert result == "https://a.com Title "

    def test_preserves_spaces(self) -> None:
        result = build_article_input("url", "Multi Word Title", "Body text here")
        assert result == "url Multi Word Title Body text here"


# ===================================================================
# aggregate_feedback
# ===================================================================


class TestAggregateFeedback:
    """Tests for feedback aggregation from Note rows."""

    def test_empty_list(self) -> None:
        assert aggregate_feedback([]) is None

    def test_single_note(self) -> None:
        notes = [_make_note("Improve tone")]
        result = aggregate_feedback(notes)
        assert result == "\u2022 Improve tone"

    def test_multiple_notes(self) -> None:
        notes = [_make_note("First"), _make_note("Second"), _make_note("Third")]
        result = aggregate_feedback(notes)
        assert result is not None
        lines = result.split("\n")
        assert len(lines) == 3
        assert lines[0] == "\u2022 First"
        assert lines[1] == "\u2022 Second"
        assert lines[2] == "\u2022 Third"

    def test_skips_empty_feedback(self) -> None:
        notes = [_make_note("Valid"), _make_note(""), _make_note("Also valid")]
        result = aggregate_feedback(notes)
        assert result is not None
        lines = result.split("\n")
        assert len(lines) == 2

    def test_skips_none_feedback(self) -> None:
        note = MagicMock()
        note.feedback_text = None
        notes = [_make_note("Valid"), note]
        result = aggregate_feedback(notes)
        assert result is not None
        assert result == "\u2022 Valid"

    def test_all_empty_returns_none(self) -> None:
        notes = [_make_note(""), _make_note("")]
        assert aggregate_feedback(notes) is None

    def test_uses_bullet_marker(self) -> None:
        """Uses • (bullet) marker matching n8n Aggregate Feedback node."""
        notes = [_make_note("Test")]
        result = aggregate_feedback(notes)
        assert result is not None
        assert result.startswith("\u2022")


# ===================================================================
# parse_summary_output
# ===================================================================


class TestParseSummaryOutput:
    """Tests for LLM output parsing."""

    def test_full_output(self) -> None:
        url, title, summary, business = parse_summary_output(_SAMPLE_LLM_OUTPUT)
        assert url == "https://example.com/article"
        assert title == "AI Advances in 2026"
        assert "significant progress" in summary
        assert "transform business operations" in business

    def test_missing_url(self) -> None:
        raw = "Title: Test\nSummary: S\nBusiness Relevance: B"
        url, _, _, _ = parse_summary_output(raw)
        assert url == "N/A"

    def test_missing_title(self) -> None:
        raw = "URL: https://a.com\nSummary: S\nBusiness Relevance: B"
        _, title, _, _ = parse_summary_output(raw)
        assert title == "Untitled"

    def test_missing_summary(self) -> None:
        raw = "URL: https://a.com\nTitle: T\nBusiness Relevance: B"
        _, _, summary, _ = parse_summary_output(raw)
        assert summary == "No summary available."

    def test_missing_business_relevance(self) -> None:
        raw = "URL: https://a.com\nTitle: T\nSummary: S"
        _, _, _, business = parse_summary_output(raw)
        assert business == "No business relevance available."

    def test_completely_empty(self) -> None:
        url, title, summary, business = parse_summary_output("")
        assert url == "N/A"
        assert title == "Untitled"
        assert summary == "No summary available."
        assert business == "No business relevance available."

    def test_multiline_summary(self) -> None:
        raw = (
            "URL: https://a.com\n"
            "Title: T\n"
            "Summary: Line 1.\nLine 2.\nLine 3.\n"
            "Business Relevance: B"
        )
        _, _, summary, _ = parse_summary_output(raw)
        assert "Line 1" in summary
        assert "Line 2" in summary
        assert "Line 3" in summary

    def test_multiline_business_relevance(self) -> None:
        raw = "URL: https://a.com\nTitle: T\nSummary: S\nBusiness Relevance: Line 1.\nLine 2."
        _, _, _, business = parse_summary_output(raw)
        assert "Line 1" in business
        assert "Line 2" in business

    def test_whitespace_trimmed(self) -> None:
        raw = (
            "URL:   https://a.com   \n"
            "Title:   Test Title   \n"
            "Summary:   Test summary.   \n"
            "Business Relevance:   Test biz.   "
        )
        url, title, summary, business = parse_summary_output(raw)
        assert url == "https://a.com"
        assert title == "Test Title"
        assert summary == "Test summary."
        assert business == "Test biz."

    def test_returns_four_tuple(self) -> None:
        result = parse_summary_output(_SAMPLE_LLM_OUTPUT)
        assert isinstance(result, tuple)
        assert len(result) == 4


# ===================================================================
# call_summary_llm
# ===================================================================


class TestCallSummaryLlm:
    """Tests for the LLM summarization call."""

    @pytest.mark.asyncio
    async def test_calls_litellm(self) -> None:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with (
            patch("ica.pipeline.summarization.litellm") as mock_litellm,
            patch(
                "ica.pipeline.summarization.get_model",
                return_value="test/model",
            ),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await call_summary_llm("article input")

        assert result == _SAMPLE_LLM_OUTPUT
        mock_litellm.acompletion.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_specified_model(self) -> None:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "output"

        with patch("ica.pipeline.summarization.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            await call_summary_llm("input", model="custom/model")

        call_kwargs = mock_litellm.acompletion.call_args
        assert call_kwargs.kwargs["model"] == "custom/model"

    @pytest.mark.asyncio
    async def test_includes_feedback_in_prompt(self) -> None:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "output"

        with patch("ica.pipeline.summarization.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            await call_summary_llm(
                "input",
                aggregated_feedback="\u2022 Be more concise",
                model="test/model",
            )

        call_kwargs = mock_litellm.acompletion.call_args
        messages = call_kwargs.kwargs["messages"]
        user_msg = messages[1]["content"]
        assert "Be more concise" in user_msg

    @pytest.mark.asyncio
    async def test_no_feedback(self) -> None:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "output"

        with patch("ica.pipeline.summarization.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            await call_summary_llm("input", model="test/model")

        call_kwargs = mock_litellm.acompletion.call_args
        messages = call_kwargs.kwargs["messages"]
        user_msg = messages[1]["content"]
        assert "Editorial Improvement Context" not in user_msg

    @pytest.mark.asyncio
    async def test_empty_response_raises(self) -> None:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""

        with patch("ica.pipeline.summarization.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            with pytest.raises(RuntimeError, match="empty response"):
                await call_summary_llm("input", model="test/model")

    @pytest.mark.asyncio
    async def test_whitespace_only_response_raises(self) -> None:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "   \n  "

        with patch("ica.pipeline.summarization.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            with pytest.raises(RuntimeError, match="empty response"):
                await call_summary_llm("input", model="test/model")

    @pytest.mark.asyncio
    async def test_strips_response(self) -> None:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "  trimmed output  "

        with patch("ica.pipeline.summarization.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await call_summary_llm("input", model="test/model")

        assert result == "trimmed output"

    @pytest.mark.asyncio
    async def test_system_and_user_messages(self) -> None:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "output"

        with patch("ica.pipeline.summarization.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            await call_summary_llm("article content", model="test/model")

        call_kwargs = mock_litellm.acompletion.call_args
        messages = call_kwargs.kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "article content" in messages[1]["content"]


# ===================================================================
# summarize_single_article
# ===================================================================


class TestSummarizeSingleArticle:
    """Tests for the single-article summarization flow."""

    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        """Successful fetch → convert → LLM → parse."""
        article = _make_article(url="https://example.com/ai-news", title="AI News")
        http = FakeHttpFetcher(_make_fetch_result(content="<p>Article body</p>"))

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with patch("ica.pipeline.summarization.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await summarize_single_article(
                article,
                order=1,
                http=http,
                model="test/model",
            )

        assert isinstance(result, ArticleSummary)
        assert result.url == "https://example.com/article"
        assert result.order == 1
        assert result.newsletter_id == "NL-001"
        assert result.industry_news is False

    @pytest.mark.asyncio
    async def test_passes_browser_headers(self) -> None:
        """HTTP fetch uses browser-like headers."""
        article = _make_article()
        http = FakeHttpFetcher()

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with patch("ica.pipeline.summarization.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            await summarize_single_article(article, order=1, http=http, model="test/model")

        assert len(http.calls) == 1
        _, headers = http.calls[0]
        assert headers == BROWSER_HEADERS

    @pytest.mark.asyncio
    async def test_fetch_failure_with_slack_fallback(self) -> None:
        """Fetch fails → Slack manual fallback used."""
        article = _make_article(url="https://example.com/blocked")
        http = FakeHttpFetcher(_make_fetch_result(content=None, error="403 Forbidden"))
        slack = FakeSlackFallback("Manual article content here")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with patch("ica.pipeline.summarization.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await summarize_single_article(
                article,
                order=1,
                http=http,
                slack=slack,
                model="test/model",
            )

        assert isinstance(result, ArticleSummary)
        assert len(slack.calls) == 1
        msg, _, _, desc = slack.calls[0]
        assert "https://example.com/blocked" in msg
        assert desc == "https://example.com/blocked"

    @pytest.mark.asyncio
    async def test_fetch_failure_no_slack_raises(self) -> None:
        """Fetch fails without Slack fallback → RuntimeError."""
        article = _make_article()
        http = FakeHttpFetcher(_make_fetch_result(content=None, error="timeout"))

        with pytest.raises(RuntimeError, match="no Slack fallback"):
            await summarize_single_article(article, order=1, http=http, model="test/model")

    @pytest.mark.asyncio
    async def test_youtube_triggers_fallback(self) -> None:
        """YouTube URL triggers Slack fallback even with good content."""
        article = _make_article(url="https://www.youtube.com/watch?v=abc123")
        http = FakeHttpFetcher(_make_fetch_result(content="<html>OK</html>"))
        slack = FakeSlackFallback("YouTube transcript text")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with patch("ica.pipeline.summarization.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            await summarize_single_article(
                article, order=1, http=http, slack=slack, model="test/model"
            )

        assert len(slack.calls) == 1

    @pytest.mark.asyncio
    async def test_captcha_triggers_fallback(self) -> None:
        """Captcha in response triggers Slack fallback."""
        article = _make_article()
        http = FakeHttpFetcher(_make_fetch_result(content="<html>sgcaptcha challenge</html>"))
        slack = FakeSlackFallback("Clean article text")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with patch("ica.pipeline.summarization.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            await summarize_single_article(
                article, order=1, http=http, slack=slack, model="test/model"
            )

        assert len(slack.calls) == 1

    @pytest.mark.asyncio
    async def test_manual_content_not_html_converted(self) -> None:
        """Manual Slack content is used as-is, not HTML-stripped."""
        article = _make_article(url="https://example.com/blocked")
        http = FakeHttpFetcher(_make_fetch_result(content=None, error="403"))
        manual_text = "This is <b>already</b> readable text from user"
        slack = FakeSlackFallback(manual_text)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with patch("ica.pipeline.summarization.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            await summarize_single_article(
                article, order=1, http=http, slack=slack, model="test/model"
            )

        # Verify the LLM input contains the manual text as-is
        call_kwargs = mock_litellm.acompletion.call_args
        user_msg = call_kwargs.kwargs["messages"][1]["content"]
        assert manual_text in user_msg

    @pytest.mark.asyncio
    async def test_html_content_is_stripped(self) -> None:
        """Successfully fetched HTML is stripped of tags before LLM call."""
        article = _make_article()
        http = FakeHttpFetcher(
            _make_fetch_result(content="<html><body><p>Clean text</p></body></html>")
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with patch("ica.pipeline.summarization.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            await summarize_single_article(article, order=1, http=http, model="test/model")

        call_kwargs = mock_litellm.acompletion.call_args
        user_msg = call_kwargs.kwargs["messages"][1]["content"]
        assert "<html>" not in user_msg
        assert "<body>" not in user_msg
        assert "Clean text" in user_msg

    @pytest.mark.asyncio
    async def test_preserves_newsletter_id(self) -> None:
        article = _make_article(newsletter_id="NL-042")
        http = FakeHttpFetcher()

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with patch("ica.pipeline.summarization.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await summarize_single_article(
                article, order=1, http=http, model="test/model"
            )

        assert result.newsletter_id == "NL-042"

    @pytest.mark.asyncio
    async def test_preserves_industry_news(self) -> None:
        article = _make_article(industry_news=True)
        http = FakeHttpFetcher()

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with patch("ica.pipeline.summarization.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await summarize_single_article(
                article, order=1, http=http, model="test/model"
            )

        assert result.industry_news is True

    @pytest.mark.asyncio
    async def test_passes_aggregated_feedback(self) -> None:
        article = _make_article()
        http = FakeHttpFetcher()

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with patch("ica.pipeline.summarization.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            await summarize_single_article(
                article,
                order=1,
                http=http,
                aggregated_feedback="\u2022 Be more concise",
                model="test/model",
            )

        call_kwargs = mock_litellm.acompletion.call_args
        user_msg = call_kwargs.kwargs["messages"][1]["content"]
        assert "Be more concise" in user_msg

    @pytest.mark.asyncio
    async def test_order_passed_through(self) -> None:
        article = _make_article()
        http = FakeHttpFetcher()

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with patch("ica.pipeline.summarization.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await summarize_single_article(
                article, order=5, http=http, model="test/model"
            )

        assert result.order == 5


# ===================================================================
# summarize_articles — orchestration
# ===================================================================


class TestSummarizeArticles:
    """Tests for the main per-article summarization loop."""

    @pytest.mark.asyncio
    async def test_empty_articles(self) -> None:
        http = FakeHttpFetcher()

        with patch(
            "ica.pipeline.summarization.get_model",
            return_value="test/model",
        ):
            result = await summarize_articles([], http=http)

        assert result.summaries == []
        assert result.model == "test/model"

    @pytest.mark.asyncio
    async def test_single_article(self) -> None:
        articles = [_make_article()]
        http = FakeHttpFetcher()

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with (
            patch("ica.pipeline.summarization.litellm") as mock_litellm,
            patch(
                "ica.pipeline.summarization.get_model",
                return_value="test/model",
            ),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await summarize_articles(articles, http=http)

        assert len(result.summaries) == 1
        assert result.summaries[0].order == 1
        assert result.model == "test/model"

    @pytest.mark.asyncio
    async def test_multiple_articles_sequential(self) -> None:
        """Articles are processed one at a time (splitInBatches style)."""
        articles = [_make_article(url=f"https://example.com/{i}") for i in range(3)]
        http = FakeHttpFetcher()

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with (
            patch("ica.pipeline.summarization.litellm") as mock_litellm,
            patch(
                "ica.pipeline.summarization.get_model",
                return_value="test/model",
            ),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await summarize_articles(articles, http=http)

        assert len(result.summaries) == 3
        assert mock_litellm.acompletion.call_count == 3

    @pytest.mark.asyncio
    async def test_orders_are_sequential(self) -> None:
        """Articles get 1-based sequential order numbers."""
        articles = [_make_article(url=f"https://example.com/{i}") for i in range(3)]
        http = FakeHttpFetcher()

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with (
            patch("ica.pipeline.summarization.litellm") as mock_litellm,
            patch(
                "ica.pipeline.summarization.get_model",
                return_value="test/model",
            ),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await summarize_articles(articles, http=http)

        orders = [s.order for s in result.summaries]
        assert orders == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_fetches_learning_data(self) -> None:
        """When session is provided, learning data is fetched and injected."""
        articles = [_make_article()]
        http = FakeHttpFetcher()
        session = AsyncMock()

        mock_notes = [_make_note("Be concise"), _make_note("Add numbers")]
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with (
            patch("ica.pipeline.summarization.litellm") as mock_litellm,
            patch(
                "ica.pipeline.summarization.get_model",
                return_value="test/model",
            ),
            patch(
                "ica.pipeline.summarization.get_recent_notes",
                new_callable=AsyncMock,
                return_value=mock_notes,
            ) as mock_get_notes,
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            await summarize_articles(articles, http=http, session=session)

        mock_get_notes.assert_called_once_with(session, "user_summarization")

        # Check feedback was injected into the prompt
        call_kwargs = mock_litellm.acompletion.call_args
        user_msg = call_kwargs.kwargs["messages"][1]["content"]
        assert "Be concise" in user_msg

    @pytest.mark.asyncio
    async def test_no_session_skips_feedback(self) -> None:
        """Without session, no feedback is fetched or injected."""
        articles = [_make_article()]
        http = FakeHttpFetcher()

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with (
            patch("ica.pipeline.summarization.litellm") as mock_litellm,
            patch(
                "ica.pipeline.summarization.get_model",
                return_value="test/model",
            ),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            await summarize_articles(articles, http=http, session=None)

        call_kwargs = mock_litellm.acompletion.call_args
        user_msg = call_kwargs.kwargs["messages"][1]["content"]
        assert "Editorial Improvement Context" not in user_msg

    @pytest.mark.asyncio
    async def test_uses_override_model(self) -> None:
        articles = [_make_article()]
        http = FakeHttpFetcher()

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with patch("ica.pipeline.summarization.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await summarize_articles(articles, http=http, model="custom/model")

        assert result.model == "custom/model"
        call_kwargs = mock_litellm.acompletion.call_args
        assert call_kwargs.kwargs["model"] == "custom/model"

    @pytest.mark.asyncio
    async def test_mixed_fetch_success_and_failure(self) -> None:
        """Mix of successful fetches and Slack fallbacks."""
        articles = [
            _make_article(url="https://example.com/good"),
            _make_article(url="https://www.youtube.com/watch?v=abc"),
            _make_article(url="https://example.com/also-good"),
        ]

        call_count = 0

        async def fake_get(url: str, *, headers: dict[str, str] | None = None) -> FetchResult:
            nonlocal call_count
            call_count += 1
            return _make_fetch_result(content="<p>HTML content</p>")

        http = MagicMock()
        http.get = fake_get
        slack = FakeSlackFallback("Manual YouTube content")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with (
            patch("ica.pipeline.summarization.litellm") as mock_litellm,
            patch(
                "ica.pipeline.summarization.get_model",
                return_value="test/model",
            ),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await summarize_articles(articles, http=http, slack=slack)

        assert len(result.summaries) == 3
        # YouTube article should have triggered Slack fallback
        assert len(slack.calls) == 1

    @pytest.mark.asyncio
    async def test_preserves_newsletter_ids(self) -> None:
        """Each article's newsletter_id is preserved in the summary."""
        articles = [
            _make_article(url="https://a.com", newsletter_id="NL-001"),
            _make_article(url="https://b.com", newsletter_id="NL-002"),
        ]
        http = FakeHttpFetcher()

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with (
            patch("ica.pipeline.summarization.litellm") as mock_litellm,
            patch(
                "ica.pipeline.summarization.get_model",
                return_value="test/model",
            ),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await summarize_articles(articles, http=http)

        assert result.summaries[0].newsletter_id == "NL-001"
        assert result.summaries[1].newsletter_id == "NL-002"

    @pytest.mark.asyncio
    async def test_preserves_industry_news_flags(self) -> None:
        """Each article's industry_news flag is preserved in the summary."""
        articles = [
            _make_article(url="https://a.com", industry_news=False),
            _make_article(url="https://b.com", industry_news=True),
        ]
        http = FakeHttpFetcher()

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with (
            patch("ica.pipeline.summarization.litellm") as mock_litellm,
            patch(
                "ica.pipeline.summarization.get_model",
                return_value="test/model",
            ),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await summarize_articles(articles, http=http)

        assert result.summaries[0].industry_news is False
        assert result.summaries[1].industry_news is True

    @pytest.mark.asyncio
    async def test_feedback_shared_across_articles(self) -> None:
        """Learning data is fetched once and shared across all articles."""
        articles = [
            _make_article(url="https://a.com"),
            _make_article(url="https://b.com"),
        ]
        http = FakeHttpFetcher()
        session = AsyncMock()

        mock_notes = [_make_note("Shared feedback")]
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with (
            patch("ica.pipeline.summarization.litellm") as mock_litellm,
            patch(
                "ica.pipeline.summarization.get_model",
                return_value="test/model",
            ),
            patch(
                "ica.pipeline.summarization.get_recent_notes",
                new_callable=AsyncMock,
                return_value=mock_notes,
            ) as mock_get_notes,
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            await summarize_articles(articles, http=http, session=session)

        # Learning data fetched only once
        mock_get_notes.assert_called_once()
        # Both LLM calls include the feedback
        for call in mock_litellm.acompletion.call_args_list:
            user_msg = call.kwargs["messages"][1]["content"]
            assert "Shared feedback" in user_msg

    @pytest.mark.asyncio
    async def test_http_fetches_all_articles(self) -> None:
        """Every article gets an HTTP fetch attempt."""
        articles = [
            _make_article(url="https://a.com"),
            _make_article(url="https://b.com"),
            _make_article(url="https://c.com"),
        ]
        http = FakeHttpFetcher()

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _SAMPLE_LLM_OUTPUT

        with (
            patch("ica.pipeline.summarization.litellm") as mock_litellm,
            patch(
                "ica.pipeline.summarization.get_model",
                return_value="test/model",
            ),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            await summarize_articles(articles, http=http)

        fetched_urls = [url for url, _ in http.calls]
        assert fetched_urls == [
            "https://a.com",
            "https://b.com",
            "https://c.com",
        ]
