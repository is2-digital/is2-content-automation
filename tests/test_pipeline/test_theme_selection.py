"""Tests for ica.pipeline.theme_selection."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ica.config.llm_config import LLMPurpose

from ica.pipeline.theme_generation import GeneratedTheme, ThemeGenerationResult
from ica.pipeline.theme_selection import (
    ADD_FEEDBACK_OPTION,
    APPROVAL_FIELD_LABEL,
    APPROVE_OPTION,
    FEEDBACK_OPTION,
    FEEDBACK_TEXTAREA_LABEL,
    RESET_OPTION,
    SELECTION_FIELD_LABEL,
    THEME_OPTION_PREFIX,
    ApprovalChoice,
    ThemeSelectionResult,
    build_approval_form,
    build_theme_selection_form,
    extract_learning_data,
    extract_selected_theme,
    format_freshness_slack_message,
    format_recommendation,
    format_selected_theme_body,
    format_theme_body,
    format_themes_slack_message,
    is_feedback_selection,
    parse_approval_choice,
    run_freshness_check,
    save_approved_theme,
    store_theme_feedback,
)
from ica.utils.marker_parser import (
    FeaturedArticle,
    FormattedTheme,
    IndustryDevelopment,
    MainArticle,
    QuickHit,
)


# ---------------------------------------------------------------------------
# Fixtures — reusable test data
# ---------------------------------------------------------------------------


def _make_theme(
    name: str = "AI Adoption",
    description: str = "A theme about AI adoption",
    body: str | None = None,
) -> GeneratedTheme:
    """Create a GeneratedTheme for testing."""
    if body is None:
        body = (
            f"THEME: {name}\n"
            f"Theme Description: {description}\n"
            "Articles that fit:\n"
            "FEATURED ARTICLE:\n"
            "%FA_TITLE: Some Article Title\n"
            "%FA_SOURCE: TechCrunch\n"
            "%FA_ORIGIN: techcrunch.com\n"
            "%FA_URL: https://techcrunch.com/article\n"
            "%FA_CATEGORY: Tactical\n"
            "%FA_WHY FEATURED: Great insights\n"
            "%M1_TITLE: Main Article One\n"
            "%M1_SOURCE: Wired\n"
            "%M1_ORIGIN: wired.com\n"
            "%M1_URL: https://wired.com/article\n"
            "%M1_CATEGORY: Educational\n"
            "%M1_RATIONALE: Relevant coverage\n"
            "%M2_TITLE: Main Article Two\n"
            "%M2_SOURCE: Ars Technica\n"
            "%M2_ORIGIN: arstechnica.com\n"
            "%M2_URL: https://arstechnica.com/article\n"
            "%M2_CATEGORY: Forward-thinking\n"
            "%M2_RATIONALE: Innovative angle\n"
            "%Q1_TITLE: Quick Hit One\n"
            "%Q1_SOURCE: VentureBeat\n"
            "%Q1_ORIGIN: venturebeat.com\n"
            "%Q1_URL: https://venturebeat.com/q1\n"
            "%Q1_CATEGORY: Tactical\n"
            "%Q2_TITLE: Quick Hit Two\n"
            "%Q2_SOURCE: Reuters\n"
            "%Q2_ORIGIN: reuters.com\n"
            "%Q2_URL: https://reuters.com/q2\n"
            "%Q2_CATEGORY: Educational\n"
            "%Q3_TITLE: Quick Hit Three\n"
            "%Q3_SOURCE: BBC\n"
            "%Q3_ORIGIN: bbc.com\n"
            "%Q3_URL: https://bbc.com/q3\n"
            "%Q3_CATEGORY: Forward-thinking\n"
            "%I1_TITLE: Industry Dev One\n"
            "%I1_SOURCE: OpenAI Blog\n"
            "%I1_ORIGIN: openai.com\n"
            "%I1_URL: https://openai.com/blog\n"
            "%I1_Major AI Player: OpenAI\n"
            "%I2_TITLE: Industry Dev Two\n"
            "%I2_SOURCE: Google AI Blog\n"
            "%I2_ORIGIN: ai.google\n"
            "%I2_URL: https://ai.google/blog\n"
            "%I2_Major AI Player: Google\n"
            "REQUIREMENTS VERIFIED:\n"
            "%RV_2-2-2 Distribution Achieved:% Yes\n"
            "%RV_Source mix:% Good\n"
            "%RV_Technical complexity:% Moderate\n"
            "%RV_Major AI player coverage:% OpenAI, Google\n"
        )
    return GeneratedTheme(
        theme_name=name,
        theme_description=description,
        theme_body=body,
        formatted_theme=FormattedTheme(theme=name),
    )


def _make_result(themes: list[GeneratedTheme] | None = None) -> ThemeGenerationResult:
    """Create a ThemeGenerationResult for testing."""
    if themes is None:
        themes = [
            _make_theme("AI Adoption", "How businesses adopt AI"),
            _make_theme("Open Source AI", "Open source movement in AI"),
        ]
    return ThemeGenerationResult(
        themes=themes,
        recommendation="RECOMMENDATION: Theme 1 is stronger\nRationale: More diverse sources",
        raw_llm_output="raw output text",
        model="anthropic/claude-sonnet-4.5",
    )


# =========================================================================
# format_theme_body
# =========================================================================


class TestFormatThemeBody:
    """Tests for format_theme_body()."""

    def test_strips_url_lines(self):
        body = "%FA_URL: https://example.com\nOther content"
        result = format_theme_body(body)
        assert "https://example.com" not in result
        assert "Other content" in result

    def test_strips_rationale_lines(self):
        body = "%M1_RATIONALE: Some rationale\nOther content"
        result = format_theme_body(body)
        assert "Some rationale" not in result

    def test_strips_origin_lines(self):
        body = "%FA_ORIGIN: techcrunch.com\nOther content"
        result = format_theme_body(body)
        assert "techcrunch.com" not in result

    def test_formats_featured_article(self):
        body = "%FA_TITLE: Cool Article\n%FA_SOURCE: TechCrunch"
        result = format_theme_body(body)
        assert "*Featured Candidate:*" in result
        assert "Cool Article" in result

    def test_formats_main_articles(self):
        body = "%M1_TITLE: Main One\n%M2_TITLE: Main Two"
        result = format_theme_body(body)
        assert "*Main Candidate 1:*" in result
        assert "*Main Candidate 2:*" in result

    def test_formats_quick_hits(self):
        body = "%Q1_TITLE: QH One\n%Q2_TITLE: QH Two\n%Q3_TITLE: QH Three"
        result = format_theme_body(body)
        assert "*Quick Hits Candidates:*" in result

    def test_formats_industry_developments(self):
        body = "%I1_TITLE: Ind One\n%I2_TITLE: Ind Two"
        result = format_theme_body(body)
        assert "*Industry Candidates:*" in result

    def test_strips_requirements_verified(self):
        body = (
            "REQUIREMENTS VERIFIED:\n"
            "%RV_2-2-2 Distribution Achieved: Yes\n"
            "%RV_Source mix: Good\n"
            "%RV_Technical complexity: Moderate\n"
            "%RV_Major AI player coverage: OpenAI\n"
        )
        result = format_theme_body(body)
        assert "REQUIREMENTS VERIFIED" not in result
        assert "%RV_" not in result

    def test_strips_theme_header(self):
        body = "THEME: Some Theme\nContent"
        result = format_theme_body(body)
        assert "THEME:" not in result

    def test_formats_theme_description(self):
        body = "Theme Description: A great narrative"
        result = format_theme_body(body)
        assert "*Core Narrative:*" in result

    def test_formats_articles_that_fit(self):
        body = "Articles that fit:"
        result = format_theme_body(body)
        assert "*Articles that fit:*" in result

    def test_strips_remaining_markers(self):
        body = "%XX_UNKNOWN: value"
        result = format_theme_body(body)
        assert "%XX_" not in result

    def test_full_theme_body(self):
        theme = _make_theme()
        result = format_theme_body(theme.theme_body)
        # Should not contain raw markers.
        assert "%FA_" not in result
        assert "%M1_" not in result
        assert "%Q1_" not in result
        assert "%I1_" not in result
        assert "%RV_" not in result
        # Should contain formatted labels.
        assert "*Featured Candidate:*" in result
        assert "*Core Narrative:*" in result

    def test_empty_string(self):
        result = format_theme_body("")
        assert result == ""

    def test_no_markers(self):
        body = "Just plain text with no markers"
        result = format_theme_body(body)
        assert result == body


# =========================================================================
# format_recommendation
# =========================================================================


class TestFormatRecommendation:
    """Tests for format_recommendation()."""

    def test_bolds_rationale(self):
        text = "Rationale: Theme 1 is better"
        result = format_recommendation(text)
        assert "*Rationale:*" in result

    def test_bolds_recommendation_title(self):
        text = "RECOMMENDATION: Theme 1"
        result = format_recommendation(text)
        assert "*Theme 1*" in result

    def test_strips_marker_prefixes(self):
        text = "%FA_some text"
        result = format_recommendation(text)
        assert "%FA_" not in result

    def test_strips_222_prefixes(self):
        text = "%222_tactical: content"
        result = format_recommendation(text)
        assert "%222_" not in result

    def test_empty_string(self):
        result = format_recommendation("")
        assert result == ""

    def test_none_text(self):
        result = format_recommendation(None)  # type: ignore[arg-type]
        assert result == ""

    def test_preserves_plain_text(self):
        text = "Simple recommendation text"
        result = format_recommendation(text)
        assert "Simple recommendation text" in result


# =========================================================================
# format_themes_slack_message
# =========================================================================


class TestFormatThemesSlackMessage:
    """Tests for format_themes_slack_message()."""

    def test_contains_header(self):
        result = format_themes_slack_message(_make_result())
        assert "Newsletter Text Themes" in result

    def test_contains_theme_numbers(self):
        result = format_themes_slack_message(_make_result())
        assert "*THEME 1:*" in result
        assert "*THEME 2:*" in result

    def test_contains_theme_names(self):
        result = format_themes_slack_message(_make_result())
        assert "AI Adoption" in result
        assert "Open Source AI" in result

    def test_contains_recommendation(self):
        result = format_themes_slack_message(_make_result())
        assert "RECOMMENDATION" in result

    def test_contains_dividers(self):
        result = format_themes_slack_message(_make_result())
        # Unicode horizontal line characters used as dividers.
        assert "\u2500" in result

    def test_single_theme(self):
        themes = [_make_theme("Solo Theme")]
        result = format_themes_slack_message(_make_result(themes))
        assert "*THEME 1:*" in result
        assert "*THEME 2:*" not in result

    def test_no_recommendation(self):
        r = ThemeGenerationResult(
            themes=[_make_theme()],
            recommendation="",
            raw_llm_output="",
            model="test",
        )
        result = format_themes_slack_message(r)
        assert "Newsletter Text Themes" in result

    def test_theme_without_name_uses_fallback(self):
        theme = GeneratedTheme(
            theme_name=None,
            theme_description=None,
            theme_body="Some body",
            formatted_theme=FormattedTheme(),
        )
        result = format_themes_slack_message(_make_result([theme]))
        assert "*Theme 1*" in result


# =========================================================================
# format_selected_theme_body
# =========================================================================


class TestFormatSelectedThemeBody:
    """Tests for format_selected_theme_body()."""

    def test_strips_theme_header(self):
        body = "THEME: Some Theme\nContent"
        result = format_selected_theme_body(body)
        assert "THEME:" not in result

    def test_formats_featured_article_detail(self):
        body = "%FA_TITLE: Cool Article\n%FA_URL: https://example.com"
        result = format_selected_theme_body(body)
        assert "*FEATURED ARTICLE:*" not in result or "Title:" in result

    def test_formats_main_articles_detail(self):
        body = "%M1_TITLE: Main One\n%M2_TITLE: Main Two"
        result = format_selected_theme_body(body)
        assert "*MAIN ARTICLE 1:*" in result
        assert "*MAIN ARTICLE 2:*" in result

    def test_formats_quick_hits_detail(self):
        body = "%Q1_TITLE: QH One\n%Q2_TITLE: QH Two\n%Q3_TITLE: QH Three"
        result = format_selected_theme_body(body)
        assert "*QUICK HIT ARTICLE 1:*" in result
        assert "*QUICK HIT ARTICLE 2:*" in result
        assert "*QUICK HIT ARTICLE 3:*" in result

    def test_formats_industry_articles_detail(self):
        body = "%I1_TITLE: Ind One\n%I2_TITLE: Ind Two"
        result = format_selected_theme_body(body)
        assert "*INDUSTRY ARTICLE 1:*" in result or "INDUSTRY ARTICLE 1" in result
        assert "*INDUSTRY ARTICLE 2:*" in result or "INDUSTRY ARTICLE 2" in result

    def test_strips_source_lines(self):
        body = "%FA_SOURCE: TechCrunch\nOther"
        result = format_selected_theme_body(body)
        assert "%FA_SOURCE" not in result

    def test_strips_requirements_verified(self):
        body = "REQUIREMENTS VERIFIED: test\n%RV_Source mix:% Good"
        result = format_selected_theme_body(body)
        assert "REQUIREMENTS VERIFIED" not in result
        assert "%RV_" not in result

    def test_strips_remaining_markers(self):
        body = "%XX_UNKNOWN: value"
        result = format_selected_theme_body(body)
        assert "%XX_" not in result

    def test_full_theme_body(self):
        theme = _make_theme()
        result = format_selected_theme_body(theme.theme_body)
        # Should not contain raw markers.
        assert "%FA_" not in result
        assert "%M1_" not in result
        assert "%RV_" not in result

    def test_empty_string(self):
        result = format_selected_theme_body("")
        assert result == ""


# =========================================================================
# format_freshness_slack_message
# =========================================================================


class TestFormatFreshnessSlackMessage:
    """Tests for format_freshness_slack_message()."""

    def test_contains_selected_theme_header(self):
        result = format_freshness_slack_message("AI Theme", "body", "Fresh!")
        assert "Selected theme" in result

    def test_contains_theme_name(self):
        result = format_freshness_slack_message("AI Theme", "body", "Fresh!")
        assert "AI Theme" in result

    def test_contains_final_selections_header(self):
        result = format_freshness_slack_message("AI Theme", "body", "Fresh!")
        assert "FINAL ARTICLE SELECTIONS" in result

    def test_contains_freshness_report_header(self):
        result = format_freshness_slack_message("AI Theme", "body", "Fresh!")
        assert "Freshness Report" in result

    def test_contains_freshness_report_content(self):
        result = format_freshness_slack_message("AI Theme", "body", "All fresh!")
        assert "All fresh!" in result

    def test_contains_dividers(self):
        result = format_freshness_slack_message("AI Theme", "body", "Fresh!")
        assert "\u2500" in result


# =========================================================================
# build_theme_selection_form
# =========================================================================


class TestBuildThemeSelectionForm:
    """Tests for build_theme_selection_form()."""

    def test_returns_two_fields(self):
        themes = [_make_theme("Theme A"), _make_theme("Theme B")]
        form = build_theme_selection_form(themes)
        assert len(form) == 2

    def test_first_field_is_radio(self):
        themes = [_make_theme()]
        form = build_theme_selection_form(themes)
        assert form[0]["fieldType"] == "radio"
        assert form[0]["fieldLabel"] == SELECTION_FIELD_LABEL

    def test_second_field_is_textarea(self):
        themes = [_make_theme()]
        form = build_theme_selection_form(themes)
        assert form[1]["fieldType"] == "textarea"
        assert form[1]["fieldLabel"] == FEEDBACK_TEXTAREA_LABEL

    def test_radio_options_include_all_themes(self):
        themes = [_make_theme("Alpha"), _make_theme("Beta")]
        form = build_theme_selection_form(themes)
        options = form[0]["fieldOptions"]["values"]
        assert len(options) == 3  # 2 themes + feedback
        assert options[0]["option"] == "THEME: Alpha"
        assert options[1]["option"] == "THEME: Beta"

    def test_radio_options_include_feedback(self):
        themes = [_make_theme()]
        form = build_theme_selection_form(themes)
        options = form[0]["fieldOptions"]["values"]
        assert options[-1]["option"] == FEEDBACK_OPTION

    def test_theme_without_name_uses_fallback(self):
        theme = GeneratedTheme(
            theme_name=None,
            theme_description=None,
            theme_body="body",
            formatted_theme=FormattedTheme(),
        )
        form = build_theme_selection_form([theme])
        options = form[0]["fieldOptions"]["values"]
        assert options[0]["option"] == "THEME: Theme 1"

    def test_json_serializable(self):
        themes = [_make_theme()]
        form = build_theme_selection_form(themes)
        # Should not raise.
        json.dumps(form)

    def test_empty_themes_list(self):
        form = build_theme_selection_form([])
        options = form[0]["fieldOptions"]["values"]
        # Only the feedback option.
        assert len(options) == 1
        assert options[0]["option"] == FEEDBACK_OPTION


# =========================================================================
# build_approval_form
# =========================================================================


class TestBuildApprovalForm:
    """Tests for build_approval_form()."""

    def test_returns_two_fields(self):
        form = build_approval_form()
        assert len(form) == 2

    def test_first_field_is_radio(self):
        form = build_approval_form()
        assert form[0]["fieldType"] == "radio"
        assert form[0]["fieldLabel"] == APPROVAL_FIELD_LABEL

    def test_second_field_is_textarea(self):
        form = build_approval_form()
        assert form[1]["fieldType"] == "textarea"

    def test_three_approval_options(self):
        form = build_approval_form()
        options = form[0]["fieldOptions"]["values"]
        assert len(options) == 3

    def test_option_values(self):
        form = build_approval_form()
        options = form[0]["fieldOptions"]["values"]
        assert options[0]["option"] == APPROVE_OPTION
        assert options[1]["option"] == RESET_OPTION
        assert options[2]["option"] == ADD_FEEDBACK_OPTION

    def test_json_serializable(self):
        form = build_approval_form()
        json.dumps(form)


# =========================================================================
# extract_selected_theme
# =========================================================================


class TestExtractSelectedTheme:
    """Tests for extract_selected_theme()."""

    def test_matches_first_theme(self):
        themes = [_make_theme("Alpha"), _make_theme("Beta")]
        result = extract_selected_theme("THEME: Alpha", themes)
        assert result is not None
        assert result.theme_name == "Alpha"

    def test_matches_second_theme(self):
        themes = [_make_theme("Alpha"), _make_theme("Beta")]
        result = extract_selected_theme("THEME: Beta", themes)
        assert result is not None
        assert result.theme_name == "Beta"

    def test_case_insensitive_match(self):
        themes = [_make_theme("AI Adoption")]
        result = extract_selected_theme("THEME: ai adoption", themes)
        assert result is not None
        assert result.theme_name == "AI Adoption"

    def test_case_insensitive_prefix(self):
        themes = [_make_theme("Test")]
        result = extract_selected_theme("theme: Test", themes)
        assert result is not None

    def test_returns_none_for_feedback(self):
        themes = [_make_theme("Alpha")]
        result = extract_selected_theme("Add Feedback", themes)
        assert result is None

    def test_returns_none_for_no_match(self):
        themes = [_make_theme("Alpha")]
        result = extract_selected_theme("THEME: Nonexistent", themes)
        assert result is None

    def test_returns_none_for_empty_string(self):
        themes = [_make_theme("Alpha")]
        result = extract_selected_theme("", themes)
        assert result is None

    def test_handles_whitespace(self):
        themes = [_make_theme("AI Adoption")]
        result = extract_selected_theme("  THEME:  AI Adoption  ", themes)
        assert result is not None
        assert result.theme_name == "AI Adoption"

    def test_returns_none_for_partial_prefix(self):
        themes = [_make_theme("Test")]
        result = extract_selected_theme("THE: Test", themes)
        assert result is None

    def test_theme_name_with_special_chars(self):
        themes = [_make_theme("AI's Future: 2026 & Beyond")]
        result = extract_selected_theme("THEME: AI's Future: 2026 & Beyond", themes)
        assert result is not None

    def test_empty_themes_list(self):
        result = extract_selected_theme("THEME: Anything", [])
        assert result is None


# =========================================================================
# is_feedback_selection
# =========================================================================


class TestIsFeedbackSelection:
    """Tests for is_feedback_selection()."""

    def test_matches_exact(self):
        assert is_feedback_selection("Add Feedback") is True

    def test_case_insensitive(self):
        assert is_feedback_selection("add feedback") is True
        assert is_feedback_selection("ADD FEEDBACK") is True

    def test_strips_whitespace(self):
        assert is_feedback_selection("  Add Feedback  ") is True

    def test_false_for_theme_selection(self):
        assert is_feedback_selection("THEME: AI Adoption") is False

    def test_false_for_empty_string(self):
        assert is_feedback_selection("") is False

    def test_false_for_partial_match(self):
        assert is_feedback_selection("Add") is False
        assert is_feedback_selection("Feedback") is False


# =========================================================================
# parse_approval_choice
# =========================================================================


class TestParseApprovalChoice:
    """Tests for parse_approval_choice()."""

    def test_approve_exact(self):
        result = parse_approval_choice(APPROVE_OPTION)
        assert result == ApprovalChoice.APPROVE

    def test_approve_contains(self):
        result = parse_approval_choice("Approve articles and continue")
        assert result == ApprovalChoice.APPROVE

    def test_approve_case_insensitive(self):
        result = parse_approval_choice("APPROVE")
        assert result == ApprovalChoice.APPROVE

    def test_reset_exact(self):
        result = parse_approval_choice(RESET_OPTION)
        assert result == ApprovalChoice.RESET

    def test_reset_contains(self):
        result = parse_approval_choice("Reset Articles")
        assert result == ApprovalChoice.RESET

    def test_reset_case_insensitive(self):
        result = parse_approval_choice("reset articles (generate themes again)")
        assert result == ApprovalChoice.RESET

    def test_feedback_exact(self):
        result = parse_approval_choice(ADD_FEEDBACK_OPTION)
        assert result == ApprovalChoice.FEEDBACK

    def test_feedback_contains(self):
        result = parse_approval_choice("Add a feedback")
        assert result == ApprovalChoice.FEEDBACK

    def test_feedback_case_insensitive(self):
        result = parse_approval_choice("FEEDBACK")
        assert result == ApprovalChoice.FEEDBACK

    def test_strips_whitespace(self):
        result = parse_approval_choice("  Approve  ")
        assert result == ApprovalChoice.APPROVE

    def test_raises_for_empty(self):
        with pytest.raises(ValueError, match="Empty approval value"):
            parse_approval_choice("")

    def test_raises_for_unknown(self):
        with pytest.raises(ValueError, match="Unrecognized"):
            parse_approval_choice("Unknown option")

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("Approve articles and continue", ApprovalChoice.APPROVE),
            ("Reset Articles (Generate Themes Again)", ApprovalChoice.RESET),
            ("Add a feedback", ApprovalChoice.FEEDBACK),
        ],
    )
    def test_all_exact_options(self, value: str, expected: ApprovalChoice):
        assert parse_approval_choice(value) == expected


# =========================================================================
# ThemeSelectionResult
# =========================================================================


class TestThemeSelectionResult:
    """Tests for ThemeSelectionResult dataclass."""

    def test_creation(self):
        result = ThemeSelectionResult(
            theme_name="Test Theme",
            theme_body="body text",
            theme_summary="summary",
            formatted_theme=FormattedTheme(theme="Test Theme"),
            freshness_report="Fresh!",
            newsletter_id="nl-001",
        )
        assert result.theme_name == "Test Theme"
        assert result.theme_body == "body text"
        assert result.theme_summary == "summary"
        assert result.freshness_report == "Fresh!"
        assert result.newsletter_id == "nl-001"

    def test_frozen(self):
        result = ThemeSelectionResult(
            theme_name="Test",
            theme_body="body",
            theme_summary=None,
            formatted_theme=FormattedTheme(),
            freshness_report="report",
        )
        with pytest.raises(AttributeError):
            result.theme_name = "Changed"  # type: ignore[misc]

    def test_default_newsletter_id(self):
        result = ThemeSelectionResult(
            theme_name="Test",
            theme_body="body",
            theme_summary=None,
            formatted_theme=FormattedTheme(),
            freshness_report="report",
        )
        assert result.newsletter_id is None


# =========================================================================
# ApprovalChoice enum
# =========================================================================


class TestApprovalChoice:
    """Tests for the ApprovalChoice enum."""

    def test_values(self):
        assert ApprovalChoice.APPROVE == "approve"
        assert ApprovalChoice.RESET == "reset"
        assert ApprovalChoice.FEEDBACK == "feedback"

    def test_member_count(self):
        assert len(ApprovalChoice) == 3

    def test_string_comparison(self):
        assert ApprovalChoice.APPROVE == "approve"


# =========================================================================
# run_freshness_check
# =========================================================================


class TestRunFreshnessCheck:
    """Tests for run_freshness_check()."""

    @pytest.mark.asyncio
    async def test_calls_llm(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Theme is fresh and unique."

        with patch("ica.pipeline.theme_selection.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await run_freshness_check("theme body text")

        assert result == "Theme is fresh and unique."
        mock_litellm.acompletion.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_uses_default_model(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Fresh"

        with (
            patch("ica.pipeline.theme_selection.litellm") as mock_litellm,
            patch("ica.pipeline.theme_selection.get_model") as mock_get_model,
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            mock_get_model.return_value = "google/gemini-2.5-flash"
            await run_freshness_check("body")

        mock_get_model.assert_called_once_with(LLMPurpose.THEME_FRESHNESS_CHECK)
        call_kwargs = mock_litellm.acompletion.call_args
        assert call_kwargs.kwargs["model"] == "google/gemini-2.5-flash"

    @pytest.mark.asyncio
    async def test_uses_override_model(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Fresh"

        with patch("ica.pipeline.theme_selection.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            await run_freshness_check("body", model="custom/model")

        call_kwargs = mock_litellm.acompletion.call_args
        assert call_kwargs.kwargs["model"] == "custom/model"

    @pytest.mark.asyncio
    async def test_raises_on_empty_response(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""

        with patch("ica.pipeline.theme_selection.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            with pytest.raises(RuntimeError, match="empty response"):
                await run_freshness_check("body")

    @pytest.mark.asyncio
    async def test_raises_on_whitespace_response(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "   \n  "

        with patch("ica.pipeline.theme_selection.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            with pytest.raises(RuntimeError, match="empty response"):
                await run_freshness_check("body")

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_response(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "  Fresh theme  \n"

        with patch("ica.pipeline.theme_selection.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await run_freshness_check("body")

        assert result == "Fresh theme"

    @pytest.mark.asyncio
    async def test_passes_theme_body_to_prompt(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Fresh"

        with patch("ica.pipeline.theme_selection.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            await run_freshness_check("My unique theme body")

        call_args = mock_litellm.acompletion.call_args
        messages = call_args.kwargs["messages"]
        user_msg = messages[1]["content"]
        assert "My unique theme body" in user_msg


# =========================================================================
# extract_learning_data
# =========================================================================


class TestExtractLearningData:
    """Tests for extract_learning_data()."""

    @pytest.mark.asyncio
    async def test_extracts_json_learning_feedback(self):
        json_response = json.dumps(
            {"learning_feedback": "Future responses should be more concise."}
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json_response

        with patch("ica.pipeline.theme_selection.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await extract_learning_data("too long", "input", "output")

        assert result == "Future responses should be more concise."

    @pytest.mark.asyncio
    async def test_returns_raw_text_on_invalid_json(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Just some plain feedback text"

        with patch("ica.pipeline.theme_selection.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await extract_learning_data("feedback", "input", "output")

        assert result == "Just some plain feedback text"

    @pytest.mark.asyncio
    async def test_returns_raw_text_on_json_without_key(self):
        json_response = json.dumps({"other_key": "value"})
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json_response

        with patch("ica.pipeline.theme_selection.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await extract_learning_data("fb", "in", "out")

        assert result == json_response

    @pytest.mark.asyncio
    async def test_uses_default_model(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "feedback"

        with (
            patch("ica.pipeline.theme_selection.litellm") as mock_litellm,
            patch("ica.pipeline.theme_selection.get_model") as mock_get_model,
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            mock_get_model.return_value = "anthropic/claude-sonnet-4.5"
            await extract_learning_data("fb", "in", "out")

        mock_get_model.assert_called_once_with(LLMPurpose.THEME_LEARNING_DATA)

    @pytest.mark.asyncio
    async def test_uses_override_model(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "feedback"

        with patch("ica.pipeline.theme_selection.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            await extract_learning_data("fb", "in", "out", model="custom/model")

        call_kwargs = mock_litellm.acompletion.call_args
        assert call_kwargs.kwargs["model"] == "custom/model"

    @pytest.mark.asyncio
    async def test_raises_on_empty_response(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""

        with patch("ica.pipeline.theme_selection.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            with pytest.raises(RuntimeError, match="empty response"):
                await extract_learning_data("fb", "in", "out")

    @pytest.mark.asyncio
    async def test_passes_all_params_to_prompt(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "result"

        with patch("ica.pipeline.theme_selection.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            await extract_learning_data("my feedback", "my input", "my output")

        call_args = mock_litellm.acompletion.call_args
        messages = call_args.kwargs["messages"]
        user_msg = messages[1]["content"]
        assert "my feedback" in user_msg
        assert "my input" in user_msg
        assert "my output" in user_msg


# =========================================================================
# save_approved_theme
# =========================================================================


class TestSaveApprovedTheme:
    """Tests for save_approved_theme()."""

    @pytest.mark.asyncio
    async def test_calls_upsert_theme(self):
        theme = _make_theme("My Theme", "My Description")

        with patch("ica.pipeline.theme_selection.upsert_theme") as mock_upsert:
            mock_upsert.return_value = None
            mock_session = AsyncMock()
            await save_approved_theme(mock_session, theme, newsletter_id="nl-001")

        mock_upsert.assert_awaited_once_with(
            mock_session,
            theme="My Theme",
            theme_body=theme.theme_body,
            theme_summary="My Description",
            newsletter_id="nl-001",
            approved=True,
        )

    @pytest.mark.asyncio
    async def test_handles_none_theme_name(self):
        theme = GeneratedTheme(
            theme_name=None,
            theme_description=None,
            theme_body="body",
            formatted_theme=FormattedTheme(),
        )

        with patch("ica.pipeline.theme_selection.upsert_theme") as mock_upsert:
            mock_upsert.return_value = None
            mock_session = AsyncMock()
            await save_approved_theme(mock_session, theme)

        call_kwargs = mock_upsert.call_args
        assert call_kwargs.kwargs["theme"] == ""

    @pytest.mark.asyncio
    async def test_default_newsletter_id_is_none(self):
        theme = _make_theme()

        with patch("ica.pipeline.theme_selection.upsert_theme") as mock_upsert:
            mock_upsert.return_value = None
            mock_session = AsyncMock()
            await save_approved_theme(mock_session, theme)

        call_kwargs = mock_upsert.call_args
        assert call_kwargs.kwargs["newsletter_id"] is None


# =========================================================================
# store_theme_feedback
# =========================================================================


class TestStoreThemeFeedback:
    """Tests for store_theme_feedback()."""

    @pytest.mark.asyncio
    async def test_calls_add_note(self):
        with patch("ica.pipeline.theme_selection.add_note") as mock_add:
            mock_add.return_value = MagicMock()
            mock_session = AsyncMock()
            await store_theme_feedback(mock_session, "learning note", newsletter_id="nl-001")

        mock_add.assert_awaited_once()
        call_args = mock_add.call_args
        assert call_args.args[1] == "user_newsletter_themes"
        assert call_args.args[2] == "learning note"
        assert call_args.kwargs["newsletter_id"] == "nl-001"

    @pytest.mark.asyncio
    async def test_default_newsletter_id_is_none(self):
        with patch("ica.pipeline.theme_selection.add_note") as mock_add:
            mock_add.return_value = MagicMock()
            mock_session = AsyncMock()
            await store_theme_feedback(mock_session, "feedback text")

        call_kwargs = mock_add.call_args
        assert call_kwargs.kwargs["newsletter_id"] is None


# =========================================================================
# Constants
# =========================================================================


class TestConstants:
    """Tests for module-level constants."""

    def test_selection_field_label(self):
        assert SELECTION_FIELD_LABEL == "Newsletter Theme or Feedback"

    def test_feedback_textarea_label(self):
        assert FEEDBACK_TEXTAREA_LABEL == "Editor Feedback for AI"

    def test_approval_field_label(self):
        assert APPROVAL_FIELD_LABEL == "Approve or Feedback"

    def test_feedback_option(self):
        assert FEEDBACK_OPTION == "Add Feedback"

    def test_approve_option(self):
        assert APPROVE_OPTION == "Approve articles and continue"

    def test_reset_option(self):
        assert RESET_OPTION == "Reset Articles (Generate Themes Again)"

    def test_add_feedback_option(self):
        assert ADD_FEEDBACK_OPTION == "Add a feedback"

    def test_theme_option_prefix(self):
        assert THEME_OPTION_PREFIX == "THEME: "


# =========================================================================
# Integration-style tests — end-to-end scenarios
# =========================================================================


class TestEndToEndScenarios:
    """Integration-style tests for common workflow paths."""

    def test_selection_to_extraction(self):
        """Theme selection form → user picks theme → extracted correctly."""
        themes = [_make_theme("Alpha"), _make_theme("Beta")]
        form = build_theme_selection_form(themes)
        options = form[0]["fieldOptions"]["values"]

        # User selects "THEME: Alpha".
        selection = options[0]["option"]
        selected = extract_selected_theme(selection, themes)
        assert selected is not None
        assert selected.theme_name == "Alpha"

    def test_selection_feedback_path(self):
        """Theme selection form → user picks feedback."""
        themes = [_make_theme("Alpha")]
        form = build_theme_selection_form(themes)
        options = form[0]["fieldOptions"]["values"]

        feedback_option = options[-1]["option"]
        assert is_feedback_selection(feedback_option) is True
        assert extract_selected_theme(feedback_option, themes) is None

    def test_approval_all_paths(self):
        """Approval form → all three paths recognized."""
        form = build_approval_form()
        options = form[0]["fieldOptions"]["values"]

        assert parse_approval_choice(options[0]["option"]) == ApprovalChoice.APPROVE
        assert parse_approval_choice(options[1]["option"]) == ApprovalChoice.RESET
        assert parse_approval_choice(options[2]["option"]) == ApprovalChoice.FEEDBACK

    def test_format_and_extract_roundtrip(self):
        """Generate themes → format for Slack → build form → select → extract."""
        result = _make_result()
        message = format_themes_slack_message(result)
        assert "AI Adoption" in message

        form = build_theme_selection_form(result.themes)
        option_value = form[0]["fieldOptions"]["values"][0]["option"]
        selected = extract_selected_theme(option_value, result.themes)
        assert selected is not None
        assert selected.theme_name == "AI Adoption"

    @pytest.mark.asyncio
    async def test_freshness_to_approval_flow(self):
        """Selected theme → freshness check → format message → approval."""
        theme = _make_theme("AI Adoption")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Theme is fresh and unique."

        with patch("ica.pipeline.theme_selection.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            freshness = await run_freshness_check(theme.theme_body)

        message = format_freshness_slack_message(
            theme.theme_name or "", theme.theme_body, freshness
        )
        assert "AI Adoption" in message
        assert "fresh" in message.lower()

        # Approval form should have all three options.
        form = build_approval_form()
        assert len(form[0]["fieldOptions"]["values"]) == 3

    @pytest.mark.asyncio
    async def test_feedback_learning_data_flow(self):
        """Feedback → extract learning data → store in DB."""
        json_response = json.dumps({"learning_feedback": "Use more diverse sources next time."})
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json_response

        with patch("ica.pipeline.theme_selection.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            learning = await extract_learning_data(
                "Need more diversity", "articles json", "theme output"
            )

        assert learning == "Use more diverse sources next time."

        with patch("ica.pipeline.theme_selection.add_note") as mock_add:
            mock_add.return_value = MagicMock()
            mock_session = AsyncMock()
            await store_theme_feedback(mock_session, learning)

        mock_add.assert_awaited_once()


# =========================================================================
# Edge cases
# =========================================================================


class TestEdgeCases:
    """Edge-case tests."""

    def test_format_theme_body_with_windows_line_endings(self):
        body = "%FA_TITLE: Title\r\n%FA_SOURCE: Source\r\nOther"
        result = format_theme_body(body)
        assert "%FA_" not in result

    def test_format_theme_body_consecutive_markers(self):
        body = "%FA_URL: url1\n%M1_URL: url2\n%Q1_URL: url3"
        result = format_theme_body(body)
        assert "url1" not in result
        assert "url2" not in result
        assert "url3" not in result

    def test_extract_theme_with_colon_no_space(self):
        themes = [_make_theme("Test")]
        result = extract_selected_theme("THEME:Test", themes)
        assert result is not None

    def test_format_recommendation_numbered_list(self):
        text = "1. Coverage of industry trends- details\n2. Source diversity- important"
        result = format_recommendation(text)
        assert "*Coverage of industry trends*" in result

    def test_parse_approval_contains_logic(self):
        """n8n uses 'contains' not 'equals' for routing."""
        assert parse_approval_choice("I want to Approve this") == ApprovalChoice.APPROVE
        assert parse_approval_choice("Please Reset everything") == ApprovalChoice.RESET
        assert parse_approval_choice("I have some feedback") == ApprovalChoice.FEEDBACK

    def test_format_selected_theme_body_preserves_content(self):
        """Content that is not a marker should be preserved."""
        body = "Some regular content\nAnother line"
        result = format_selected_theme_body(body)
        assert "Some regular content" in result
        assert "Another line" in result

    def test_build_selection_form_three_themes(self):
        themes = [_make_theme(f"Theme {i}") for i in range(3)]
        form = build_theme_selection_form(themes)
        options = form[0]["fieldOptions"]["values"]
        assert len(options) == 4  # 3 themes + feedback

    def test_selection_preserves_theme_object_identity(self):
        """extract_selected_theme returns the actual theme object, not a copy."""
        theme_a = _make_theme("Alpha")
        theme_b = _make_theme("Beta")
        themes = [theme_a, theme_b]
        result = extract_selected_theme("THEME: Beta", themes)
        assert result is theme_b
