"""Tests for summarization output formatting and feedback loop (Step 2, third part).

Tests cover:
- SummarizationOutput dataclass
- SlackSummaryReview protocol
- format_summary_slack_text: mrkdwn text building
- build_summary_slack_blocks: Slack Block Kit blocks
- build_next_steps_form: dropdown form definition
- parse_next_steps_response: dropdown value → UserChoice
- summaries_to_output_articles: PRD Section 5.2 output format
- call_regeneration_llm: feedback-based regeneration
- extract_summary_learning_data: learning data extraction with JSON parsing
- store_summarization_feedback: notes table insertion
- run_summarization_output: orchestrated output sharing and feedback loop
- Constants: Slack field labels, messages, dividers
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ica.config.llm_config import LLMPurpose
from ica.pipeline.summarization import (
    FEEDBACK_BUTTON_LABEL,
    FEEDBACK_FORM_DESCRIPTION,
    FEEDBACK_FORM_TITLE,
    FEEDBACK_MESSAGE,
    NEXT_STEPS_BUTTON_LABEL,
    NEXT_STEPS_FIELD_LABEL,
    NEXT_STEPS_FORM_DESCRIPTION,
    NEXT_STEPS_FORM_TITLE,
    NEXT_STEPS_MESSAGE,
    NEXT_STEPS_OPTIONS,
    SUMMARY_DIVIDER,
    SUMMARY_HEADER,
    ArticleSummary,
    SummarizationOutput,
    build_next_steps_form,
    build_summary_slack_blocks,
    call_regeneration_llm,
    extract_summary_learning_data,
    format_summary_slack_text,
    parse_next_steps_response,
    run_summarization_output,
    store_summarization_feedback,
    summaries_to_output_articles,
)
from ica.services.llm import LLMResponse
from ica.utils.output_router import UserChoice

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_summary(
    *,
    url: str = "https://example.com/article",
    title: str = "Test Article",
    summary: str = "This is a test summary.",
    business_relevance: str = "Relevant for business.",
    order: int = 1,
    newsletter_id: str = "NL-001",
    industry_news: bool = False,
) -> ArticleSummary:
    return ArticleSummary(
        url=url,
        title=title,
        summary=summary,
        business_relevance=business_relevance,
        order=order,
        newsletter_id=newsletter_id,
        industry_news=industry_news,
    )


def _make_summaries(n: int = 3) -> list[ArticleSummary]:
    """Create a list of n distinct summaries."""
    return [
        _make_summary(
            url=f"https://example.com/article-{i}",
            title=f"Article {i}",
            summary=f"Summary of article {i}.",
            business_relevance=f"Business relevance for article {i}.",
            order=i,
        )
        for i in range(1, n + 1)
    ]


def _mock_llm_response(content: str) -> LLMResponse:
    """Create a mock completion() response."""
    return LLMResponse(text=content, model="test/model")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Verify Slack form constants match n8n node configurations."""

    def test_summary_header(self):
        assert SUMMARY_HEADER == "Article Summaries for Review"

    def test_next_steps_field_label(self):
        assert NEXT_STEPS_FIELD_LABEL == "Ready to proceed to next step ?"

    def test_next_steps_options(self):
        assert NEXT_STEPS_OPTIONS == ["Yes", "Provide Feedback", "Restart Chat"]

    def test_next_steps_button_label(self):
        assert NEXT_STEPS_BUTTON_LABEL == "Proceed to Next Steps"

    def test_next_steps_form_title(self):
        assert NEXT_STEPS_FORM_TITLE == "Proceed to next step"

    def test_next_steps_form_description(self):
        assert "summarized" in NEXT_STEPS_FORM_DESCRIPTION

    def test_next_steps_message_bold(self):
        assert NEXT_STEPS_MESSAGE.startswith("*")
        assert NEXT_STEPS_MESSAGE.endswith("*")

    def test_feedback_message(self):
        assert "feedback" in FEEDBACK_MESSAGE.lower()

    def test_feedback_button_label(self):
        assert FEEDBACK_BUTTON_LABEL == "Add feedback"

    def test_feedback_form_title(self):
        assert FEEDBACK_FORM_TITLE == "Feedback Form"

    def test_feedback_form_description(self):
        assert "feedback" in FEEDBACK_FORM_DESCRIPTION.lower()

    def test_summary_divider_length(self):
        assert len(SUMMARY_DIVIDER) == 30


# ---------------------------------------------------------------------------
# SummarizationOutput dataclass
# ---------------------------------------------------------------------------


class TestSummarizationOutput:
    """Test the SummarizationOutput dataclass."""

    def test_creation(self):
        output = SummarizationOutput(
            articles=[{"URL": "http://example.com"}],
            text="test text",
            model="test-model",
        )
        assert output.articles == [{"URL": "http://example.com"}]
        assert output.text == "test text"
        assert output.model == "test-model"

    def test_frozen(self):
        output = SummarizationOutput(articles=[], text="t", model="m")
        with pytest.raises(AttributeError):
            output.text = "new"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# format_summary_slack_text
# ---------------------------------------------------------------------------


class TestFormatSummarySlackText:
    """Test Slack mrkdwn text formatting for summaries."""

    def test_header_present(self):
        text = format_summary_slack_text(_make_summaries(1))
        assert SUMMARY_HEADER in text

    def test_total_articles_count(self):
        text = format_summary_slack_text(_make_summaries(5))
        assert "_Total Articles:_ 5" in text

    def test_article_title_bold(self):
        text = format_summary_slack_text([_make_summary(title="AI Advances")])
        assert "*1. AI Advances*" in text

    def test_url_present(self):
        text = format_summary_slack_text([_make_summary(url="https://example.com/ai")])
        assert "*URL:* https://example.com/ai" in text

    def test_summary_section(self):
        text = format_summary_slack_text([_make_summary(summary="AI is transforming industries.")])
        assert "*Summary:*" in text
        assert "AI is transforming industries." in text

    def test_business_relevance_section(self):
        text = format_summary_slack_text(
            [_make_summary(business_relevance="Impacts decision-making.")]
        )
        assert "*Business Relevance:*" in text
        assert "Impacts decision-making." in text

    def test_divider_between_articles(self):
        text = format_summary_slack_text(_make_summaries(2))
        assert SUMMARY_DIVIDER in text

    def test_multiple_articles_ordered(self):
        text = format_summary_slack_text(_make_summaries(3))
        assert "*1. Article 1*" in text
        assert "*2. Article 2*" in text
        assert "*3. Article 3*" in text

    def test_empty_summaries_list(self):
        text = format_summary_slack_text([])
        assert SUMMARY_HEADER in text
        assert "_Total Articles:_ 0" in text

    def test_order_matches_summary_order_field(self):
        s = _make_summary(order=7, title="Seventh")
        text = format_summary_slack_text([s])
        assert "*7. Seventh*" in text


# ---------------------------------------------------------------------------
# build_summary_slack_blocks
# ---------------------------------------------------------------------------


class TestBuildSummarySlackBlocks:
    """Test Slack Block Kit blocks construction."""

    def test_first_block_is_header_section(self):
        blocks = build_summary_slack_blocks(_make_summaries(1))
        assert blocks[0]["type"] == "section"
        assert SUMMARY_HEADER in blocks[0]["text"]["text"]

    def test_second_block_is_divider(self):
        blocks = build_summary_slack_blocks(_make_summaries(1))
        assert blocks[1]["type"] == "divider"

    def test_article_section_content(self):
        s = _make_summary(title="AI News", url="https://ai.com")
        blocks = build_summary_slack_blocks([s])
        article_block = blocks[2]
        assert article_block["type"] == "section"
        assert "AI News" in article_block["text"]["text"]
        assert "https://ai.com" in article_block["text"]["text"]

    def test_divider_after_each_article(self):
        blocks = build_summary_slack_blocks(_make_summaries(3))
        # header + divider + (article + divider) * 3 = 2 + 6 = 8
        assert len(blocks) == 8
        assert blocks[3]["type"] == "divider"
        assert blocks[5]["type"] == "divider"
        assert blocks[7]["type"] == "divider"

    def test_mrkdwn_type(self):
        blocks = build_summary_slack_blocks(_make_summaries(1))
        assert blocks[0]["text"]["type"] == "mrkdwn"
        assert blocks[2]["text"]["type"] == "mrkdwn"

    def test_total_articles_in_header(self):
        blocks = build_summary_slack_blocks(_make_summaries(4))
        assert "_Total Articles:_ 4" in blocks[0]["text"]["text"]

    def test_empty_summaries(self):
        blocks = build_summary_slack_blocks([])
        # header + divider = 2 blocks
        assert len(blocks) == 2
        assert "_Total Articles:_ 0" in blocks[0]["text"]["text"]

    def test_business_relevance_in_block(self):
        s = _make_summary(business_relevance="Strategic impact.")
        blocks = build_summary_slack_blocks([s])
        assert "Strategic impact." in blocks[2]["text"]["text"]

    def test_summary_in_block(self):
        s = _make_summary(summary="Key findings of the study.")
        blocks = build_summary_slack_blocks([s])
        assert "Key findings of the study." in blocks[2]["text"]["text"]


# ---------------------------------------------------------------------------
# build_next_steps_form
# ---------------------------------------------------------------------------


class TestBuildNextStepsForm:
    """Test the next-steps form builder."""

    def test_single_field(self):
        form = build_next_steps_form()
        assert len(form) == 1

    def test_field_type_dropdown(self):
        form = build_next_steps_form()
        assert form[0]["fieldType"] == "dropdown"

    def test_field_label(self):
        form = build_next_steps_form()
        assert form[0]["fieldLabel"] == NEXT_STEPS_FIELD_LABEL

    def test_three_options(self):
        form = build_next_steps_form()
        options = form[0]["fieldOptions"]["values"]
        assert len(options) == 3

    def test_option_values(self):
        form = build_next_steps_form()
        options = form[0]["fieldOptions"]["values"]
        labels = [opt["option"] for opt in options]
        assert labels == ["Yes", "Provide Feedback", "Restart Chat"]

    def test_required_field(self):
        form = build_next_steps_form()
        assert form[0]["requiredField"] is True

    def test_json_serializable(self):
        form = build_next_steps_form()
        serialized = json.dumps(form)
        assert isinstance(serialized, str)


# ---------------------------------------------------------------------------
# parse_next_steps_response
# ---------------------------------------------------------------------------


class TestParseNextStepsResponse:
    """Test parsing of next-steps form responses."""

    def test_yes(self):
        assert parse_next_steps_response({NEXT_STEPS_FIELD_LABEL: "Yes"}) == UserChoice.YES

    def test_provide_feedback(self):
        assert (
            parse_next_steps_response({NEXT_STEPS_FIELD_LABEL: "Provide Feedback"})
            == UserChoice.PROVIDE_FEEDBACK
        )

    def test_restart_chat(self):
        assert (
            parse_next_steps_response({NEXT_STEPS_FIELD_LABEL: "Restart Chat"})
            == UserChoice.RESTART
        )

    def test_case_insensitive(self):
        assert parse_next_steps_response({NEXT_STEPS_FIELD_LABEL: "yes"}) == UserChoice.YES

    def test_whitespace_tolerance(self):
        assert parse_next_steps_response({NEXT_STEPS_FIELD_LABEL: "  Yes  "}) == UserChoice.YES

    def test_empty_value(self):
        assert parse_next_steps_response({NEXT_STEPS_FIELD_LABEL: ""}) is None

    def test_missing_field(self):
        assert parse_next_steps_response({}) is None

    def test_unknown_value(self):
        assert parse_next_steps_response({NEXT_STEPS_FIELD_LABEL: "Maybe"}) is None

    def test_provide_feedback_case_variations(self):
        assert (
            parse_next_steps_response({NEXT_STEPS_FIELD_LABEL: "provide feedback"})
            == UserChoice.PROVIDE_FEEDBACK
        )

    def test_restart_chat_case_variations(self):
        assert (
            parse_next_steps_response({NEXT_STEPS_FIELD_LABEL: "restart chat"})
            == UserChoice.RESTART
        )


# ---------------------------------------------------------------------------
# summaries_to_output_articles
# ---------------------------------------------------------------------------


class TestSummariesToOutputArticles:
    """Test conversion to PRD Section 5.2 output format."""

    def test_basic_conversion(self):
        s = _make_summary(
            url="https://example.com",
            title="AI",
            summary="Summary.",
            business_relevance="Relevance.",
            order=1,
            newsletter_id="NL-001",
            industry_news=False,
        )
        articles = summaries_to_output_articles([s])
        assert len(articles) == 1
        assert articles[0]["URL"] == "https://example.com"
        assert articles[0]["Title"] == "AI"
        assert articles[0]["Summary"] == "Summary."
        assert articles[0]["BusinessRelevance"] == "Relevance."
        assert articles[0]["order"] == 1
        assert articles[0]["newsletter_id"] == "NL-001"
        assert articles[0]["industry_news"] is False

    def test_industry_news_true(self):
        s = _make_summary(industry_news=True)
        articles = summaries_to_output_articles([s])
        assert articles[0]["industry_news"] is True

    def test_multiple_articles_preserve_order(self):
        summaries = _make_summaries(3)
        articles = summaries_to_output_articles(summaries)
        assert len(articles) == 3
        assert articles[0]["order"] == 1
        assert articles[1]["order"] == 2
        assert articles[2]["order"] == 3

    def test_empty_list(self):
        assert summaries_to_output_articles([]) == []

    def test_key_names_match_prd(self):
        """PRD uses PascalCase keys for URL, Title, Summary, BusinessRelevance."""
        articles = summaries_to_output_articles([_make_summary()])
        keys = set(articles[0].keys())
        assert "URL" in keys
        assert "Title" in keys
        assert "Summary" in keys
        assert "BusinessRelevance" in keys
        assert "order" in keys
        assert "newsletter_id" in keys
        assert "industry_news" in keys

    def test_json_serializable(self):
        articles = summaries_to_output_articles(_make_summaries(2))
        serialized = json.dumps(articles)
        assert isinstance(serialized, str)


# ---------------------------------------------------------------------------
# call_regeneration_llm
# ---------------------------------------------------------------------------


class TestCallRegenerationLlm:
    """Test the regeneration LLM call."""

    @pytest.mark.asyncio
    async def test_returns_content(self):
        response = _mock_llm_response("Regenerated summaries")
        with patch(
            "ica.pipeline.summarization.completion",
            new_callable=AsyncMock,
            return_value=response,
        ) as mock_completion:
            result = await call_regeneration_llm(
                "original text",
                "make shorter",
                model="test-model",
            )
        assert result == "Regenerated summaries"
        assert mock_completion.call_count == 1

    @pytest.mark.asyncio
    async def test_strips_whitespace(self):
        response = _mock_llm_response("result")
        with patch(
            "ica.pipeline.summarization.completion",
            new_callable=AsyncMock,
            return_value=response,
        ):
            result = await call_regeneration_llm("original", "feedback", model="m")
        assert result == "result"

    @pytest.mark.asyncio
    async def test_uses_regeneration_prompt(self):
        response = _mock_llm_response("result")
        with patch(
            "ica.pipeline.summarization.completion",
            new_callable=AsyncMock,
            return_value=response,
        ) as mock_completion:
            await call_regeneration_llm("original content", "user feedback", model="m")
            call_args = mock_completion.call_args
            # The user prompt should include original content and feedback
            assert "original content" in call_args.kwargs["user_prompt"]
            assert "user feedback" in call_args.kwargs["user_prompt"]

    @pytest.mark.asyncio
    async def test_uses_specified_model(self):
        response = _mock_llm_response("result")
        with patch(
            "ica.pipeline.summarization.completion",
            new_callable=AsyncMock,
            return_value=response,
        ) as mock_completion:
            await call_regeneration_llm("original", "feedback", model="custom/model")
            call_args = mock_completion.call_args
            assert call_args.kwargs["model"] == "custom/model"

    @pytest.mark.asyncio
    async def test_default_model_from_config(self):
        response = _mock_llm_response("result")
        with patch(
            "ica.pipeline.summarization.completion",
            new_callable=AsyncMock,
            return_value=response,
        ) as mock_completion:
            await call_regeneration_llm("original", "feedback")
            call_args = mock_completion.call_args
            assert call_args.kwargs["purpose"] == LLMPurpose.SUMMARY_REGENERATION


# ---------------------------------------------------------------------------
# extract_summary_learning_data
# ---------------------------------------------------------------------------


class TestExtractSummaryLearningData:
    """Test the learning data extraction LLM call."""

    @pytest.mark.asyncio
    async def test_extracts_json_field(self):
        json_response = json.dumps({"learning_feedback": "Use shorter summaries next time."})
        response = _mock_llm_response(json_response)
        with patch(
            "ica.pipeline.summarization.completion",
            new_callable=AsyncMock,
            return_value=response,
        ):
            result = await extract_summary_learning_data(
                "make shorter", "input", "output", model="m"
            )
        assert result == "Use shorter summaries next time."

    @pytest.mark.asyncio
    async def test_returns_raw_when_not_json(self):
        response = _mock_llm_response("Just a plain text note.")
        with patch(
            "ica.pipeline.summarization.completion",
            new_callable=AsyncMock,
            return_value=response,
        ):
            result = await extract_summary_learning_data("feedback", "input", "output", model="m")
        assert result == "Just a plain text note."

    @pytest.mark.asyncio
    async def test_returns_raw_when_json_missing_key(self):
        json_response = json.dumps({"other_key": "value"})
        response = _mock_llm_response(json_response)
        with patch(
            "ica.pipeline.summarization.completion",
            new_callable=AsyncMock,
            return_value=response,
        ):
            result = await extract_summary_learning_data("feedback", "input", "output", model="m")
        assert result == json_response

    @pytest.mark.asyncio
    async def test_strips_whitespace(self):
        response = _mock_llm_response("trimmed")
        with patch(
            "ica.pipeline.summarization.completion",
            new_callable=AsyncMock,
            return_value=response,
        ):
            result = await extract_summary_learning_data("fb", "in", "out", model="m")
        assert result == "trimmed"

    @pytest.mark.asyncio
    async def test_uses_learning_data_prompt(self):
        response = _mock_llm_response("result")
        with patch(
            "ica.pipeline.summarization.completion",
            new_callable=AsyncMock,
            return_value=response,
        ) as mock_completion:
            await extract_summary_learning_data("user_fb", "input_text", "model_out", model="m")
            call_args = mock_completion.call_args
            # User prompt should contain all three inputs
            assert "user_fb" in call_args.kwargs["user_prompt"]
            assert "input_text" in call_args.kwargs["user_prompt"]
            assert "model_out" in call_args.kwargs["user_prompt"]

    @pytest.mark.asyncio
    async def test_default_model_from_config(self):
        response = _mock_llm_response("result")
        with patch(
            "ica.pipeline.summarization.completion",
            new_callable=AsyncMock,
            return_value=response,
        ) as mock_completion:
            await extract_summary_learning_data("fb", "in", "out")
            call_args = mock_completion.call_args
            assert call_args.kwargs["purpose"] == LLMPurpose.SUMMARY_LEARNING_DATA


# ---------------------------------------------------------------------------
# store_summarization_feedback
# ---------------------------------------------------------------------------


class TestStoreSummarizationFeedback:
    """Test learning feedback storage in the notes table."""

    @pytest.mark.asyncio
    async def test_calls_add_note(self):
        with patch("ica.pipeline.summarization.add_note") as mock_add_note:
            mock_add_note.return_value = MagicMock()
            session = AsyncMock()
            await store_summarization_feedback(session, "learning note")
            mock_add_note.assert_called_once_with(
                session,
                "user_summarization",
                "learning note",
                newsletter_id=None,
            )

    @pytest.mark.asyncio
    async def test_passes_newsletter_id(self):
        with patch("ica.pipeline.summarization.add_note") as mock_add_note:
            mock_add_note.return_value = MagicMock()
            session = AsyncMock()
            await store_summarization_feedback(session, "note", newsletter_id="NL-007")
            mock_add_note.assert_called_once_with(
                session,
                "user_summarization",
                "note",
                newsletter_id="NL-007",
            )

    @pytest.mark.asyncio
    async def test_note_type_is_user_summarization(self):
        with patch("ica.pipeline.summarization.add_note") as mock_add_note:
            mock_add_note.return_value = MagicMock()
            session = AsyncMock()
            await store_summarization_feedback(session, "text")
            call_args = mock_add_note.call_args
            assert call_args.args[1] == "user_summarization"


# ---------------------------------------------------------------------------
# run_summarization_output — "Yes" path (immediate approval)
# ---------------------------------------------------------------------------


class TestRunSummarizationOutputYes:
    """Test the orchestrator when user selects 'Yes' immediately."""

    @pytest.mark.asyncio
    async def test_returns_output_on_yes(self):
        slack = AsyncMock()
        slack.send_and_wait_form.return_value = {
            NEXT_STEPS_FIELD_LABEL: "Yes",
        }

        with patch("ica.pipeline.summarization.get_model", return_value="m"):
            result = await run_summarization_output(_make_summaries(2), slack=slack)

        assert isinstance(result, SummarizationOutput)
        assert len(result.articles) == 2
        assert result.model == "m"

    @pytest.mark.asyncio
    async def test_shares_content_in_channel(self):
        slack = AsyncMock()
        slack.send_and_wait_form.return_value = {
            NEXT_STEPS_FIELD_LABEL: "Yes",
        }

        with patch("ica.pipeline.summarization.get_model", return_value="m"):
            await run_summarization_output(_make_summaries(1), slack=slack)

        slack.send_channel_message.assert_called_once()
        call_args = slack.send_channel_message.call_args
        assert SUMMARY_HEADER in call_args.args[0]

    @pytest.mark.asyncio
    async def test_sends_next_steps_form(self):
        slack = AsyncMock()
        slack.send_and_wait_form.return_value = {
            NEXT_STEPS_FIELD_LABEL: "Yes",
        }

        with patch("ica.pipeline.summarization.get_model", return_value="m"):
            await run_summarization_output(_make_summaries(1), slack=slack)

        slack.send_and_wait_form.assert_called_once()
        call_kwargs = slack.send_and_wait_form.call_args.kwargs
        assert call_kwargs["button_label"] == NEXT_STEPS_BUTTON_LABEL
        assert call_kwargs["form_title"] == NEXT_STEPS_FORM_TITLE

    @pytest.mark.asyncio
    async def test_output_text_contains_header(self):
        slack = AsyncMock()
        slack.send_and_wait_form.return_value = {
            NEXT_STEPS_FIELD_LABEL: "Yes",
        }

        with patch("ica.pipeline.summarization.get_model", return_value="m"):
            result = await run_summarization_output(_make_summaries(1), slack=slack)

        assert SUMMARY_HEADER in result.text

    @pytest.mark.asyncio
    async def test_output_articles_format(self):
        slack = AsyncMock()
        slack.send_and_wait_form.return_value = {
            NEXT_STEPS_FIELD_LABEL: "Yes",
        }

        with patch("ica.pipeline.summarization.get_model", return_value="m"):
            result = await run_summarization_output(
                [_make_summary(url="https://ai.com", title="AI News")],
                slack=slack,
            )

        assert len(result.articles) == 1
        assert result.articles[0]["URL"] == "https://ai.com"
        assert result.articles[0]["Title"] == "AI News"

    @pytest.mark.asyncio
    async def test_blocks_passed_to_channel(self):
        slack = AsyncMock()
        slack.send_and_wait_form.return_value = {
            NEXT_STEPS_FIELD_LABEL: "Yes",
        }

        with patch("ica.pipeline.summarization.get_model", return_value="m"):
            await run_summarization_output(_make_summaries(1), slack=slack)

        call_kwargs = slack.send_channel_message.call_args.kwargs
        blocks = call_kwargs["blocks"]
        assert len(blocks) > 0
        assert blocks[0]["type"] == "section"

    @pytest.mark.asyncio
    async def test_no_feedback_collected(self):
        slack = AsyncMock()
        slack.send_and_wait_form.return_value = {
            NEXT_STEPS_FIELD_LABEL: "Yes",
        }

        with patch("ica.pipeline.summarization.get_model", return_value="m"):
            await run_summarization_output(_make_summaries(1), slack=slack)

        slack.send_and_wait_freetext.assert_not_called()


# ---------------------------------------------------------------------------
# run_summarization_output — "Provide Feedback" path
# ---------------------------------------------------------------------------


class TestRunSummarizationOutputFeedback:
    """Test the orchestrator feedback loop."""

    @pytest.mark.asyncio
    async def test_feedback_then_yes(self):
        """First loop: feedback → regenerate. Second loop: yes → exit."""
        slack = AsyncMock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.return_value = "Make shorter"

        regen_response = _mock_llm_response(f"*{SUMMARY_HEADER}*\nRegenerated text")
        learning_response = _mock_llm_response(
            json.dumps({"learning_feedback": "Shorter summaries."})
        )

        with (
            patch("ica.pipeline.summarization.get_model", return_value="m"),
            patch(
                "ica.pipeline.summarization.completion",
                new_callable=AsyncMock,
                side_effect=[regen_response, learning_response],
            ),
        ):
            result = await run_summarization_output(_make_summaries(1), slack=slack)

        assert isinstance(result, SummarizationOutput)
        # After regen, the output text should be the regenerated version
        assert "Regenerated text" in result.text

    @pytest.mark.asyncio
    async def test_feedback_form_sent(self):
        slack = AsyncMock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.return_value = "feedback text"

        regen_response = _mock_llm_response(f"*{SUMMARY_HEADER}*\nregen")
        learning_response = _mock_llm_response("note")

        with (
            patch("ica.pipeline.summarization.get_model", return_value="m"),
            patch(
                "ica.pipeline.summarization.completion",
                new_callable=AsyncMock,
                side_effect=[regen_response, learning_response],
            ),
        ):
            await run_summarization_output(_make_summaries(1), slack=slack)

        slack.send_and_wait_freetext.assert_called_once()
        call_kwargs = slack.send_and_wait_freetext.call_args.kwargs
        assert call_kwargs["button_label"] == FEEDBACK_BUTTON_LABEL

    @pytest.mark.asyncio
    async def test_learning_data_stored(self):
        slack = AsyncMock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.return_value = "feedback"

        regen_response = _mock_llm_response(f"*{SUMMARY_HEADER}*\nregen")
        learning_response = _mock_llm_response(json.dumps({"learning_feedback": "stored note"}))

        session = AsyncMock()

        with (
            patch("ica.pipeline.summarization.get_model", return_value="m"),
            patch(
                "ica.pipeline.summarization.completion",
                new_callable=AsyncMock,
                side_effect=[regen_response, learning_response],
            ),
            patch("ica.pipeline.summarization.add_note") as mock_add_note,
        ):
            mock_add_note.return_value = MagicMock()
            await run_summarization_output(_make_summaries(1), slack=slack, session=session)

        mock_add_note.assert_called_once_with(
            session,
            "user_summarization",
            "stored note",
            newsletter_id=None,
        )

    @pytest.mark.asyncio
    async def test_learning_data_with_newsletter_id(self):
        slack = AsyncMock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.return_value = "feedback"

        regen_response = _mock_llm_response(f"*{SUMMARY_HEADER}*\nregen")
        learning_response = _mock_llm_response("note text")

        session = AsyncMock()

        with (
            patch("ica.pipeline.summarization.get_model", return_value="m"),
            patch(
                "ica.pipeline.summarization.completion",
                new_callable=AsyncMock,
                side_effect=[regen_response, learning_response],
            ),
            patch("ica.pipeline.summarization.add_note") as mock_add_note,
        ):
            mock_add_note.return_value = MagicMock()
            await run_summarization_output(
                _make_summaries(1),
                slack=slack,
                session=session,
                newsletter_id="NL-005",
            )

        mock_add_note.assert_called_once_with(
            session,
            "user_summarization",
            "note text",
            newsletter_id="NL-005",
        )

    @pytest.mark.asyncio
    async def test_no_session_skips_storage(self):
        """When session is None, feedback is not stored."""
        slack = AsyncMock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.return_value = "feedback"

        regen_response = _mock_llm_response(f"*{SUMMARY_HEADER}*\nregen")
        learning_response = _mock_llm_response("note")

        with (
            patch("ica.pipeline.summarization.get_model", return_value="m"),
            patch(
                "ica.pipeline.summarization.completion",
                new_callable=AsyncMock,
                side_effect=[regen_response, learning_response],
            ),
            patch("ica.pipeline.summarization.add_note") as mock_add_note,
        ):
            await run_summarization_output(_make_summaries(1), slack=slack, session=None)

        mock_add_note.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_regen_reverts_to_original(self):
        """If regenerated text lacks the header, original text is used."""
        slack = AsyncMock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.return_value = "feedback"

        # Regen missing the header
        regen_response = _mock_llm_response("No header here")
        learning_response = _mock_llm_response("note")

        with (
            patch("ica.pipeline.summarization.get_model", return_value="m"),
            patch(
                "ica.pipeline.summarization.completion",
                new_callable=AsyncMock,
                side_effect=[regen_response, learning_response],
            ),
        ):
            result = await run_summarization_output(_make_summaries(1), slack=slack)

        # Should revert to original text which contains the header
        assert SUMMARY_HEADER in result.text

    @pytest.mark.asyncio
    async def test_shared_twice_on_feedback(self):
        """Content is shared once initially and once after regen."""
        slack = AsyncMock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.return_value = "feedback"

        regen_response = _mock_llm_response(f"*{SUMMARY_HEADER}*\nregen")
        learning_response = _mock_llm_response("note")

        with (
            patch("ica.pipeline.summarization.get_model", return_value="m"),
            patch(
                "ica.pipeline.summarization.completion",
                new_callable=AsyncMock,
                side_effect=[regen_response, learning_response],
            ),
        ):
            await run_summarization_output(_make_summaries(1), slack=slack)

        assert slack.send_channel_message.call_count == 2


# ---------------------------------------------------------------------------
# run_summarization_output — "Restart Chat" path
# ---------------------------------------------------------------------------


class TestRunSummarizationOutputRestart:
    """Test the orchestrator restart path."""

    @pytest.mark.asyncio
    async def test_restart_then_yes(self):
        """Restart resets to original text, then Yes exits."""
        slack = AsyncMock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Restart Chat"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]

        with patch("ica.pipeline.summarization.get_model", return_value="m"):
            result = await run_summarization_output(_make_summaries(1), slack=slack)

        assert isinstance(result, SummarizationOutput)
        assert SUMMARY_HEADER in result.text

    @pytest.mark.asyncio
    async def test_restart_reshares_content(self):
        """Restart loops back and re-shares the content."""
        slack = AsyncMock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Restart Chat"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]

        with patch("ica.pipeline.summarization.get_model", return_value="m"):
            await run_summarization_output(_make_summaries(1), slack=slack)

        assert slack.send_channel_message.call_count == 2

    @pytest.mark.asyncio
    async def test_restart_no_feedback_collected(self):
        slack = AsyncMock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Restart Chat"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]

        with patch("ica.pipeline.summarization.get_model", return_value="m"):
            await run_summarization_output(_make_summaries(1), slack=slack)

        slack.send_and_wait_freetext.assert_not_called()

    @pytest.mark.asyncio
    async def test_restart_after_feedback_resets_text(self):
        """Feedback → Restart → Yes should return original text."""
        slack = AsyncMock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Restart Chat"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.return_value = "feedback"

        regen_response = _mock_llm_response(f"*{SUMMARY_HEADER}*\nRegenerated")
        learning_response = _mock_llm_response("note")

        with (
            patch("ica.pipeline.summarization.get_model", return_value="m"),
            patch(
                "ica.pipeline.summarization.completion",
                new_callable=AsyncMock,
                side_effect=[regen_response, learning_response],
            ),
        ):
            result = await run_summarization_output(_make_summaries(1), slack=slack)

        # After restart, text should be original (not regenerated)
        assert "Regenerated" not in result.text
        assert SUMMARY_HEADER in result.text


# ---------------------------------------------------------------------------
# run_summarization_output — unknown selection
# ---------------------------------------------------------------------------


class TestRunSummarizationOutputUnknown:
    """Test the orchestrator with unrecognized form values."""

    @pytest.mark.asyncio
    async def test_unknown_value_loops_back(self):
        """Unknown value is treated like restart."""
        slack = AsyncMock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Maybe Later"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]

        with patch("ica.pipeline.summarization.get_model", return_value="m"):
            result = await run_summarization_output(_make_summaries(1), slack=slack)

        assert isinstance(result, SummarizationOutput)
        assert slack.send_channel_message.call_count == 2


# ---------------------------------------------------------------------------
# run_summarization_output — multiple feedback rounds
# ---------------------------------------------------------------------------


class TestRunSummarizationOutputMultipleFeedback:
    """Test multiple rounds of feedback."""

    @pytest.mark.asyncio
    async def test_two_feedback_rounds_then_yes(self):
        slack = AsyncMock()
        slack.send_and_wait_form.side_effect = [
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Provide Feedback"},
            {NEXT_STEPS_FIELD_LABEL: "Yes"},
        ]
        slack.send_and_wait_freetext.side_effect = [
            "first feedback",
            "second feedback",
        ]

        regen1 = _mock_llm_response(f"*{SUMMARY_HEADER}*\nRegen 1")
        learn1 = _mock_llm_response("note 1")
        regen2 = _mock_llm_response(f"*{SUMMARY_HEADER}*\nRegen 2")
        learn2 = _mock_llm_response("note 2")

        with (
            patch("ica.pipeline.summarization.get_model", return_value="m"),
            patch(
                "ica.pipeline.summarization.completion",
                new_callable=AsyncMock,
                side_effect=[regen1, learn1, regen2, learn2],
            ),
        ):
            result = await run_summarization_output(_make_summaries(1), slack=slack)

        # Final text should be from second regeneration
        assert "Regen 2" in result.text
        assert slack.send_and_wait_freetext.call_count == 2
        assert slack.send_channel_message.call_count == 3


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_single_summary(self):
        slack = AsyncMock()
        slack.send_and_wait_form.return_value = {
            NEXT_STEPS_FIELD_LABEL: "Yes",
        }

        with patch("ica.pipeline.summarization.get_model", return_value="m"):
            result = await run_summarization_output([_make_summary()], slack=slack)

        assert len(result.articles) == 1

    @pytest.mark.asyncio
    async def test_many_summaries(self):
        slack = AsyncMock()
        slack.send_and_wait_form.return_value = {
            NEXT_STEPS_FIELD_LABEL: "Yes",
        }

        with patch("ica.pipeline.summarization.get_model", return_value="m"):
            result = await run_summarization_output(_make_summaries(10), slack=slack)

        assert len(result.articles) == 10

    def test_format_text_special_characters(self):
        s = _make_summary(
            title='Article with "quotes" & <brackets>',
            summary="Summary with *bold* and _italic_.",
        )
        text = format_summary_slack_text([s])
        assert '"quotes"' in text
        assert "<brackets>" in text

    def test_blocks_special_characters(self):
        s = _make_summary(
            title='Article with "quotes"',
            url="https://example.com/path?q=1&b=2",
        )
        blocks = build_summary_slack_blocks([s])
        block_text = blocks[2]["text"]["text"]
        assert '"quotes"' in block_text
        assert "q=1&b=2" in block_text

    def test_format_text_unicode(self):
        s = _make_summary(
            title="AI \u2014 The Future",
            summary="Caf\u00e9 culture and AI.",
        )
        text = format_summary_slack_text([s])
        assert "\u2014" in text
        assert "Caf\u00e9" in text
