"""Tests for ica.prompts.markdown_generation."""

from __future__ import annotations

import json

from ica.llm_configs import get_process_prompts
from ica.llm_configs.loader import get_system_prompt
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
    "- Future responses should use shorter sentences\n- Emphasize practical ROI numbers more"
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
    """Verify the generation system prompt is the shared system prompt."""

    def test_is_shared_system_prompt(self):
        assert _GENERATION_SYSTEM == get_system_prompt()

    def test_is_string(self):
        assert isinstance(_GENERATION_SYSTEM, str)

    def test_not_empty(self):
        assert len(_GENERATION_SYSTEM) > 0

    def test_contains_zero_hallucination(self):
        assert "ZERO HALLUCINATION" in _GENERATION_SYSTEM

    def test_contains_strict_output(self):
        assert "STRICT OUTPUT" in _GENERATION_SYSTEM


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

    def test_contains_main_articles_heading(self):
        assert "# *MAIN ARTICLES*" in _GENERATION_INSTRUCTION

    def test_contains_quick_hits_heading(self):
        assert "# *QUICK HITS*" in _GENERATION_INSTRUCTION

    def test_contains_industry_reference(self):
        assert "*INDUSTRY*" in _GENERATION_INSTRUCTION

    def test_contains_footer_heading(self):
        assert "# *FOOTER*" in _GENERATION_INSTRUCTION

    def test_all_sections_present(self):
        sections = [
            "# *INTRODUCTION*",
            "# *QUICK HIGHLIGHTS*",
            "# *FEATURED ARTICLE*",
            "# *MAIN ARTICLES*",
            "# *QUICK HITS*",
            "*INDUSTRY*",
            "# *FOOTER*",
        ]
        for s in sections:
            assert s in _GENERATION_INSTRUCTION, f"Missing section: {s}"

    # --- Section content rules ---

    def test_introduction_rules(self):
        assert "Striking observation" in _GENERATION_INSTRUCTION
        assert "italicized theme summary" in _GENERATION_INSTRUCTION

    def test_quick_highlights_rules(self):
        assert "3 bullets" in _GENERATION_INSTRUCTION
        assert "150-190 chars" in _GENERATION_INSTRUCTION

    def test_featured_article_rules(self):
        assert "300-400 char" in _GENERATION_INSTRUCTION
        assert "Key Insight" in _GENERATION_INSTRUCTION
        assert "300-370 chars" in _GENERATION_INSTRUCTION
        assert "CTA link" in _GENERATION_INSTRUCTION

    def test_featured_article_cta_rules(self):
        prompt = _GENERATION_INSTRUCTION
        assert "'->'." in prompt or "'->" in prompt

    def test_main_article_rules(self):
        assert "max 750 chars" in _GENERATION_INSTRUCTION
        assert "180-250 chars" in _GENERATION_INSTRUCTION
        assert "Strategic Take-away" in _GENERATION_INSTRUCTION

    def test_quick_hits_rules(self):
        assert "# *QUICK HITS*" in _GENERATION_INSTRUCTION
        assert "summaries" in _GENERATION_INSTRUCTION

    def test_industry_rules(self):
        assert "*INDUSTRY*" in _GENERATION_INSTRUCTION
        assert "summaries" in _GENERATION_INSTRUCTION

    def test_footer_rules(self):
        assert "wrap for the week" in _GENERATION_INSTRUCTION
        assert "Thoughts?" in _GENERATION_INSTRUCTION

    def test_url_integrity_rules(self):
        assert "ONLY URLs" in _GENERATION_INSTRUCTION
        assert "Formatting_Integrity" in _GENERATION_INSTRUCTION

    def test_output_instruction(self):
        assert "Markdown output now" in _GENERATION_INSTRUCTION

    def test_no_stray_placeholders(self):
        """Only the four expected placeholders should appear."""
        known = [
            "{feedback_section}",
            "{validator_errors_section}",
            "{formatted_theme}",
            "{previous_markdown}",
        ]
        cleaned = _GENERATION_INSTRUCTION
        for p in known:
            cleaned = cleaned.replace(p, "")
        open_idx = cleaned.index("{") if "{" in cleaned else -1
        assert "{" not in cleaned, (
            f"Stray placeholder in user prompt: {cleaned[open_idx : open_idx + 30]}"
        )
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
        rendered = _FEEDBACK_SECTION_TEMPLATE.format(aggregated_feedback="- Use shorter sentences")
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
        rendered = _VALIDATOR_ERRORS_SECTION_TEMPLATE.format(validator_errors="[error1, error2]")
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

    def test_system_prompt_is_shared(self):
        system, _ = build_markdown_generation_prompt(SAMPLE_THEME)
        assert system == get_system_prompt()

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

    def test_system_prompt_is_original_on_first_generation(self):
        system, _ = build_markdown_generation_prompt(SAMPLE_THEME)
        # Shared system prompt has no format placeholders, so format() is a no-op
        assert system == get_system_prompt()

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

    def test_user_prompt_contains_all_sections(self):
        _, user = build_markdown_generation_prompt(SAMPLE_THEME)
        for section in [
            "# *INTRODUCTION*",
            "# *QUICK HIGHLIGHTS*",
            "# *FEATURED ARTICLE*",
            "# *MAIN ARTICLES*",
            "# *QUICK HITS*",
            "*INDUSTRY*",
            "# *FOOTER*",
        ]:
            assert section in user


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

    def test_previous_markdown_not_in_system(self):
        system, _ = build_markdown_generation_prompt(
            SAMPLE_THEME,
            previous_markdown=SAMPLE_PREVIOUS_MARKDOWN,
        )
        # Shared system prompt has no {previous_markdown} placeholder;
        # format() is a no-op so previous markdown is NOT injected.
        assert "Sample intro paragraph" not in system
        assert system == get_system_prompt()

    def test_full_regeneration_context(self):
        system, user = build_markdown_generation_prompt(
            SAMPLE_THEME,
            aggregated_feedback=SAMPLE_FEEDBACK,
            previous_markdown=SAMPLE_PREVIOUS_MARKDOWN,
            validator_errors=SAMPLE_VALIDATOR_ERRORS,
        )
        # System is always the shared prompt (previous markdown not injected)
        assert system == get_system_prompt()
        assert "Sample intro paragraph" not in system
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
    """Verify the regeneration system prompt is the shared system prompt."""

    def test_is_shared_system_prompt(self):
        assert _REGEN_SYSTEM == get_system_prompt()

    def test_is_string(self):
        assert isinstance(_REGEN_SYSTEM, str)

    def test_not_empty(self):
        assert len(_REGEN_SYSTEM) > 0

    def test_contains_zero_hallucination(self):
        assert "ZERO HALLUCINATION" in _REGEN_SYSTEM

    def test_contains_strict_output(self):
        assert "STRICT OUTPUT" in _REGEN_SYSTEM


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

    def test_system_is_shared_prompt(self):
        system, _ = build_markdown_regeneration_prompt(
            "# Newsletter\nContent here.",
            "Make the intro shorter.",
        )
        # Shared system prompt has no {original_markdown}/{user_feedback}
        # placeholders; format() is a no-op.
        assert system == get_system_prompt()

    def test_original_markdown_not_in_system(self):
        system, _ = build_markdown_regeneration_prompt(
            "# Newsletter\nContent here.",
            "Make the intro shorter.",
        )
        assert "# Newsletter" not in system
        assert "Content here." not in system

    def test_user_feedback_not_in_system(self):
        system, _ = build_markdown_regeneration_prompt(
            "# Newsletter\nContent here.",
            "Make the intro shorter.",
        )
        assert "Make the intro shorter." not in system

    def test_user_prompt_contains_original_and_feedback(self):
        _, user = build_markdown_regeneration_prompt(
            "# Newsletter\nContent here.",
            "Make the intro shorter.",
        )
        # The instruction template interpolates both original_markdown and
        # user_feedback into the XML-tagged user prompt.
        assert "# Newsletter" in user
        assert "Content here." in user
        assert "Make the intro shorter." in user

    def test_no_unresolved_placeholders(self):
        system, _user = build_markdown_regeneration_prompt(
            "Some markdown.",
            "Some feedback.",
        )
        assert "{" not in system
        assert "}" not in system


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
        _system, user = build_markdown_generation_prompt(theme_with_braces)
        assert "Test {with} braces" in user

    def test_multiline_feedback(self):
        feedback = "- Point one\n- Point two\n- Point three"
        _, user = build_markdown_generation_prompt(SAMPLE_THEME, aggregated_feedback=feedback)
        assert "Point one" in user
        assert "Point three" in user

    def test_very_long_previous_markdown_not_in_system(self):
        long_md = "X" * 10000
        system, _ = build_markdown_generation_prompt(SAMPLE_THEME, previous_markdown=long_md)
        # Shared system prompt has no {previous_markdown} placeholder;
        # format() is a no-op so previous markdown is not injected.
        assert long_md not in system
        assert system == get_system_prompt()

    def test_feedback_only_no_errors(self):
        """Feedback present but no validator errors."""
        _, user = build_markdown_generation_prompt(
            SAMPLE_THEME, aggregated_feedback="- Be concise"
        )
        assert "Editorial Improvement Context" in user
        assert "MUST BE RESOLVED" not in user

    def test_errors_only_no_feedback(self):
        """Validator errors present but no feedback."""
        _, user = build_markdown_generation_prompt(SAMPLE_THEME, validator_errors="[some error]")
        assert "MUST BE RESOLVED" in user
        assert "Editorial Improvement Context" not in user
