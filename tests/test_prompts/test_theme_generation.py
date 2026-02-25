"""Tests for ica.prompts.theme_generation."""

from __future__ import annotations

import json

from ica.llm_configs import get_process_prompts
from ica.prompts.theme_generation import (
    _FEEDBACK_SECTION_TEMPLATE,
    build_theme_generation_prompt,
)

# Load prompts from JSON config (same source the builder function uses).
_SYSTEM, _INSTRUCTION = get_process_prompts("theme-generation")


# ---------------------------------------------------------------------------
# Constant sanity checks — system prompt
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    """Verify the system prompt contains all required protocol sections."""

    def test_contains_role_description(self):
        assert "professional AI research editor" in _SYSTEM

    def test_contains_json_format_mention(self):
        assert "JSON" in _SYSTEM

    def test_contains_accuracy_control_protocol(self):
        assert "Accuracy Control Protocol (MANDATORY)" in _SYSTEM

    def test_contains_do_not_search(self):
        assert "Do NOT search for alternative sources" in _SYSTEM

    def test_contains_do_not_infer(self):
        assert "Do NOT generate or infer missing details" in _SYSTEM

    def test_contains_use_only_provided_data(self):
        assert "Use ONLY provided data" in _SYSTEM

    def test_contains_industry_news_rule(self):
        assert "industry_news" in _SYSTEM
        assert "%I1_" in _SYSTEM
        assert "%I2_" in _SYSTEM

    def test_mentions_two_themes(self):
        assert "two themes" in _SYSTEM

    def test_mentions_content_distribution(self):
        assert "content distribution" in _SYSTEM

    def test_mentions_source_mix(self):
        assert "source mix" in _SYSTEM

    def test_no_feedback_in_system_prompt(self):
        """Feedback is injected into the user prompt, not the system prompt."""
        assert "Editorial Improvement Context" not in _SYSTEM

    def test_no_placeholders_in_system_prompt(self):
        """System prompt should have no format placeholders."""
        assert "{" not in _SYSTEM
        assert "}" not in _SYSTEM


# ---------------------------------------------------------------------------
# Constant sanity checks — user prompt template
# ---------------------------------------------------------------------------


class TestUserPromptTemplate:
    """Verify the user prompt template contains required placeholders and markers."""

    def test_has_feedback_section_placeholder(self):
        assert "{feedback_section}" in _INSTRUCTION

    def test_has_summaries_json_placeholder(self):
        assert "{summaries_json}" in _INSTRUCTION

    def test_contains_output_format_heading(self):
        assert "Output Format (MANDATORY)" in _INSTRUCTION

    # --- Featured Article markers ---
    def test_contains_fa_title_marker(self):
        assert "%FA_TITLE:" in _INSTRUCTION

    def test_contains_fa_source_marker(self):
        assert "%FA_SOURCE:" in _INSTRUCTION

    def test_contains_fa_origin_marker(self):
        assert "%FA_ORIGIN:" in _INSTRUCTION

    def test_contains_fa_url_marker(self):
        assert "%FA_URL:" in _INSTRUCTION

    def test_contains_fa_category_marker(self):
        assert "%FA_CATEGORY:" in _INSTRUCTION

    def test_contains_fa_why_featured_marker(self):
        assert "%FA_WHY FEATURED:" in _INSTRUCTION

    # --- Main Article markers ---
    def test_contains_m1_markers(self):
        assert "%M1_TITLE:" in _INSTRUCTION
        assert "%M1_SOURCE:" in _INSTRUCTION
        assert "%M1_URL:" in _INSTRUCTION
        assert "%M1_CATEGORY:" in _INSTRUCTION
        assert "%M1_RATIONALE:" in _INSTRUCTION

    def test_contains_m2_markers(self):
        assert "%M2_TITLE:" in _INSTRUCTION
        assert "%M2_SOURCE:" in _INSTRUCTION
        assert "%M2_URL:" in _INSTRUCTION
        assert "%M2_CATEGORY:" in _INSTRUCTION
        assert "%M2_RATIONALE:" in _INSTRUCTION

    # --- Quick Hit markers ---
    def test_contains_q1_markers(self):
        assert "%Q1_TITLE:" in _INSTRUCTION
        assert "%Q1_SOURCE:" in _INSTRUCTION
        assert "%Q1_URL:" in _INSTRUCTION
        assert "%Q1_CATEGORY:" in _INSTRUCTION

    def test_contains_q2_markers(self):
        assert "%Q2_TITLE:" in _INSTRUCTION
        assert "%Q2_SOURCE:" in _INSTRUCTION
        assert "%Q2_URL:" in _INSTRUCTION
        assert "%Q2_CATEGORY:" in _INSTRUCTION

    def test_contains_q3_markers(self):
        assert "%Q3_TITLE:" in _INSTRUCTION
        assert "%Q3_SOURCE:" in _INSTRUCTION
        assert "%Q3_URL:" in _INSTRUCTION
        assert "%Q3_CATEGORY:" in _INSTRUCTION

    # --- Industry Development markers ---
    def test_contains_i1_markers(self):
        assert "%I1_TITLE:" in _INSTRUCTION
        assert "%I1_SOURCE:" in _INSTRUCTION
        assert "%I1_URL:" in _INSTRUCTION
        assert "%I1_Major AI Player:" in _INSTRUCTION

    def test_contains_i2_markers(self):
        assert "%I2_TITLE:" in _INSTRUCTION
        assert "%I2_SOURCE:" in _INSTRUCTION
        assert "%I2_URL:" in _INSTRUCTION
        assert "%I2_Major AI Player:" in _INSTRUCTION

    # --- 2-2-2 Distribution markers ---
    def test_contains_222_distribution_section(self):
        assert "2-2-2 Distribution:" in _INSTRUCTION

    def test_contains_222_tactical(self):
        assert "%222_tactical:%" in _INSTRUCTION

    def test_contains_222_educational(self):
        assert "%222_educational:%" in _INSTRUCTION

    def test_contains_222_forward_thinking(self):
        assert "%222_forward-thinking:%" in _INSTRUCTION

    # --- Source mix markers ---
    def test_contains_source_mix_section(self):
        assert "Source mix:" in _INSTRUCTION

    def test_contains_sm_smaller_publisher(self):
        assert "%SM_smaller_publisher:%" in _INSTRUCTION

    def test_contains_sm_major_ai_player(self):
        assert "%SM_major_ai_player_coverage:%" in _INSTRUCTION

    # --- Requirements Verified markers ---
    def test_contains_requirements_verified_section(self):
        assert "REQUIREMENTS VERIFIED" in _INSTRUCTION

    def test_contains_rv_222_distribution(self):
        assert "%RV_2-2-2 Distribution Achieved:%" in _INSTRUCTION

    def test_contains_rv_source_mix(self):
        assert "%RV_Source mix:%" in _INSTRUCTION

    def test_contains_rv_technical_complexity(self):
        assert "%RV_Technical complexity:%" in _INSTRUCTION

    def test_contains_rv_major_ai_player(self):
        assert "%RV_Major AI player coverage:%" in _INSTRUCTION

    # --- Theme separator and recommendation ---
    def test_contains_theme_separator_instruction(self):
        assert '"-----"' in _INSTRUCTION

    def test_contains_recommendation_section(self):
        assert "RECOMMENDATION:" in _INSTRUCTION

    def test_contains_rationale_section(self):
        assert "Rationale:" in _INSTRUCTION

    def test_contains_theme_heading(self):
        assert "THEME:" in _INSTRUCTION

    def test_contains_theme_description(self):
        assert "Theme Description:" in _INSTRUCTION

    def test_contains_featured_article_heading(self):
        assert "FEATURED ARTICLE:" in _INSTRUCTION

    def test_contains_input_label(self):
        assert "Input:" in _INSTRUCTION


# ---------------------------------------------------------------------------
# Feedback section template
# ---------------------------------------------------------------------------


class TestFeedbackSectionTemplate:
    """Verify the feedback template structure."""

    def test_contains_heading(self):
        assert "Editorial Improvement Context" in _FEEDBACK_SECTION_TEMPLATE

    def test_contains_prior_feedback_label(self):
        assert "From Prior Feedback" in _FEEDBACK_SECTION_TEMPLATE

    def test_contains_placeholder(self):
        assert "{aggregated_feedback}" in _FEEDBACK_SECTION_TEMPLATE

    def test_contains_usage_guidance(self):
        assert "adjust language, flow, and focus" in _FEEDBACK_SECTION_TEMPLATE

    def test_contains_accuracy_caveat(self):
        assert "factual accuracy" in _FEEDBACK_SECTION_TEMPLATE

    def test_renders_with_feedback_text(self):
        rendered = _FEEDBACK_SECTION_TEMPLATE.format(
            aggregated_feedback="- Use shorter theme descriptions",
        )
        assert "Use shorter theme descriptions" in rendered
        assert "{aggregated_feedback}" not in rendered


# ---------------------------------------------------------------------------
# build_theme_generation_prompt — no feedback
# ---------------------------------------------------------------------------


class TestBuildThemeGenerationPromptNoFeedback:
    """Test build_theme_generation_prompt without feedback."""

    SAMPLE_SUMMARIES = json.dumps(
        [
            {
                "Title": "AI Agents Transform Enterprise",
                "Summary": "New platforms enable autonomous workflows.",
                "BusinessRelevance": "Reduces operational costs by 30%.",
                "Order": 1,
                "industry_news": "false",
            },
            {
                "Title": "OpenAI Launches GPT-5",
                "Summary": "OpenAI releases next-gen model.",
                "BusinessRelevance": "Major capability leap for businesses.",
                "Order": 2,
                "industry_news": "true",
            },
        ]
    )

    def test_returns_tuple(self):
        result = build_theme_generation_prompt(self.SAMPLE_SUMMARIES)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_prompt_is_constant(self):
        system, _ = build_theme_generation_prompt(self.SAMPLE_SUMMARIES)
        assert system == _SYSTEM

    def test_user_prompt_contains_summaries(self):
        _, user = build_theme_generation_prompt(self.SAMPLE_SUMMARIES)
        assert "AI Agents Transform Enterprise" in user
        assert "OpenAI Launches GPT-5" in user

    def test_user_prompt_contains_json_data(self):
        _, user = build_theme_generation_prompt(self.SAMPLE_SUMMARIES)
        assert '"Order": 1' in user
        assert '"Order": 2' in user

    def test_no_feedback_section_when_none(self):
        _, user = build_theme_generation_prompt(self.SAMPLE_SUMMARIES, None)
        assert "Editorial Improvement Context" not in user

    def test_no_feedback_section_when_empty(self):
        _, user = build_theme_generation_prompt(self.SAMPLE_SUMMARIES, "")
        assert "Editorial Improvement Context" not in user

    def test_no_feedback_section_when_whitespace(self):
        _, user = build_theme_generation_prompt(self.SAMPLE_SUMMARIES, "   ")
        assert "Editorial Improvement Context" not in user

    def test_user_prompt_contains_output_format(self):
        _, user = build_theme_generation_prompt(self.SAMPLE_SUMMARIES)
        assert "Output Format (MANDATORY)" in user

    def test_user_prompt_contains_markers(self):
        _, user = build_theme_generation_prompt(self.SAMPLE_SUMMARIES)
        assert "%FA_TITLE:" in user
        assert "%M1_TITLE:" in user
        assert "%Q1_TITLE:" in user
        assert "%I1_TITLE:" in user

    def test_user_prompt_contains_recommendation(self):
        _, user = build_theme_generation_prompt(self.SAMPLE_SUMMARIES)
        assert "RECOMMENDATION:" in user

    def test_user_prompt_ends_with_input_data(self):
        _, user = build_theme_generation_prompt(self.SAMPLE_SUMMARIES)
        assert user.rstrip().endswith(self.SAMPLE_SUMMARIES)

    def test_user_prompt_no_unresolved_placeholders(self):
        _, user = build_theme_generation_prompt(self.SAMPLE_SUMMARIES)
        assert "{feedback_section}" not in user
        assert "{summaries_json}" not in user
        assert "{aggregated_feedback}" not in user


# ---------------------------------------------------------------------------
# build_theme_generation_prompt — with feedback
# ---------------------------------------------------------------------------


class TestBuildThemeGenerationPromptWithFeedback:
    """Test build_theme_generation_prompt with feedback injected."""

    SAMPLE_SUMMARIES = json.dumps([{"Title": "Test", "Order": 1}])
    SAMPLE_FEEDBACK = (
        "- Themes should focus more on practical applications\n"
        "- Avoid overly technical language in theme descriptions"
    )

    def test_feedback_section_injected(self):
        _, user = build_theme_generation_prompt(
            self.SAMPLE_SUMMARIES,
            self.SAMPLE_FEEDBACK,
        )
        assert "Editorial Improvement Context" in user

    def test_feedback_text_present(self):
        _, user = build_theme_generation_prompt(
            self.SAMPLE_SUMMARIES,
            self.SAMPLE_FEEDBACK,
        )
        assert "practical applications" in user
        assert "Avoid overly technical language" in user

    def test_feedback_before_output_format(self):
        _, user = build_theme_generation_prompt(
            self.SAMPLE_SUMMARIES,
            self.SAMPLE_FEEDBACK,
        )
        fb_pos = user.index("Editorial Improvement Context")
        fmt_pos = user.index("Output Format (MANDATORY)")
        assert fb_pos < fmt_pos

    def test_feedback_stripped(self):
        _, user = build_theme_generation_prompt(
            self.SAMPLE_SUMMARIES,
            "  leading and trailing whitespace  ",
        )
        assert "leading and trailing whitespace" in user
        # Should not have the extra whitespace around it
        assert "  leading" not in user

    def test_system_prompt_unchanged_with_feedback(self):
        system, _ = build_theme_generation_prompt(
            self.SAMPLE_SUMMARIES,
            self.SAMPLE_FEEDBACK,
        )
        assert system == _SYSTEM

    def test_summaries_still_present_with_feedback(self):
        _, user = build_theme_generation_prompt(
            self.SAMPLE_SUMMARIES,
            self.SAMPLE_FEEDBACK,
        )
        assert '"Title": "Test"' in user

    def test_no_unresolved_placeholders_with_feedback(self):
        _, user = build_theme_generation_prompt(
            self.SAMPLE_SUMMARIES,
            self.SAMPLE_FEEDBACK,
        )
        assert "{feedback_section}" not in user
        assert "{summaries_json}" not in user
        assert "{aggregated_feedback}" not in user


# ---------------------------------------------------------------------------
# Content distribution structure — all article slots present
# ---------------------------------------------------------------------------


class TestContentDistributionSlots:
    """Ensure the prompt specifies the correct article slot structure:
    1 FA + 2 MA + 3 QH + 2 ID = 8 articles per theme.
    """

    def test_one_featured_article(self):
        assert "FEATURED ARTICLE:" in _INSTRUCTION
        # Only one FA prefix set
        assert "%FA_TITLE:" in _INSTRUCTION

    def test_two_main_articles(self):
        assert "%M1_TITLE:" in _INSTRUCTION
        assert "%M2_TITLE:" in _INSTRUCTION

    def test_three_quick_hits(self):
        assert "%Q1_TITLE:" in _INSTRUCTION
        assert "%Q2_TITLE:" in _INSTRUCTION
        assert "%Q3_TITLE:" in _INSTRUCTION

    def test_two_industry_developments(self):
        assert "%I1_TITLE:" in _INSTRUCTION
        assert "%I2_TITLE:" in _INSTRUCTION

    def test_no_extra_main_article_slots(self):
        """Should not have M3 or higher."""
        assert "%M3_" not in _INSTRUCTION

    def test_no_extra_quick_hit_slots(self):
        """Should not have Q4 or higher."""
        assert "%Q4_" not in _INSTRUCTION

    def test_no_extra_industry_dev_slots(self):
        """Should not have I3 or higher."""
        assert "%I3_" not in _INSTRUCTION


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case behavior for build_theme_generation_prompt."""

    def test_empty_json_array(self):
        system, user = build_theme_generation_prompt("[]")
        assert system == _SYSTEM
        assert "[]" in user

    def test_large_summaries_json(self):
        """Prompt should handle large JSON inputs without error."""
        large = json.dumps([{"Title": f"Article {i}", "Order": i} for i in range(50)])
        system, user = build_theme_generation_prompt(large)
        assert "Article 49" in user

    def test_summaries_with_special_characters(self):
        """JSON with special characters should pass through unmodified."""
        data = json.dumps([{"Title": "AI & ML: {next} generation", "Order": 1}])
        _, user = build_theme_generation_prompt(data)
        assert "AI & ML: {next} generation" in user

    def test_feedback_with_newlines(self):
        feedback = "Line 1\nLine 2\nLine 3"
        _, user = build_theme_generation_prompt("[]", feedback)
        assert "Line 1\nLine 2\nLine 3" in user

    def test_multiline_feedback(self):
        feedback = "- Point A\n- Point B\n- Point C"
        _, user = build_theme_generation_prompt("[]", feedback)
        assert "Point A" in user
        assert "Point C" in user
