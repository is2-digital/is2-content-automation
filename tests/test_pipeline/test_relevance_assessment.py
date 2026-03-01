"""Tests for ica.pipeline.relevance_assessment.

Tests cover:
- RelevanceResult: frozen dataclass fields
- _parse_response: JSON parsing, markdown code fences, fail-open default,
  unknown decisions, missing reason
- assess_article: LLM call with correct purpose and prompt
- assess_articles: batch processing, sequential execution
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ica.config.llm_config import LLMPurpose
from ica.pipeline.relevance_assessment import (
    RelevanceResult,
    _parse_response,
    assess_article,
    assess_articles,
)

# ===========================================================================
# RelevanceResult dataclass
# ===========================================================================


class TestRelevanceResult:
    """Tests for the RelevanceResult frozen dataclass."""

    def test_fields(self) -> None:
        result = RelevanceResult(url="https://a.com", decision="accept", reason="good")
        assert result.url == "https://a.com"
        assert result.decision == "accept"
        assert result.reason == "good"

    def test_is_frozen(self) -> None:
        result = RelevanceResult(url="https://a.com", decision="accept", reason="good")
        with pytest.raises(AttributeError):
            result.decision = "reject"  # type: ignore[misc]


# ===========================================================================
# _parse_response
# ===========================================================================


class TestParseResponse:
    """Tests for the _parse_response private function."""

    def test_valid_accept_json(self) -> None:
        text = '{"decision": "accept", "reason": "Relevant to SMB audience"}'
        result = _parse_response(text, url="https://a.com")
        assert result.decision == "accept"
        assert result.reason == "Relevant to SMB audience"
        assert result.url == "https://a.com"

    def test_valid_reject_json(self) -> None:
        text = '{"decision": "reject", "reason": "Too academic"}'
        result = _parse_response(text, url="https://a.com")
        assert result.decision == "reject"
        assert result.reason == "Too academic"

    def test_strips_markdown_code_fences(self) -> None:
        text = '```json\n{"decision": "accept", "reason": "Good fit"}\n```'
        result = _parse_response(text, url="https://a.com")
        assert result.decision == "accept"
        assert result.reason == "Good fit"

    def test_strips_bare_code_fences(self) -> None:
        text = '```\n{"decision": "reject", "reason": "Not relevant"}\n```'
        result = _parse_response(text, url="https://a.com")
        assert result.decision == "reject"

    def test_handles_whitespace(self) -> None:
        text = '  \n  {"decision": "accept", "reason": "OK"}  \n  '
        result = _parse_response(text, url="https://a.com")
        assert result.decision == "accept"

    def test_malformed_json_defaults_to_accept(self) -> None:
        text = "This is not JSON at all"
        result = _parse_response(text, url="https://a.com")
        assert result.decision == "accept"
        assert "Parse error" in result.reason

    def test_empty_string_defaults_to_accept(self) -> None:
        result = _parse_response("", url="https://a.com")
        assert result.decision == "accept"

    def test_unknown_decision_defaults_to_accept(self) -> None:
        text = '{"decision": "maybe", "reason": "Unclear"}'
        result = _parse_response(text, url="https://a.com")
        assert result.decision == "accept"
        assert result.reason == "Unclear"

    def test_decision_case_insensitive(self) -> None:
        text = '{"decision": "REJECT", "reason": "Nope"}'
        result = _parse_response(text, url="https://a.com")
        assert result.decision == "reject"

    def test_decision_with_whitespace(self) -> None:
        text = '{"decision": "  accept  ", "reason": "Fine"}'
        result = _parse_response(text, url="https://a.com")
        assert result.decision == "accept"

    def test_missing_reason_gets_default(self) -> None:
        text = '{"decision": "accept"}'
        result = _parse_response(text, url="https://a.com")
        assert result.reason == "No reason provided"

    def test_empty_reason_gets_default(self) -> None:
        text = '{"decision": "accept", "reason": ""}'
        result = _parse_response(text, url="https://a.com")
        assert result.reason == "No reason provided"

    def test_whitespace_only_reason_gets_default(self) -> None:
        text = '{"decision": "accept", "reason": "   "}'
        result = _parse_response(text, url="https://a.com")
        assert result.reason == "No reason provided"

    def test_missing_decision_defaults_to_accept(self) -> None:
        text = '{"reason": "Some reason"}'
        result = _parse_response(text, url="https://a.com")
        assert result.decision == "accept"
        assert result.reason == "Some reason"

    def test_url_passed_through(self) -> None:
        text = '{"decision": "reject", "reason": "Bad"}'
        result = _parse_response(text, url="https://specific-url.com/article")
        assert result.url == "https://specific-url.com/article"

    def test_extra_fields_ignored(self) -> None:
        text = '{"decision": "accept", "reason": "Good", "score": 0.9, "extra": true}'
        result = _parse_response(text, url="https://a.com")
        assert result.decision == "accept"
        assert result.reason == "Good"


# ===========================================================================
# assess_article
# ===========================================================================


class TestAssessArticle:
    """Tests for the assess_article async function."""

    @patch("ica.pipeline.relevance_assessment.completion")
    @patch("ica.pipeline.relevance_assessment.build_relevance_prompt")
    async def test_calls_llm_with_correct_purpose(
        self, mock_prompt: AsyncMock, mock_completion: AsyncMock
    ) -> None:
        mock_prompt.return_value = ("system", "user")
        mock_completion.return_value = AsyncMock(
            text='{"decision": "accept", "reason": "Good"}'
        )

        await assess_article("Title", "Excerpt", "https://a.com")

        mock_completion.assert_awaited_once()
        call_kwargs = mock_completion.call_args.kwargs
        assert call_kwargs["purpose"] == LLMPurpose.RELEVANCE_ASSESSMENT
        assert call_kwargs["system_prompt"] == "system"
        assert call_kwargs["user_prompt"] == "user"
        assert call_kwargs["step"] == "relevance_assessment"

    @patch("ica.pipeline.relevance_assessment.completion")
    @patch("ica.pipeline.relevance_assessment.build_relevance_prompt")
    async def test_passes_title_and_excerpt_to_prompt_builder(
        self, mock_prompt: AsyncMock, mock_completion: AsyncMock
    ) -> None:
        mock_prompt.return_value = ("sys", "usr")
        mock_completion.return_value = AsyncMock(
            text='{"decision": "accept", "reason": "OK"}'
        )

        await assess_article("My Title", "My Excerpt", "https://a.com")

        mock_prompt.assert_called_once_with(title="My Title", excerpt="My Excerpt")

    @patch("ica.pipeline.relevance_assessment.completion")
    @patch("ica.pipeline.relevance_assessment.build_relevance_prompt")
    async def test_returns_accept_result(
        self, mock_prompt: AsyncMock, mock_completion: AsyncMock
    ) -> None:
        mock_prompt.return_value = ("sys", "usr")
        mock_completion.return_value = AsyncMock(
            text='{"decision": "accept", "reason": "Relevant article"}'
        )

        result = await assess_article("Title", "Excerpt", "https://a.com")

        assert result.decision == "accept"
        assert result.reason == "Relevant article"
        assert result.url == "https://a.com"

    @patch("ica.pipeline.relevance_assessment.completion")
    @patch("ica.pipeline.relevance_assessment.build_relevance_prompt")
    async def test_returns_reject_result(
        self, mock_prompt: AsyncMock, mock_completion: AsyncMock
    ) -> None:
        mock_prompt.return_value = ("sys", "usr")
        mock_completion.return_value = AsyncMock(
            text='{"decision": "reject", "reason": "Not relevant"}'
        )

        result = await assess_article("Title", "Excerpt", "https://a.com")

        assert result.decision == "reject"
        assert result.reason == "Not relevant"

    @patch("ica.pipeline.relevance_assessment.completion")
    @patch("ica.pipeline.relevance_assessment.build_relevance_prompt")
    async def test_model_override_passed_through(
        self, mock_prompt: AsyncMock, mock_completion: AsyncMock
    ) -> None:
        mock_prompt.return_value = ("sys", "usr")
        mock_completion.return_value = AsyncMock(
            text='{"decision": "accept", "reason": "OK"}'
        )

        await assess_article("Title", "Excerpt", "https://a.com", model="custom/model")

        call_kwargs = mock_completion.call_args.kwargs
        assert call_kwargs["model"] == "custom/model"

    @patch("ica.pipeline.relevance_assessment.completion")
    @patch("ica.pipeline.relevance_assessment.build_relevance_prompt")
    async def test_fail_open_on_malformed_response(
        self, mock_prompt: AsyncMock, mock_completion: AsyncMock
    ) -> None:
        mock_prompt.return_value = ("sys", "usr")
        mock_completion.return_value = AsyncMock(text="Not JSON")

        result = await assess_article("Title", "Excerpt", "https://a.com")

        assert result.decision == "accept"
        assert "Parse error" in result.reason


# ===========================================================================
# assess_articles (batch)
# ===========================================================================


class TestAssessArticles:
    """Tests for the assess_articles batch function."""

    @patch("ica.pipeline.relevance_assessment.assess_article")
    async def test_processes_all_articles(self, mock_assess: AsyncMock) -> None:
        mock_assess.side_effect = [
            RelevanceResult(url="https://a.com", decision="accept", reason="Good"),
            RelevanceResult(url="https://b.com", decision="reject", reason="Bad"),
            RelevanceResult(url="https://c.com", decision="accept", reason="OK"),
        ]

        results = await assess_articles([
            ("https://a.com", "Title A", "Excerpt A"),
            ("https://b.com", "Title B", "Excerpt B"),
            ("https://c.com", "Title C", "Excerpt C"),
        ])

        assert len(results) == 3
        assert results[0].decision == "accept"
        assert results[1].decision == "reject"
        assert results[2].decision == "accept"

    @patch("ica.pipeline.relevance_assessment.assess_article")
    async def test_empty_input(self, mock_assess: AsyncMock) -> None:
        results = await assess_articles([])
        assert results == []
        mock_assess.assert_not_awaited()

    @patch("ica.pipeline.relevance_assessment.assess_article")
    async def test_passes_correct_args(self, mock_assess: AsyncMock) -> None:
        mock_assess.return_value = RelevanceResult(
            url="https://a.com", decision="accept", reason="OK"
        )

        await assess_articles(
            [("https://a.com", "The Title", "The Excerpt")],
            model="custom/model",
        )

        mock_assess.assert_awaited_once_with(
            title="The Title",
            excerpt="The Excerpt",
            url="https://a.com",
            model="custom/model",
        )

    @patch("ica.pipeline.relevance_assessment.assess_article")
    async def test_sequential_execution(self, mock_assess: AsyncMock) -> None:
        """Articles are assessed one at a time, not concurrently."""
        call_order: list[str] = []

        async def track_calls(**kwargs: str) -> RelevanceResult:
            call_order.append(kwargs["url"])
            return RelevanceResult(url=kwargs["url"], decision="accept", reason="OK")

        mock_assess.side_effect = track_calls

        await assess_articles([
            ("https://first.com", "First", ""),
            ("https://second.com", "Second", ""),
        ])

        assert call_order == ["https://first.com", "https://second.com"]
