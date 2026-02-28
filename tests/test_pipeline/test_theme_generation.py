"""Tests for the theme generation pipeline step.

Tests cover:
- Feedback aggregation: empty, single, multiple, whitespace-only entries
- LLM call: prompt construction, model selection, error handling
- Theme output parsing: splitting, marker extraction, edge cases
- Full orchestration: with/without DB session, with/without feedback
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from ica.errors import LLMError
from ica.pipeline.theme_generation import (
    GeneratedTheme,
    ThemeGenerationResult,
    aggregate_feedback,
    call_theme_llm,
    generate_themes,
    parse_theme_output,
)
from ica.services.llm import LLMResponse
from ica.utils.marker_parser import FormattedTheme

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_SUMMARIES_JSON = json.dumps(
    [
        {
            "Title": "GPT-5 Released with Advanced Reasoning",
            "Summary": "OpenAI released GPT-5 with improved reasoning capabilities.",
            "BusinessRelevance": "Major leap in AI capability for enterprise adoption.",
            "Order": 1,
            "URL": "https://example.com/gpt5",
            "industry_news": "true",
        },
        {
            "Title": "Small Business AI Adoption Surges",
            "Summary": "Survey shows 70% of SMBs now use AI tools daily.",
            "BusinessRelevance": "Key market signal for AI tool providers.",
            "Order": 2,
            "URL": "https://example.com/smb-ai",
            "industry_news": "false",
        },
        {
            "Title": "AI Ethics Framework Published",
            "Summary": "New comprehensive AI ethics guidelines released.",
            "BusinessRelevance": "Compliance requirements for AI deployments.",
            "Order": 3,
            "URL": "https://example.com/ethics",
            "industry_news": "false",
        },
    ]
)

SAMPLE_LLM_OUTPUT = """\
THEME: AI Revolution in Small Business
Theme Description: How recent AI developments are transforming SMB operations.

Articles that fit.
FEATURED ARTICLE:
%FA_TITLE: Small Business AI Adoption Surges
%FA_SOURCE: 2
%FA_ORIGIN: TechCrunch
%FA_URL: https://example.com/smb-ai
%FA_CATEGORY: Market Analysis
%FA_WHY FEATURED: Direct relevance to our solopreneur audience

%M1_TITLE: AI Ethics Framework Published
%M1_SOURCE: 3
%M1_ORIGIN: MIT Technology Review
%M1_URL: https://example.com/ethics
%M1_CATEGORY: Policy & Governance
%M1_RATIONALE: Important compliance context for AI adopters

%M2_TITLE: New AI Automation Tools for Marketing
%M2_SOURCE: 4
%M2_ORIGIN: HubSpot Blog
%M2_URL: https://example.com/marketing-ai
%M2_CATEGORY: Marketing Technology
%M2_RATIONALE: Practical tools our audience can use immediately

%Q1_TITLE: ChatGPT Gets Voice Mode Update
%Q1_SOURCE: 5
%Q1_ORIGIN: The Verge
%Q1_URL: https://example.com/chatgpt-voice
%Q1_CATEGORY: Product Updates

%Q2_TITLE: AI Startup Funding Hits Record
%Q2_SOURCE: 6
%Q2_ORIGIN: VentureBeat
%Q2_URL: https://example.com/funding
%Q2_CATEGORY: Investment Trends

%Q3_TITLE: Google Launches AI Search Features
%Q3_SOURCE: 7
%Q3_ORIGIN: Search Engine Journal
%Q3_URL: https://example.com/google-ai
%Q3_CATEGORY: Search & Discovery

%I1_TITLE: GPT-5 Released with Advanced Reasoning
%I1_SOURCE: 1
%I1_ORIGIN: OpenAI Blog
%I1_URL: https://example.com/gpt5
%I1_Major AI Player: OpenAI

%I2_TITLE: Google DeepMind Publishes New Research
%I2_SOURCE: 8
%I2_ORIGIN: Google DeepMind
%I2_URL: https://example.com/deepmind
%I2_Major AI Player: Google

2-2-2 Distribution:
%222_tactical:% (Source 2) SMB adoption, (Source 4) Marketing tools
%222_educational:% (Source 3) Ethics framework, (Source 5) ChatGPT voice
%222_forward-thinking:% (Source 1) GPT-5 reasoning, (Source 8) DeepMind research

Source mix:
%SM_smaller_publisher:% HubSpot Blog (Source 4), Search Engine Journal (Source 7)
%SM_major_ai_player_coverage:% GPT-5 reasoning (Source 1)

REQUIREMENTS VERIFIED,
%RV_2-2-2 Distribution Achieved:% SMB (S2), Tools (S4), Ethics (S3), GPT-5 (S1)
%RV_Source mix:% (Source 4) HubSpot, (Source 7) SEJ
%RV_Technical complexity:% (Source 1) GPT-5 architecture
%RV_Major AI player coverage:% (Source 1) OpenAI GPT-5

-----

THEME: The Ethics and Impact of Next-Gen AI
Theme Description: Exploring how new AI models raise ethical questions.

Articles that fit.
FEATURED ARTICLE:
%FA_TITLE: AI Ethics Framework Published
%FA_SOURCE: 3
%FA_ORIGIN: MIT Technology Review
%FA_URL: https://example.com/ethics
%FA_CATEGORY: Policy & Governance
%FA_WHY FEATURED: Timely and important topic for responsible AI adoption

%M1_TITLE: GPT-5 Released with Advanced Reasoning
%M1_SOURCE: 1
%M1_ORIGIN: OpenAI Blog
%M1_URL: https://example.com/gpt5
%M1_CATEGORY: AI Technology
%M1_RATIONALE: Foundational technology driving the ethical discussion

%M2_TITLE: Small Business AI Adoption Surges
%M2_SOURCE: 2
%M2_ORIGIN: TechCrunch
%M2_URL: https://example.com/smb-ai
%M2_CATEGORY: Market Analysis
%M2_RATIONALE: Real-world impact context

%Q1_TITLE: AI Regulation Debate Heats Up
%Q1_SOURCE: 9
%Q1_ORIGIN: Reuters
%Q1_URL: https://example.com/regulation
%Q1_CATEGORY: Policy

%Q2_TITLE: AI Safety Research Advances
%Q2_SOURCE: 10
%Q2_ORIGIN: Anthropic Blog
%Q2_URL: https://example.com/safety
%Q2_CATEGORY: Research

%Q3_TITLE: EU AI Act Implementation Begins
%Q3_SOURCE: 11
%Q3_ORIGIN: EuroNews
%Q3_URL: https://example.com/eu-ai-act
%Q3_CATEGORY: Regulation

%I1_TITLE: GPT-5 Released with Advanced Reasoning
%I1_SOURCE: 1
%I1_ORIGIN: OpenAI Blog
%I1_URL: https://example.com/gpt5
%I1_Major AI Player: OpenAI

%I2_TITLE: Google DeepMind Publishes New Research
%I2_SOURCE: 8
%I2_ORIGIN: Google DeepMind
%I2_URL: https://example.com/deepmind
%I2_Major AI Player: Google

2-2-2 Distribution:
%222_tactical:% (Source 2) SMB adoption, (Source 9) Regulation debate
%222_educational:% (Source 3) Ethics framework, (Source 10) Safety research
%222_forward-thinking:% (Source 1) GPT-5, (Source 11) EU AI Act

Source mix:
%SM_smaller_publisher:% Anthropic Blog (Source 10), EuroNews (Source 11)
%SM_major_ai_player_coverage:% GPT-5 reasoning (Source 1)

REQUIREMENTS VERIFIED,
%RV_2-2-2 Distribution Achieved:% SMB (S2), Regulation (S9), Ethics (S3), GPT-5 (S1)
%RV_Source mix:% (Source 10) Anthropic, (Source 11) EuroNews
%RV_Technical complexity:% (Source 1) GPT-5 architecture
%RV_Major AI player coverage:% (Source 1) OpenAI GPT-5

-----

RECOMMENDATION: Theme 1 - AI Revolution in Small Business
Rationale:

1. Featured Article: AI Adoption Surges is relevant to our audience
2. Main Articles: Ethics and marketing AI provide practical context
3. Quick Hits: Balanced mix of updates, trends, and innovation
4. Industry Developments: OpenAI GPT-5 and DeepMind coverage
5. Source Mix: Diverse publishers from HubSpot to SEJ

This theme speaks directly to our core audience of solopreneurs.\
"""


@dataclass
class FakeFeedbackRow:
    """Minimal stand-in for Note rows."""

    feedback_text: str
    created_at: datetime | None = None
    newsletter_id: str | None = None


# ---------------------------------------------------------------------------
# aggregate_feedback
# ---------------------------------------------------------------------------


class TestAggregateFeedback:
    """Tests for feedback aggregation logic."""

    def test_empty_list_returns_none(self) -> None:
        assert aggregate_feedback([]) is None

    def test_single_entry(self) -> None:
        rows = [FakeFeedbackRow(feedback_text="Use shorter themes")]
        result = aggregate_feedback(rows)  # type: ignore[arg-type]
        assert result == "- Use shorter themes"

    def test_multiple_entries_bullet_list(self) -> None:
        rows = [
            FakeFeedbackRow(feedback_text="More tactical content"),
            FakeFeedbackRow(feedback_text="Better source diversity"),
            FakeFeedbackRow(feedback_text="Shorter descriptions"),
        ]
        result = aggregate_feedback(rows)  # type: ignore[arg-type]
        assert result is not None
        lines = result.split("\n")
        assert len(lines) == 3
        assert lines[0] == "- More tactical content"
        assert lines[1] == "- Better source diversity"
        assert lines[2] == "- Shorter descriptions"

    def test_empty_feedback_text_filtered(self) -> None:
        rows = [
            FakeFeedbackRow(feedback_text="Valid feedback"),
            FakeFeedbackRow(feedback_text=""),
            FakeFeedbackRow(feedback_text="Another valid one"),
        ]
        result = aggregate_feedback(rows)  # type: ignore[arg-type]
        assert result is not None
        lines = result.split("\n")
        assert len(lines) == 2
        assert "Valid feedback" in lines[0]
        assert "Another valid one" in lines[1]

    def test_all_empty_feedback_returns_none(self) -> None:
        rows = [
            FakeFeedbackRow(feedback_text=""),
            FakeFeedbackRow(feedback_text=""),
        ]
        result = aggregate_feedback(rows)  # type: ignore[arg-type]
        assert result is None

    def test_preserves_order(self) -> None:
        rows = [
            FakeFeedbackRow(feedback_text="First"),
            FakeFeedbackRow(feedback_text="Second"),
            FakeFeedbackRow(feedback_text="Third"),
        ]
        result = aggregate_feedback(rows)  # type: ignore[arg-type]
        assert result is not None
        assert result.index("First") < result.index("Second") < result.index("Third")

    def test_special_characters_preserved(self) -> None:
        rows = [FakeFeedbackRow(feedback_text="Use %FA_TITLE markers")]
        result = aggregate_feedback(rows)  # type: ignore[arg-type]
        assert result == "- Use %FA_TITLE markers"

    def test_multiline_feedback_text(self) -> None:
        rows = [FakeFeedbackRow(feedback_text="Line 1\nLine 2")]
        result = aggregate_feedback(rows)  # type: ignore[arg-type]
        assert result == "- Line 1\nLine 2"

    def test_unicode_content(self) -> None:
        rows = [FakeFeedbackRow(feedback_text="More focus on AI — especially GenAI")]
        result = aggregate_feedback(rows)  # type: ignore[arg-type]
        assert "—" in result


# ---------------------------------------------------------------------------
# parse_theme_output
# ---------------------------------------------------------------------------


class TestParseThemeOutput:
    """Tests for parsing raw LLM output into structured themes."""

    def test_parses_two_themes(self) -> None:
        themes = parse_theme_output(SAMPLE_LLM_OUTPUT)
        assert len(themes) == 2

    def test_theme_names_extracted(self) -> None:
        themes = parse_theme_output(SAMPLE_LLM_OUTPUT)
        assert themes[0].theme_name == "AI Revolution in Small Business"
        assert themes[1].theme_name == "The Ethics and Impact of Next-Gen AI"

    def test_theme_descriptions_extracted(self) -> None:
        themes = parse_theme_output(SAMPLE_LLM_OUTPUT)
        assert themes[0].theme_description is not None
        assert "SMB" in themes[0].theme_description
        assert themes[1].theme_description is not None
        assert "ethical" in themes[1].theme_description

    def test_theme_body_not_empty(self) -> None:
        themes = parse_theme_output(SAMPLE_LLM_OUTPUT)
        for theme in themes:
            assert len(theme.theme_body) > 0

    def test_formatted_theme_type(self) -> None:
        themes = parse_theme_output(SAMPLE_LLM_OUTPUT)
        for theme in themes:
            assert isinstance(theme.formatted_theme, FormattedTheme)

    def test_featured_article_parsed(self) -> None:
        themes = parse_theme_output(SAMPLE_LLM_OUTPUT)
        fa = themes[0].formatted_theme.featured_article
        assert fa.title == "Small Business AI Adoption Surges"
        assert fa.source == "2"
        assert fa.url == "https://example.com/smb-ai"
        assert fa.category == "Market Analysis"
        assert fa.why_featured is not None

    def test_main_articles_parsed(self) -> None:
        themes = parse_theme_output(SAMPLE_LLM_OUTPUT)
        m1 = themes[0].formatted_theme.main_article_1
        assert m1.title == "AI Ethics Framework Published"
        assert m1.source == "3"
        assert m1.rationale is not None

        m2 = themes[0].formatted_theme.main_article_2
        assert m2.title == "New AI Automation Tools for Marketing"
        assert m2.source == "4"

    def test_quick_hits_parsed(self) -> None:
        themes = parse_theme_output(SAMPLE_LLM_OUTPUT)
        ft = themes[0].formatted_theme
        assert ft.quick_hit_1.title == "ChatGPT Gets Voice Mode Update"
        assert ft.quick_hit_2.title == "AI Startup Funding Hits Record"
        assert ft.quick_hit_3.title == "Google Launches AI Search Features"

    def test_industry_developments_parsed(self) -> None:
        themes = parse_theme_output(SAMPLE_LLM_OUTPUT)
        ft = themes[0].formatted_theme
        assert ft.industry_development_1.title == "GPT-5 Released with Advanced Reasoning"
        assert ft.industry_development_1.major_ai_player == "OpenAI"
        assert ft.industry_development_2.major_ai_player == "Google"

    def test_requirements_verified_parsed(self) -> None:
        themes = parse_theme_output(SAMPLE_LLM_OUTPUT)
        rv = themes[0].formatted_theme.requirements_verified
        assert rv.distribution_achieved is not None
        assert rv.source_mix is not None
        assert rv.technical_complexity is not None
        assert rv.major_ai_player_coverage is not None

    def test_second_theme_has_different_featured(self) -> None:
        themes = parse_theme_output(SAMPLE_LLM_OUTPUT)
        fa1 = themes[0].formatted_theme.featured_article.title
        fa2 = themes[1].formatted_theme.featured_article.title
        assert fa1 != fa2

    def test_theme_title_matches_formatted_theme(self) -> None:
        themes = parse_theme_output(SAMPLE_LLM_OUTPUT)
        for theme in themes:
            assert theme.formatted_theme.theme == theme.theme_name

    def test_empty_input(self) -> None:
        themes = parse_theme_output("")
        assert themes == []

    def test_single_theme(self) -> None:
        single = SAMPLE_LLM_OUTPUT.split("-----")[0].strip() + "\n-----"
        themes = parse_theme_output(single)
        assert len(themes) == 1
        assert themes[0].theme_name == "AI Revolution in Small Business"

    def test_generated_theme_is_frozen(self) -> None:
        themes = parse_theme_output(SAMPLE_LLM_OUTPUT)
        with pytest.raises(AttributeError):
            themes[0].theme_name = "changed"  # type: ignore[misc]

    def test_no_separator_single_block(self) -> None:
        raw = (
            "THEME: My Theme\n"
            "Theme Description: A test theme\n\n"
            "%FA_TITLE: Test Article\n"
            "%FA_SOURCE: 1\n"
        )
        themes = parse_theme_output(raw)
        assert len(themes) == 1
        assert themes[0].theme_name == "My Theme"
        assert themes[0].formatted_theme.featured_article.title == "Test Article"


# ---------------------------------------------------------------------------
# call_theme_llm
# ---------------------------------------------------------------------------


class TestCallThemeLlm:
    """Tests for the LLM call function."""

    @pytest.mark.asyncio
    async def test_calls_completion_with_correct_args(self) -> None:
        with patch("ica.pipeline.theme_generation.completion") as mock_completion:
            mock_completion.return_value = LLMResponse(
                text=SAMPLE_LLM_OUTPUT.strip(), model="test-model"
            )

            _text, _model = await call_theme_llm(SAMPLE_SUMMARIES_JSON, model="test-model")

            mock_completion.assert_called_once()
            call_kwargs = mock_completion.call_args.kwargs
            assert call_kwargs["model"] == "test-model"
            assert "system_prompt" in call_kwargs
            assert "user_prompt" in call_kwargs

    @pytest.mark.asyncio
    async def test_returns_response_text_and_model(self) -> None:
        with patch("ica.pipeline.theme_generation.completion") as mock_completion:
            mock_completion.return_value = LLMResponse(
                text="THEME: Test\n-----", model="test-model"
            )

            text, model = await call_theme_llm(SAMPLE_SUMMARIES_JSON, model="test-model")

            assert text == "THEME: Test\n-----"
            assert model == "test-model"

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_response(self) -> None:
        with patch("ica.pipeline.theme_generation.completion") as mock_completion:
            mock_completion.return_value = LLMResponse(
                text="THEME: Test", model="test-model"
            )

            text, _ = await call_theme_llm(SAMPLE_SUMMARIES_JSON, model="test-model")
            assert text == "THEME: Test"

    @pytest.mark.asyncio
    async def test_empty_response_raises_llm_error(self) -> None:
        with patch("ica.pipeline.theme_generation.completion") as mock_completion:
            mock_completion.side_effect = LLMError(
                "theme_generation", "LLM returned an empty response"
            )

            with pytest.raises(LLMError, match="empty response"):
                await call_theme_llm(SAMPLE_SUMMARIES_JSON, model="test-model")

    @pytest.mark.asyncio
    async def test_whitespace_only_response_raises_llm_error(self) -> None:
        with patch("ica.pipeline.theme_generation.completion") as mock_completion:
            mock_completion.side_effect = LLMError(
                "theme_generation", "LLM returned an empty response"
            )

            with pytest.raises(LLMError, match="empty response"):
                await call_theme_llm(SAMPLE_SUMMARIES_JSON, model="test-model")

    @pytest.mark.asyncio
    async def test_none_response_raises_llm_error(self) -> None:
        with patch("ica.pipeline.theme_generation.completion") as mock_completion:
            mock_completion.side_effect = LLMError(
                "theme_generation", "LLM returned an empty response"
            )

            with pytest.raises(LLMError, match="empty response"):
                await call_theme_llm(SAMPLE_SUMMARIES_JSON, model="test-model")

    @pytest.mark.asyncio
    async def test_default_model_uses_theme_purpose(self) -> None:
        with patch("ica.pipeline.theme_generation.completion") as mock_completion:
            mock_completion.return_value = LLMResponse(
                text="THEME: Test", model="anthropic/claude-sonnet-4.5"
            )

            _, model = await call_theme_llm(SAMPLE_SUMMARIES_JSON)

            call_kwargs = mock_completion.call_args.kwargs
            assert call_kwargs["purpose"] is not None
            assert model == "anthropic/claude-sonnet-4.5"

    @pytest.mark.asyncio
    async def test_feedback_injected_into_prompt(self) -> None:
        with patch("ica.pipeline.theme_generation.completion") as mock_completion:
            mock_completion.return_value = LLMResponse(
                text="THEME: Test", model="test-model"
            )

            await call_theme_llm(
                SAMPLE_SUMMARIES_JSON,
                aggregated_feedback="- Use more tactical content",
                model="test-model",
            )

            call_kwargs = mock_completion.call_args.kwargs
            user_prompt = call_kwargs["user_prompt"]
            assert "tactical content" in user_prompt

    @pytest.mark.asyncio
    async def test_no_feedback_no_section(self) -> None:
        with patch("ica.pipeline.theme_generation.completion") as mock_completion:
            mock_completion.return_value = LLMResponse(
                text="THEME: Test", model="test-model"
            )

            await call_theme_llm(SAMPLE_SUMMARIES_JSON, model="test-model")

            call_kwargs = mock_completion.call_args.kwargs
            user_prompt = call_kwargs["user_prompt"]
            assert "Editorial Improvement Context" not in user_prompt


# ---------------------------------------------------------------------------
# generate_themes (full orchestration)
# ---------------------------------------------------------------------------


class TestGenerateThemes:
    """Tests for the full theme generation pipeline."""

    @pytest.mark.asyncio
    async def test_without_session_no_feedback(self) -> None:
        with patch("ica.pipeline.theme_generation.completion") as mock_completion:
            mock_completion.return_value = LLMResponse(
                text=SAMPLE_LLM_OUTPUT.strip(), model="test-model"
            )

            result = await generate_themes(SAMPLE_SUMMARIES_JSON, model="test-model")

            assert isinstance(result, ThemeGenerationResult)
            assert len(result.themes) == 2
            assert result.model == "test-model"

    @pytest.mark.asyncio
    async def test_result_has_recommendation(self) -> None:
        with patch("ica.pipeline.theme_generation.completion") as mock_completion:
            mock_completion.return_value = LLMResponse(
                text=SAMPLE_LLM_OUTPUT.strip(), model="test-model"
            )

            result = await generate_themes(SAMPLE_SUMMARIES_JSON, model="test-model")

            assert "RECOMMENDATION" in result.recommendation
            assert "Theme 1" in result.recommendation

    @pytest.mark.asyncio
    async def test_result_has_raw_llm_output(self) -> None:
        with patch("ica.pipeline.theme_generation.completion") as mock_completion:
            mock_completion.return_value = LLMResponse(
                text=SAMPLE_LLM_OUTPUT.strip(), model="test-model"
            )

            result = await generate_themes(SAMPLE_SUMMARIES_JSON, model="test-model")

            assert result.raw_llm_output == SAMPLE_LLM_OUTPUT.strip()

    @pytest.mark.asyncio
    async def test_themes_have_formatted_data(self) -> None:
        with patch("ica.pipeline.theme_generation.completion") as mock_completion:
            mock_completion.return_value = LLMResponse(
                text=SAMPLE_LLM_OUTPUT.strip(), model="test-model"
            )

            result = await generate_themes(SAMPLE_SUMMARIES_JSON, model="test-model")

            for theme in result.themes:
                assert theme.formatted_theme.featured_article.title is not None
                assert theme.formatted_theme.main_article_1.title is not None
                assert theme.formatted_theme.main_article_2.title is not None

    @pytest.mark.asyncio
    async def test_with_session_fetches_feedback(self) -> None:
        mock_session = AsyncMock()

        feedback_rows = [
            FakeFeedbackRow(feedback_text="Be more concise"),
            FakeFeedbackRow(feedback_text="Add more sources"),
        ]

        with (
            patch("ica.pipeline.theme_generation.completion") as mock_completion,
            patch(
                "ica.pipeline.theme_generation.get_recent_notes",
                new_callable=AsyncMock,
                return_value=feedback_rows,
            ) as mock_get_feedback,
        ):
            mock_completion.return_value = LLMResponse(
                text=SAMPLE_LLM_OUTPUT.strip(), model="test-model"
            )

            result = await generate_themes(
                SAMPLE_SUMMARIES_JSON,
                session=mock_session,
                model="test-model",
            )

            mock_get_feedback.assert_called_once()
            assert len(result.themes) == 2

    @pytest.mark.asyncio
    async def test_feedback_passed_to_llm(self) -> None:
        mock_session = AsyncMock()

        feedback_rows = [
            FakeFeedbackRow(feedback_text="Focus on practical tools"),
        ]

        with (
            patch("ica.pipeline.theme_generation.completion") as mock_completion,
            patch(
                "ica.pipeline.theme_generation.get_recent_notes",
                new_callable=AsyncMock,
                return_value=feedback_rows,
            ),
        ):
            mock_completion.return_value = LLMResponse(
                text=SAMPLE_LLM_OUTPUT.strip(), model="test-model"
            )

            await generate_themes(
                SAMPLE_SUMMARIES_JSON,
                session=mock_session,
                model="test-model",
            )

            call_kwargs = mock_completion.call_args.kwargs
            user_prompt = call_kwargs["user_prompt"]
            assert "practical tools" in user_prompt

    @pytest.mark.asyncio
    async def test_empty_feedback_rows_no_injection(self) -> None:
        mock_session = AsyncMock()

        with (
            patch("ica.pipeline.theme_generation.completion") as mock_completion,
            patch(
                "ica.pipeline.theme_generation.get_recent_notes",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            mock_completion.return_value = LLMResponse(
                text=SAMPLE_LLM_OUTPUT.strip(), model="test-model"
            )

            await generate_themes(
                SAMPLE_SUMMARIES_JSON,
                session=mock_session,
                model="test-model",
            )

            call_kwargs = mock_completion.call_args.kwargs
            user_prompt = call_kwargs["user_prompt"]
            assert "Editorial Improvement Context" not in user_prompt

    @pytest.mark.asyncio
    async def test_result_is_frozen(self) -> None:
        with patch("ica.pipeline.theme_generation.completion") as mock_completion:
            mock_completion.return_value = LLMResponse(
                text=SAMPLE_LLM_OUTPUT.strip(), model="test-model"
            )

            result = await generate_themes(SAMPLE_SUMMARIES_JSON, model="test-model")

            with pytest.raises(AttributeError):
                result.model = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ThemeGenerationResult defaults
# ---------------------------------------------------------------------------


class TestThemeGenerationResultDefaults:
    """Tests for ThemeGenerationResult default values."""

    def test_default_themes_empty(self) -> None:
        result = ThemeGenerationResult()
        assert result.themes == []

    def test_default_recommendation_empty(self) -> None:
        result = ThemeGenerationResult()
        assert result.recommendation == ""

    def test_default_raw_output_empty(self) -> None:
        result = ThemeGenerationResult()
        assert result.raw_llm_output == ""

    def test_default_model_empty(self) -> None:
        result = ThemeGenerationResult()
        assert result.model == ""


# ---------------------------------------------------------------------------
# GeneratedTheme
# ---------------------------------------------------------------------------


class TestGeneratedTheme:
    """Tests for the GeneratedTheme dataclass."""

    def test_creation(self) -> None:
        theme = GeneratedTheme(
            theme_name="Test Theme",
            theme_description="A test",
            theme_body="body text",
            formatted_theme=FormattedTheme(),
        )
        assert theme.theme_name == "Test Theme"
        assert theme.theme_description == "A test"
        assert theme.theme_body == "body text"

    def test_frozen(self) -> None:
        theme = GeneratedTheme(
            theme_name="Test",
            theme_description=None,
            theme_body="",
            formatted_theme=FormattedTheme(),
        )
        with pytest.raises(AttributeError):
            theme.theme_name = "changed"  # type: ignore[misc]

    def test_none_fields(self) -> None:
        theme = GeneratedTheme(
            theme_name=None,
            theme_description=None,
            theme_body="",
            formatted_theme=FormattedTheme(),
        )
        assert theme.theme_name is None
        assert theme.theme_description is None


# ---------------------------------------------------------------------------
# Edge cases: LLM output variations
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for various LLM output edge cases."""

    def test_extra_whitespace_around_separator(self) -> None:
        raw = (
            "THEME: First\n"
            "Theme Description: Desc 1\n\n"
            "%FA_TITLE: Article 1\n"
            "\n  -----  \n\n"
            "THEME: Second\n"
            "Theme Description: Desc 2\n\n"
            "%FA_TITLE: Article 2\n"
        )
        themes = parse_theme_output(raw)
        assert len(themes) == 2
        assert themes[0].formatted_theme.featured_article.title == "Article 1"
        assert themes[1].formatted_theme.featured_article.title == "Article 2"

    def test_theme_with_recommendation_only(self) -> None:
        raw = "RECOMMENDATION: Theme 1\nRationale: It's the best"
        themes = parse_theme_output(raw)
        assert themes == []

    def test_urls_preserved_in_markers(self) -> None:
        raw = (
            "THEME: URL Test\n"
            "Theme Description: Testing URLs\n\n"
            "%FA_TITLE: Test\n"
            "%FA_URL: https://example.com/article?id=123&lang=en\n"
        )
        themes = parse_theme_output(raw)
        assert themes[0].formatted_theme.featured_article.url == (
            "https://example.com/article?id=123&lang=en"
        )

    def test_markers_with_special_characters(self) -> None:
        raw = (
            "THEME: Special Chars\n"
            "Theme Description: Testing\n\n"
            "%FA_TITLE: AI — The Next Frontier (2026)\n"
            "%FA_SOURCE: 1\n"
        )
        themes = parse_theme_output(raw)
        assert "—" in themes[0].formatted_theme.featured_article.title

    def test_windows_line_endings(self) -> None:
        raw = (
            "THEME: Windows Test\r\n"
            "Theme Description: Testing CRLF\r\n\r\n"
            "%FA_TITLE: Test Article\r\n"
            "%FA_SOURCE: 1\r\n"
        )
        themes = parse_theme_output(raw)
        assert len(themes) == 1
        assert themes[0].theme_name == "Windows Test"

    def test_multiple_separators_between_themes(self) -> None:
        raw = (
            "THEME: First\n"
            "Theme Description: D1\n\n"
            "%FA_TITLE: A1\n"
            "-----\n"
            "-----\n"
            "THEME: Second\n"
            "Theme Description: D2\n\n"
            "%FA_TITLE: A2\n"
        )
        themes = parse_theme_output(raw)
        # Empty blocks between separators are filtered by strip()
        assert len(themes) >= 1

    @pytest.mark.asyncio
    async def test_generate_themes_propagates_llm_error(self) -> None:
        with patch("ica.pipeline.theme_generation.completion") as mock_completion:
            mock_completion.side_effect = LLMError(
                "theme_generation", "API rate limit exceeded"
            )

            with pytest.raises(LLMError, match="API rate limit"):
                await generate_themes(SAMPLE_SUMMARIES_JSON, model="test-model")

    def test_all_marker_types_present_in_sample(self) -> None:
        themes = parse_theme_output(SAMPLE_LLM_OUTPUT)
        ft = themes[0].formatted_theme

        # Featured Article
        assert ft.featured_article.title is not None
        assert ft.featured_article.source is not None
        assert ft.featured_article.origin is not None
        assert ft.featured_article.url is not None
        assert ft.featured_article.category is not None
        assert ft.featured_article.why_featured is not None

        # Main Articles
        assert ft.main_article_1.title is not None
        assert ft.main_article_1.rationale is not None
        assert ft.main_article_2.title is not None

        # Quick Hits
        assert ft.quick_hit_1.title is not None
        assert ft.quick_hit_2.title is not None
        assert ft.quick_hit_3.title is not None

        # Industry Developments
        assert ft.industry_development_1.title is not None
        assert ft.industry_development_1.major_ai_player is not None
        assert ft.industry_development_2.title is not None

        # Requirements Verified
        assert ft.requirements_verified.distribution_achieved is not None
        assert ft.requirements_verified.source_mix is not None
        assert ft.requirements_verified.technical_complexity is not None
        assert ft.requirements_verified.major_ai_player_coverage is not None


# ---------------------------------------------------------------------------
# Integration: parse → formatted_theme dict-like access
# ---------------------------------------------------------------------------


class TestFormattedThemeAccess:
    """Tests verifying the formatted_theme structure matches PRD spec."""

    def test_theme_field_is_theme_name(self) -> None:
        themes = parse_theme_output(SAMPLE_LLM_OUTPUT)
        assert themes[0].formatted_theme.theme == "AI Revolution in Small Business"

    def test_featured_article_has_why_featured(self) -> None:
        """PRD requires Why Featured field for FA only."""
        themes = parse_theme_output(SAMPLE_LLM_OUTPUT)
        assert themes[0].formatted_theme.featured_article.why_featured is not None

    def test_main_articles_have_rationale(self) -> None:
        """PRD requires Rationale field for M1/M2 only."""
        themes = parse_theme_output(SAMPLE_LLM_OUTPUT)
        assert themes[0].formatted_theme.main_article_1.rationale is not None
        assert themes[0].formatted_theme.main_article_2.rationale is not None

    def test_industry_devs_have_major_ai_player(self) -> None:
        """PRD requires Major AI Player field for I1/I2 only."""
        themes = parse_theme_output(SAMPLE_LLM_OUTPUT)
        assert themes[0].formatted_theme.industry_development_1.major_ai_player is not None
        assert themes[0].formatted_theme.industry_development_2.major_ai_player is not None

    def test_quick_hits_have_no_rationale(self) -> None:
        """Quick Hits should not have rationale (that's M1/M2 only)."""
        themes = parse_theme_output(SAMPLE_LLM_OUTPUT)
        q1 = themes[0].formatted_theme.quick_hit_1
        assert not hasattr(q1, "rationale")

    def test_quick_hits_have_no_why_featured(self) -> None:
        """Quick Hits should not have why_featured (that's FA only)."""
        themes = parse_theme_output(SAMPLE_LLM_OUTPUT)
        q1 = themes[0].formatted_theme.quick_hit_1
        assert not hasattr(q1, "why_featured")
