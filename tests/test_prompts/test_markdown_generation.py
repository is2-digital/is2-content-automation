"""Tests for ica.prompts.markdown_generation."""

from __future__ import annotations

import json

from ica.llm_configs import get_process_prompts
from ica.prompts.markdown_generation import (
    _FEEDBACK_SECTION_TEMPLATE,
    _VALIDATOR_ERRORS_SECTION_TEMPLATE,
    build_markdown_generation_prompt,
    build_markdown_regeneration_prompt,
)

# Load prompts from JSON config (same source the builder functions use).
_GENERATION_SYSTEM, _GENERATION_INSTRUCTION = get_process_prompts("markdown-generation")
_REGEN_SYSTEM, _REGEN_INSTRUCTION = get_process_prompts("markdown-regeneration")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_THEME = json.dumps(
    {
        "THEME": "AI Governance in Practice",
        "FEATURED ARTICLE": {
            "Title": "How enterprises build AI frameworks",
            "Source": "TechCrunch",
            "URL": "https://example.com/featured",
            "Category": "AI Strategy",
            "Why Featured": "Comprehensive framework analysis",
        },
        "MAIN ARTICLE 1": {
            "Title": "Cost savings from AI deployment",
            "Source": "Forbes",
            "URL": "https://example.com/main1",
            "Category": "Business Impact",
        },
        "MAIN ARTICLE 2": {
            "Title": "AI model benchmarking trends",
            "Source": "MIT Tech Review",
            "URL": "https://example.com/main2",
            "Category": "Research",
        },
        "QUICK HIT 1": {
            "Title": "Quick hit one",
            "Source": "Wired",
            "URL": "https://example.com/qh1",
        },
        "QUICK HIT 2": {
            "Title": "Quick hit two",
            "Source": "Ars Technica",
            "URL": "https://example.com/qh2",
        },
        "QUICK HIT 3": {
            "Title": "Quick hit three",
            "Source": "VentureBeat",
            "URL": "https://example.com/qh3",
        },
        "INDUSTRY DEVELOPMENT 1": {
            "Title": "OpenAI launches new model",
            "Source": "Reuters",
            "URL": "https://example.com/id1",
            "Major AI Player": "OpenAI",
        },
        "INDUSTRY DEVELOPMENT 2": {
            "Title": "Google expands AI services",
            "Source": "Bloomberg",
            "URL": "https://example.com/id2",
            "Major AI Player": "Google",
        },
    },
    indent=2,
)

SAMPLE_FEEDBACK = (
    "- Future responses should use shorter sentences\n"
    "- Emphasize practical ROI numbers more"
)

SAMPLE_PREVIOUS_MARKDOWN = "# *INTRODUCTION*\n\nSample intro paragraph."

SAMPLE_VALIDATOR_ERRORS = json.dumps(
    [
        "Featured Article – Paragraph 1 – current=250 – target=300-400 – delta=-50",
        "Footer – Paragraph 2 – current=180 – target=200-550 – delta=-20",
    ]
)


# ---------------------------------------------------------------------------
# System prompt constant checks
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    """Verify the system prompt contains all required protocol sections."""

    def test_contains_role_description(self):
        assert "expert editorial AI" in _GENERATION_SYSTEM

    def test_contains_b2b_newsletter_mention(self):
        assert "B2B newsletters" in _GENERATION_SYSTEM

    def test_contains_json_input_constraint(self):
        assert "ONLY the content and URLs explicitly present in the JSON input" in (
            _GENERATION_SYSTEM
        )

    def test_contains_previous_markdown_placeholder(self):
        assert "{previous_markdown}" in _GENERATION_SYSTEM

    def test_contains_validator_error_handling(self):
        assert "validator errors" in _GENERATION_SYSTEM

    def test_contains_delta_instructions(self):
        assert "delta" in _GENERATION_SYSTEM
        assert "EXACTLY the specified number of characters" in (
            _GENERATION_SYSTEM
        )

    def test_contains_fix_order(self):
        assert "FIX ORDER (MANDATORY)" in _GENERATION_SYSTEM

    def test_fix_order_sequence(self):
        prompt = _GENERATION_SYSTEM
        p1_pos = prompt.index("Featured Article – Paragraph 1")
        p2_pos = prompt.index("Featured Article – Paragraph 2")
        ki_pos = prompt.index("Featured Article – Key Insight")
        ma_pos = prompt.index("Main Articles", ki_pos)
        id_pos = prompt.index("Industry Developments", ma_pos)
        ft_pos = prompt.index("Footer", id_pos)
        assert p1_pos < p2_pos < ki_pos < ma_pos < id_pos < ft_pos

    def test_contains_output_rules(self):
        assert "OUTPUT RULES" in _GENERATION_SYSTEM

    def test_contains_exact_headings_rule(self):
        assert "EXACT section headings" in _GENERATION_SYSTEM

    def test_contains_hard_constraints(self):
        assert "HARD CONSTRAINTS (NON-NEGOTIABLE)" in _GENERATION_SYSTEM

    def test_contains_url_invention_ban(self):
        assert "MAY NOT invent, infer, autocomplete, or substitute URLs" in (
            _GENERATION_SYSTEM
        )

    # --- Voice calibration ---

    def test_contains_voice_calibration_header(self):
        assert "VOICE CALIBRATION" in _GENERATION_SYSTEM

    def test_contains_precision_as_principle(self):
        assert "PRECISION AS PRINCIPLE" in _GENERATION_SYSTEM

    def test_contains_direct_authority(self):
        assert "DIRECT AUTHORITY WITHOUT ARROGANCE" in _GENERATION_SYSTEM

    def test_contains_conversational_but_not_casual(self):
        assert "CONVERSATIONAL BUT NOT CASUAL" in _GENERATION_SYSTEM

    def test_contains_intellectual_honesty(self):
        assert "INTELLECTUAL HONESTY" in _GENERATION_SYSTEM

    def test_contains_practical_grounding(self):
        assert "PRACTICAL GROUNDING" in _GENERATION_SYSTEM

    def test_contains_dry_humor(self):
        assert "DRY HUMOR" in _GENERATION_SYSTEM

    def test_contains_strategic_synthesis(self):
        assert "STRATEGIC SYNTHESIS" in _GENERATION_SYSTEM

    def test_contains_bold_formatting(self):
        assert "BOLD FORMATTING FOR EMPHASIS" in _GENERATION_SYSTEM

    def test_contains_directive_language(self):
        assert "DIRECTIVE LANGUAGE" in _GENERATION_SYSTEM

    def test_contains_three_acceptable_patterns(self):
        assert "Pattern A" in _GENERATION_SYSTEM
        assert "Pattern B" in _GENERATION_SYSTEM
        assert "Pattern C" in _GENERATION_SYSTEM

    def test_pattern_a_is_primary(self):
        assert "PRIMARY PATTERN" in _GENERATION_SYSTEM

    def test_pattern_c_callout_only(self):
        assert "CALLOUT BOXES ONLY" in _GENERATION_SYSTEM

    def test_contains_language_to_avoid(self):
        assert "LANGUAGE TO AVOID" in _GENERATION_SYSTEM

    def test_contains_application_by_section(self):
        assert "APPLICATION BY SECTION" in _GENERATION_SYSTEM

    def test_contains_kevin_voice_examples(self):
        """Check that representative voice examples from the n8n prompt are present."""
        assert "strongly caution" in _GENERATION_SYSTEM
        assert "garbage in, garbage out" in _GENERATION_SYSTEM

    def test_system_prompt_has_only_previous_markdown_placeholder(self):
        """System prompt should only have {previous_markdown} as placeholder."""
        # Replace the known placeholder to check there are no unexpected ones
        cleaned = _GENERATION_SYSTEM.replace("{previous_markdown}", "")
        # Bold markdown like **term** contains no braces; check no stray {
        assert "{" not in cleaned
        assert "}" not in cleaned


# ---------------------------------------------------------------------------
# User prompt template checks
# ---------------------------------------------------------------------------


class TestUserPromptTemplate:
    """Verify the user prompt template contains required placeholders and sections."""

    def test_has_feedback_section_placeholder(self):
        assert "{feedback_section}" in _GENERATION_INSTRUCTION

    def test_has_validator_errors_section_placeholder(self):
        assert "{validator_errors_section}" in _GENERATION_INSTRUCTION

    def test_has_formatted_theme_placeholder(self):
        assert "{formatted_theme}" in _GENERATION_INSTRUCTION

    # --- Required section headings ---

    def test_contains_introduction_heading(self):
        assert "# *INTRODUCTION*" in _GENERATION_INSTRUCTION

    def test_contains_quick_highlights_heading(self):
        assert "# *QUICK HIGHLIGHTS*" in _GENERATION_INSTRUCTION

    def test_contains_featured_article_heading(self):
        assert "# *FEATURED ARTICLE*" in _GENERATION_INSTRUCTION

    def test_contains_main_article_1_heading(self):
        assert "# *MAIN ARTICLE 1*" in _GENERATION_INSTRUCTION

    def test_contains_main_article_2_heading(self):
        assert "# *MAIN ARTICLE 2*" in _GENERATION_INSTRUCTION

    def test_contains_quick_hits_heading(self):
        assert "# *QUICK HITS*" in _GENERATION_INSTRUCTION

    def test_contains_industry_developments_heading(self):
        assert "# *INDUSTRY DEVELOPMENTS*" in _GENERATION_INSTRUCTION

    def test_contains_footer_heading(self):
        assert "# *FOOTER*" in _GENERATION_INSTRUCTION

    def test_all_eight_sections_present(self):
        headings = [
            "# *INTRODUCTION*",
            "# *QUICK HIGHLIGHTS*",
            "# *FEATURED ARTICLE*",
            "# *MAIN ARTICLE 1*",
            "# *MAIN ARTICLE 2*",
            "# *QUICK HITS*",
            "# *INDUSTRY DEVELOPMENTS*",
            "# *FOOTER*",
        ]
        for h in headings:
            assert h in _GENERATION_INSTRUCTION, f"Missing heading: {h}"

    # --- Section content rules ---

    def test_introduction_rules(self):
        assert "Conversational opening paragraph" in _GENERATION_INSTRUCTION
        assert "Italic theme summary" in _GENERATION_INSTRUCTION

    def test_quick_highlights_rules(self):
        assert "3 bullet points" in _GENERATION_INSTRUCTION
        assert "150-190 characters" in _GENERATION_INSTRUCTION

    def test_featured_article_rules(self):
        assert "300-400 characters" in _GENERATION_INSTRUCTION
        assert "Key Insight Paragraph" in _GENERATION_INSTRUCTION
        assert "300-370 characters" in _GENERATION_INSTRUCTION
        assert "CTA Link" in _GENERATION_INSTRUCTION

    def test_featured_article_cta_rules(self):
        prompt = _GENERATION_INSTRUCTION
        assert '2-4 words' in prompt
        assert 'end with' in prompt

    def test_main_article_rules(self):
        assert "max 750 chars" in _GENERATION_INSTRUCTION
        assert "180-250 chars" in _GENERATION_INSTRUCTION
        assert "Strategic Take-away" in _GENERATION_INSTRUCTION
        assert "Actionable Steps" in _GENERATION_INSTRUCTION

    def test_quick_hits_rules(self):
        assert "3 items" in _GENERATION_INSTRUCTION

    def test_industry_developments_rules(self):
        assert "2 items" in _GENERATION_INSTRUCTION
        assert "major AI company" in _GENERATION_INSTRUCTION

    def test_footer_rules(self):
        assert "Reflective paragraph" in _GENERATION_INSTRUCTION
        assert "tie back to the theme" in _GENERATION_INSTRUCTION

    def test_link_rules(self):
        assert "LINK RULES" in _GENERATION_INSTRUCTION
        assert "ONLY URLs found" in _GENERATION_INSTRUCTION

    def test_final_instructions(self):
        assert "FINAL INSTRUCTIONS" in _GENERATION_INSTRUCTION
        assert "only the final newsletter in valid Markdown" in (
            _GENERATION_INSTRUCTION
        )

    def test_no_stray_placeholders(self):
        """Only the three expected placeholders should appear."""
        known = ["{feedback_section}", "{validator_errors_section}", "{formatted_theme}"]
        cleaned = _GENERATION_INSTRUCTION
        for p in known:
            cleaned = cleaned.replace(p, "")
        assert "{" not in cleaned, f"Stray placeholder in user prompt: {cleaned[cleaned.index('{'):cleaned.index('{')+30]}"
        assert "}" not in cleaned


# ---------------------------------------------------------------------------
# Feedback section template checks
# ---------------------------------------------------------------------------


class TestFeedbackSectionTemplate:
    """Verify the feedback section template."""

    def test_has_aggregated_feedback_placeholder(self):
        assert "{aggregated_feedback}" in _FEEDBACK_SECTION_TEMPLATE

    def test_contains_editorial_context_header(self):
        assert "Editorial Improvement Context" in _FEEDBACK_SECTION_TEMPLATE

    def test_renders_feedback(self):
        rendered = _FEEDBACK_SECTION_TEMPLATE.format(
            aggregated_feedback="- Use shorter sentences"
        )
        assert "- Use shorter sentences" in rendered
        assert "{" not in rendered


# ---------------------------------------------------------------------------
# Validator errors section template checks
# ---------------------------------------------------------------------------


class TestValidatorErrorsSectionTemplate:
    """Verify the validator errors section template."""

    def test_has_validator_errors_placeholder(self):
        assert "{validator_errors}" in _VALIDATOR_ERRORS_SECTION_TEMPLATE

    def test_contains_must_be_resolved(self):
        assert "MUST BE RESOLVED" in _VALIDATOR_ERRORS_SECTION_TEMPLATE

    def test_renders_errors(self):
        rendered = _VALIDATOR_ERRORS_SECTION_TEMPLATE.format(
            validator_errors="[error1, error2]"
        )
        assert "[error1, error2]" in rendered
        assert "{" not in rendered


# ---------------------------------------------------------------------------
# build_markdown_generation_prompt — first generation (no feedback/errors)
# ---------------------------------------------------------------------------


class TestBuildPromptFirstGeneration:
    """Test build_markdown_generation_prompt with minimal inputs (first attempt)."""

    def test_returns_tuple(self):
        result = build_markdown_generation_prompt(SAMPLE_THEME)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_prompt_type(self):
        system, _ = build_markdown_generation_prompt(SAMPLE_THEME)
        assert isinstance(system, str)

    def test_user_prompt_type(self):
        _, user = build_markdown_generation_prompt(SAMPLE_THEME)
        assert isinstance(user, str)

    def test_system_prompt_contains_role(self):
        system, _ = build_markdown_generation_prompt(SAMPLE_THEME)
        assert "expert editorial AI" in system

    def test_user_prompt_contains_theme_data(self):
        _, user = build_markdown_generation_prompt(SAMPLE_THEME)
        assert "AI Governance in Practice" in user
        assert "https://example.com/featured" in user

    def test_no_feedback_section_when_empty(self):
        _, user = build_markdown_generation_prompt(SAMPLE_THEME)
        assert "Editorial Improvement Context" not in user

    def test_no_validator_errors_when_empty(self):
        _, user = build_markdown_generation_prompt(SAMPLE_THEME)
        assert "MUST BE RESOLVED" not in user

    def test_previous_markdown_empty_by_default(self):
        system, _ = build_markdown_generation_prompt(SAMPLE_THEME)
        # The placeholder is replaced; it should show empty between the markers
        assert "PREVIOUS NEWSLETTER OUTPUT:" in system

    def test_system_has_no_unresolved_placeholders(self):
        system, _ = build_markdown_generation_prompt(SAMPLE_THEME)
        assert "{" not in system
        assert "}" not in system

    def test_user_has_no_unresolved_placeholders(self):
        _, user = build_markdown_generation_prompt(SAMPLE_THEME)
        # JSON theme data contains literal braces, so check for format placeholders
        assert "{feedback_section}" not in user
        assert "{validator_errors_section}" not in user
        assert "{formatted_theme}" not in user

    def test_user_prompt_contains_all_headings(self):
        _, user = build_markdown_generation_prompt(SAMPLE_THEME)
        for heading in [
            "# *INTRODUCTION*",
            "# *QUICK HIGHLIGHTS*",
            "# *FEATURED ARTICLE*",
            "# *MAIN ARTICLE 1*",
            "# *MAIN ARTICLE 2*",
            "# *QUICK HITS*",
            "# *INDUSTRY DEVELOPMENTS*",
            "# *FOOTER*",
        ]:
            assert heading in user


# ---------------------------------------------------------------------------
# build_markdown_generation_prompt — with feedback
# ---------------------------------------------------------------------------


class TestBuildPromptWithFeedback:
    """Test build_markdown_generation_prompt with aggregated feedback."""

    def test_feedback_section_injected(self):
        _, user = build_markdown_generation_prompt(
            SAMPLE_THEME, aggregated_feedback=SAMPLE_FEEDBACK
        )
        assert "Editorial Improvement Context" in user

    def test_feedback_content_present(self):
        _, user = build_markdown_generation_prompt(
            SAMPLE_THEME, aggregated_feedback=SAMPLE_FEEDBACK
        )
        assert "shorter sentences" in user
        assert "ROI numbers" in user

    def test_system_unchanged_by_feedback(self):
        system_no_fb, _ = build_markdown_generation_prompt(SAMPLE_THEME)
        system_with_fb, _ = build_markdown_generation_prompt(
            SAMPLE_THEME, aggregated_feedback=SAMPLE_FEEDBACK
        )
        assert system_no_fb == system_with_fb

    def test_no_unresolved_placeholders_with_feedback(self):
        _, user = build_markdown_generation_prompt(
            SAMPLE_THEME, aggregated_feedback=SAMPLE_FEEDBACK
        )
        assert "{feedback_section}" not in user
        assert "{validator_errors_section}" not in user
        assert "{formatted_theme}" not in user
        assert "{aggregated_feedback}" not in user


# ---------------------------------------------------------------------------
# build_markdown_generation_prompt — with validator errors (regeneration)
# ---------------------------------------------------------------------------


class TestBuildPromptWithValidatorErrors:
    """Test build_markdown_generation_prompt during validator-driven regeneration."""

    def test_validator_errors_section_injected(self):
        _, user = build_markdown_generation_prompt(
            SAMPLE_THEME,
            validator_errors=SAMPLE_VALIDATOR_ERRORS,
        )
        assert "MUST BE RESOLVED" in user

    def test_validator_errors_content_present(self):
        _, user = build_markdown_generation_prompt(
            SAMPLE_THEME,
            validator_errors=SAMPLE_VALIDATOR_ERRORS,
        )
        assert "Featured Article" in user
        assert "delta" in user

    def test_previous_markdown_injected(self):
        system, _ = build_markdown_generation_prompt(
            SAMPLE_THEME,
            previous_markdown=SAMPLE_PREVIOUS_MARKDOWN,
        )
        assert "Sample intro paragraph" in system

    def test_full_regeneration_context(self):
        system, user = build_markdown_generation_prompt(
            SAMPLE_THEME,
            aggregated_feedback=SAMPLE_FEEDBACK,
            previous_markdown=SAMPLE_PREVIOUS_MARKDOWN,
            validator_errors=SAMPLE_VALIDATOR_ERRORS,
        )
        # System has previous markdown
        assert "Sample intro paragraph" in system
        # User has feedback
        assert "Editorial Improvement Context" in user
        # User has validator errors
        assert "MUST BE RESOLVED" in user
        # User has theme data
        assert "AI Governance in Practice" in user

    def test_no_unresolved_placeholders_full_context(self):
        system, user = build_markdown_generation_prompt(
            SAMPLE_THEME,
            aggregated_feedback=SAMPLE_FEEDBACK,
            previous_markdown=SAMPLE_PREVIOUS_MARKDOWN,
            validator_errors=SAMPLE_VALIDATOR_ERRORS,
        )
        assert "{previous_markdown}" not in system
        for placeholder in [
            "{feedback_section}",
            "{validator_errors_section}",
            "{formatted_theme}",
            "{aggregated_feedback}",
            "{validator_errors}",
        ]:
            assert placeholder not in user


# ---------------------------------------------------------------------------
# Regeneration prompt checks
# ---------------------------------------------------------------------------


class TestRegenerationSystemPrompt:
    """Verify the regeneration prompt template."""

    def test_contains_role(self):
        assert "professional content editor" in _REGEN_SYSTEM

    def test_contains_original_markdown_placeholder(self):
        assert "{original_markdown}" in _REGEN_SYSTEM

    def test_contains_user_feedback_placeholder(self):
        assert "{user_feedback}" in _REGEN_SYSTEM

    def test_contains_revision_rules(self):
        assert "REVISION RULES" in _REGEN_SYSTEM

    def test_contains_preserve_rules(self):
        assert "Preserve exactly" in _REGEN_SYSTEM
        assert "section headings" in _REGEN_SYSTEM
        assert "URLs exactly" in _REGEN_SYSTEM

    def test_contains_output_rules(self):
        assert "only the fully revised newsletter" in _REGEN_SYSTEM

    def test_only_expected_placeholders(self):
        cleaned = _REGEN_SYSTEM
        cleaned = cleaned.replace("{original_markdown}", "")
        cleaned = cleaned.replace("{user_feedback}", "")
        assert "{" not in cleaned
        assert "}" not in cleaned


# ---------------------------------------------------------------------------
# build_markdown_regeneration_prompt
# ---------------------------------------------------------------------------


class TestBuildRegenerationPrompt:
    """Test build_markdown_regeneration_prompt."""

    def test_returns_tuple(self):
        result = build_markdown_regeneration_prompt(
            "# Newsletter\nContent here.",
            "Make the intro shorter.",
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_contains_original_markdown(self):
        system, _ = build_markdown_regeneration_prompt(
            "# Newsletter\nContent here.",
            "Make the intro shorter.",
        )
        assert "# Newsletter" in system
        assert "Content here." in system

    def test_system_contains_user_feedback(self):
        system, _ = build_markdown_regeneration_prompt(
            "# Newsletter\nContent here.",
            "Make the intro shorter.",
        )
        assert "Make the intro shorter." in system

    def test_user_message_is_feedback(self):
        _, user = build_markdown_regeneration_prompt(
            "# Newsletter\nContent here.",
            "Make the intro shorter.",
        )
        assert user == "Make the intro shorter."

    def test_no_unresolved_placeholders(self):
        system, user = build_markdown_regeneration_prompt(
            "Some markdown.",
            "Some feedback.",
        )
        assert "{" not in system
        assert "}" not in system

    def test_preserves_markdown_formatting(self):
        original = "# *INTRODUCTION*\n\n**Bold text** and *italic*."
        system, _ = build_markdown_regeneration_prompt(original, "feedback")
        assert "**Bold text**" in system
        assert "*italic*" in system

    def test_preserves_urls_in_original(self):
        original = "[Read more](https://example.com/article) for details."
        system, _ = build_markdown_regeneration_prompt(original, "feedback")
        assert "https://example.com/article" in system


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_theme_string(self):
        """Empty theme is allowed (produces valid prompt with empty data section)."""
        system, user = build_markdown_generation_prompt("")
        assert "{" not in system
        assert "{" not in user

    def test_theme_with_special_characters(self):
        """Theme data containing braces should not break formatting."""
        theme_with_braces = json.dumps({"title": "Test {with} braces"})
        # This would raise KeyError if there were stray placeholders
        system, user = build_markdown_generation_prompt(theme_with_braces)
        assert "Test {with} braces" in user

    def test_multiline_feedback(self):
        feedback = "- Point one\n- Point two\n- Point three"
        _, user = build_markdown_generation_prompt(
            SAMPLE_THEME, aggregated_feedback=feedback
        )
        assert "Point one" in user
        assert "Point three" in user

    def test_very_long_previous_markdown(self):
        long_md = "X" * 10000
        system, _ = build_markdown_generation_prompt(
            SAMPLE_THEME, previous_markdown=long_md
        )
        assert long_md in system

    def test_feedback_only_no_errors(self):
        """Feedback present but no validator errors."""
        _, user = build_markdown_generation_prompt(
            SAMPLE_THEME, aggregated_feedback="- Be concise"
        )
        assert "Editorial Improvement Context" in user
        assert "MUST BE RESOLVED" not in user

    def test_errors_only_no_feedback(self):
        """Validator errors present but no feedback."""
        _, user = build_markdown_generation_prompt(
            SAMPLE_THEME, validator_errors="[some error]"
        )
        assert "MUST BE RESOLVED" in user
        assert "Editorial Improvement Context" not in user
