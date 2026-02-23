"""Tests for ica.prompts.linkedin_carousel."""

from __future__ import annotations

from ica.prompts.linkedin_carousel import (
    LINKEDIN_CAROUSEL_SYSTEM_PROMPT,
    LINKEDIN_CAROUSEL_USER_PROMPT,
    LINKEDIN_REGENERATION_SYSTEM_PROMPT,
    LINKEDIN_REGENERATION_USER_PROMPT,
    build_linkedin_carousel_prompt,
    build_linkedin_regeneration_prompt,
)


# ===========================================================================
# Generation system prompt
# ===========================================================================


class TestLinkedInCarouselSystemPrompt:
    """Verify the generation system prompt contains all required sections."""

    def test_contains_role(self):
        assert "expert editorial AI" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    def test_contains_b2b_context(self):
        assert "B2B AI newsletters" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    def test_contains_linkedin_carousel(self):
        assert "LinkedIn carousel" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    # --- Source rules ---

    def test_contains_critical_source_rules(self):
        assert "CRITICAL SOURCE RULES" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    def test_contains_formatted_theme_source_of_truth(self):
        assert "formattedTheme is the source of truth" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    def test_contains_no_invent_urls(self):
        assert "DO NOT invent or infer URLs" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    # --- Article order ---

    def test_contains_article_order(self):
        assert "ARTICLE ORDER (MUST BE PRESERVED)" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    def test_contains_all_article_types(self):
        assert "FEATURED ARTICLE" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT
        assert "MAIN ARTICLE 1" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT
        assert "MAIN ARTICLE 2" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT
        assert "QUICK HIT 1" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT
        assert "QUICK HIT 2" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT
        assert "QUICK HIT 3" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT
        assert "INDUSTRY DEVELOPMENT 1" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT
        assert "INDUSTRY DEVELOPMENT 2" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    # --- Voice & tone ---

    def test_contains_voice_and_tone(self):
        assert "VOICE & TONE" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    def test_contains_professional_tone(self):
        assert "Professional, conversational, and authoritative" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    # --- Technical specifications ---

    def test_contains_technical_specs(self):
        assert "TECHNICAL SPECIFICATIONS" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    def test_contains_slide_body_char_range(self):
        assert "265-315 characters" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    def test_contains_target_290(self):
        assert "~290 characters" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    def test_contains_paragraph_1_range(self):
        assert "120-150 characters" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    def test_contains_paragraph_2_range(self):
        assert "130-150 characters" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    def test_contains_tldr_bullet_target(self):
        assert "~50 characters target" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    # --- LinkedIn post copy ---

    def test_contains_post_copy_section(self):
        assert "LINKEDIN POST COPY (3 VERSIONS)" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    def test_contains_feeling_behind_hook(self):
        assert "Feeling behind on AI" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    def test_contains_is2_digital(self):
        assert "iS2 Digital" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    def test_contains_3_4_lines(self):
        assert "3-4 short, scannable lines" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    # --- Carousel content ---

    def test_contains_tldr_section(self):
        assert "TL;DR SECTION" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    def test_contains_8_bullets(self):
        assert "8 bullets total" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    def test_contains_slides_3_10(self):
        assert "SLIDES 3-10" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    def test_contains_character_errors_handling(self):
        assert "character_errors" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    # --- Slack formatting ---

    def test_contains_slack_formatting_rules(self):
        assert "SLACK FORMATTING RULES" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    def test_contains_single_asterisks_rule(self):
        assert "single asterisks" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    def test_contains_no_double_asterisks(self):
        assert "Do NOT use **double asterisks**" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    # --- Final rules ---

    def test_contains_final_execution_rules(self):
        assert "FINAL EXECUTION RULES" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    def test_contains_no_add_remove_slides(self):
        assert "Do NOT add or remove slides" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT


# ===========================================================================
# Generation user prompt
# ===========================================================================


class TestLinkedInCarouselUserPrompt:
    """Verify the generation user prompt template."""

    def test_contains_formatted_theme_placeholder(self):
        assert "{formatted_theme}" in LINKEDIN_CAROUSEL_USER_PROMPT

    def test_contains_newsletter_content_placeholder(self):
        assert "{newsletter_content}" in LINKEDIN_CAROUSEL_USER_PROMPT

    def test_contains_previous_output_placeholder(self):
        assert "{previous_output}" in LINKEDIN_CAROUSEL_USER_PROMPT

    def test_contains_output_format(self):
        assert "OUTPUT FORMAT" in LINKEDIN_CAROUSEL_USER_PROMPT

    def test_contains_version_labels(self):
        assert "*Version 1*" in LINKEDIN_CAROUSEL_USER_PROMPT
        assert "*Version 2*" in LINKEDIN_CAROUSEL_USER_PROMPT
        assert "*Version 3*" in LINKEDIN_CAROUSEL_USER_PROMPT

    def test_contains_tldr_section(self):
        assert "TL;DR" in LINKEDIN_CAROUSEL_USER_PROMPT

    def test_contains_slide_3_label(self):
        assert "Slide 3" in LINKEDIN_CAROUSEL_USER_PROMPT


# ===========================================================================
# Regeneration system prompt
# ===========================================================================


class TestLinkedInRegenerationSystemPrompt:
    """Verify the regeneration system prompt."""

    def test_contains_revision_pass(self):
        assert "revision pass" in LINKEDIN_REGENERATION_SYSTEM_PROMPT

    def test_contains_not_new_generation(self):
        assert "not a new generation" in LINKEDIN_REGENERATION_SYSTEM_PROMPT

    # --- Critical execution rules ---

    def test_contains_critical_rules(self):
        assert "CRITICAL EXECUTION RULES" in LINKEDIN_REGENERATION_SYSTEM_PROMPT

    def test_contains_source_of_truth(self):
        assert "source of truth" in LINKEDIN_REGENERATION_SYSTEM_PROMPT

    def test_contains_apply_only_feedback(self):
        assert "Apply ONLY the feedback" in LINKEDIN_REGENERATION_SYSTEM_PROMPT

    def test_contains_do_not_recreate(self):
        assert "Do NOT recreate content" in LINKEDIN_REGENERATION_SYSTEM_PROMPT

    def test_contains_preserve_voice(self):
        assert "Preserve voice, tone, and framing" in LINKEDIN_REGENERATION_SYSTEM_PROMPT

    # --- Structure locked ---

    def test_contains_structure_locked(self):
        assert "STRUCTURE & ORDER (LOCKED)" in LINKEDIN_REGENERATION_SYSTEM_PROMPT

    def test_contains_unchanged_rules(self):
        assert "Article order must remain unchanged" in LINKEDIN_REGENERATION_SYSTEM_PROMPT
        assert "Slide numbering must remain unchanged" in LINKEDIN_REGENERATION_SYSTEM_PROMPT

    # --- Technical specs ---

    def test_contains_char_range(self):
        assert "265-315 characters" in LINKEDIN_REGENERATION_SYSTEM_PROMPT

    # --- Slack formatting ---

    def test_contains_slack_formatting(self):
        assert "SLACK FORMATTING RULES" in LINKEDIN_REGENERATION_SYSTEM_PROMPT


# ===========================================================================
# Regeneration user prompt
# ===========================================================================


class TestLinkedInRegenerationUserPrompt:
    """Verify the regeneration user prompt template."""

    def test_contains_previous_output_placeholder(self):
        assert "{previous_output}" in LINKEDIN_REGENERATION_USER_PROMPT

    def test_contains_feedback_placeholder(self):
        assert "{feedback_text}" in LINKEDIN_REGENERATION_USER_PROMPT

    def test_contains_formatted_theme_placeholder(self):
        assert "{formatted_theme}" in LINKEDIN_REGENERATION_USER_PROMPT

    def test_contains_newsletter_content_placeholder(self):
        assert "{newsletter_content}" in LINKEDIN_REGENERATION_USER_PROMPT

    def test_contains_output_format(self):
        assert "OUTPUT FORMAT" in LINKEDIN_REGENERATION_USER_PROMPT

    def test_contains_primary_source_label(self):
        assert "PRIMARY SOURCE" in LINKEDIN_REGENERATION_USER_PROMPT

    def test_contains_primary_authority_label(self):
        assert "PRIMARY AUTHORITY" in LINKEDIN_REGENERATION_USER_PROMPT

    def test_contains_read_only_labels(self):
        assert "READ-ONLY" in LINKEDIN_REGENERATION_USER_PROMPT


# ===========================================================================
# Builder functions
# ===========================================================================


class TestBuildLinkedInCarouselPrompt:
    """Verify the generation builder function."""

    def test_returns_tuple(self):
        result = build_linkedin_carousel_prompt("theme", "content")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_prompt_is_constant(self):
        sys_prompt, _ = build_linkedin_carousel_prompt("theme", "content")
        assert sys_prompt is LINKEDIN_CAROUSEL_SYSTEM_PROMPT

    def test_user_prompt_contains_formatted_theme(self):
        _, user_prompt = build_linkedin_carousel_prompt("my theme data", "content")
        assert "my theme data" in user_prompt

    def test_user_prompt_contains_newsletter_content(self):
        _, user_prompt = build_linkedin_carousel_prompt("theme", "my newsletter html")
        assert "my newsletter html" in user_prompt

    def test_no_previous_output_shows_none(self):
        _, user_prompt = build_linkedin_carousel_prompt("theme", "content")
        assert "None" in user_prompt

    def test_empty_previous_output_shows_none(self):
        _, user_prompt = build_linkedin_carousel_prompt("theme", "content", "")
        assert "None" in user_prompt

    def test_previous_output_included(self):
        _, user_prompt = build_linkedin_carousel_prompt(
            "theme", "content", "previous carousel"
        )
        assert "previous carousel" in user_prompt
        assert "None" not in user_prompt.split("Previously generated output")[1]

    def test_different_themes_produce_different_prompts(self):
        _, prompt_a = build_linkedin_carousel_prompt("theme A", "content")
        _, prompt_b = build_linkedin_carousel_prompt("theme B", "content")
        assert prompt_a != prompt_b

    def test_system_prompt_unchanged_with_previous_output(self):
        sys_a, _ = build_linkedin_carousel_prompt("theme", "content")
        sys_b, _ = build_linkedin_carousel_prompt("theme", "content", "prev")
        assert sys_a == sys_b


class TestBuildLinkedInRegenerationPrompt:
    """Verify the regeneration builder function."""

    def test_returns_tuple(self):
        result = build_linkedin_regeneration_prompt(
            "previous", "feedback", "theme", "content"
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_prompt_is_constant(self):
        sys_prompt, _ = build_linkedin_regeneration_prompt(
            "previous", "feedback", "theme", "content"
        )
        assert sys_prompt is LINKEDIN_REGENERATION_SYSTEM_PROMPT

    def test_user_prompt_contains_previous_output(self):
        _, user_prompt = build_linkedin_regeneration_prompt(
            "my previous output", "feedback", "theme", "content"
        )
        assert "my previous output" in user_prompt

    def test_user_prompt_contains_feedback(self):
        _, user_prompt = build_linkedin_regeneration_prompt(
            "previous", "make slides punchier", "theme", "content"
        )
        assert "make slides punchier" in user_prompt

    def test_user_prompt_contains_formatted_theme(self):
        _, user_prompt = build_linkedin_regeneration_prompt(
            "previous", "feedback", "ref theme data", "content"
        )
        assert "ref theme data" in user_prompt

    def test_user_prompt_contains_newsletter_content(self):
        _, user_prompt = build_linkedin_regeneration_prompt(
            "previous", "feedback", "theme", "html newsletter"
        )
        assert "html newsletter" in user_prompt

    def test_different_feedback_produces_different_prompts(self):
        _, prompt_a = build_linkedin_regeneration_prompt(
            "prev", "fix A", "theme", "content"
        )
        _, prompt_b = build_linkedin_regeneration_prompt(
            "prev", "fix B", "theme", "content"
        )
        assert prompt_a != prompt_b
