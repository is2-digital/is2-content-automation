"""Tests for ica.prompts.linkedin_carousel."""

from __future__ import annotations

from ica.llm_configs import get_process_prompts
from ica.llm_configs.loader import get_system_prompt
from ica.prompts.linkedin_carousel import (
    build_linkedin_carousel_prompt,
    build_linkedin_regeneration_prompt,
)

# Load prompts from JSON config (same source the builder functions use).
_CAROUSEL_SYSTEM, _CAROUSEL_INSTRUCTION = get_process_prompts("linkedin-carousel")
_REGEN_SYSTEM, _REGEN_INSTRUCTION = get_process_prompts("linkedin-regeneration")


# ===========================================================================
# Generation system prompt
# ===========================================================================


class TestLinkedInCarouselSystemPrompt:
    """Verify the generation system prompt is the shared system prompt."""

    def test_is_shared_system_prompt(self):
        assert _CAROUSEL_SYSTEM == get_system_prompt()

    def test_is_string(self):
        assert isinstance(_CAROUSEL_SYSTEM, str)

    def test_not_empty(self):
        assert len(_CAROUSEL_SYSTEM) > 0

    def test_contains_data_integrity(self):
        assert "Data Integrity" in _CAROUSEL_SYSTEM

    def test_contains_output_integrity(self):
        assert "Output Integrity" in _CAROUSEL_SYSTEM


# ===========================================================================
# Generation user prompt
# ===========================================================================


class TestLinkedInCarouselUserPrompt:
    """Verify the generation user prompt template."""

    def test_contains_formatted_theme_placeholder(self):
        assert "{formatted_theme}" in _CAROUSEL_INSTRUCTION

    def test_contains_newsletter_content_placeholder(self):
        assert "{newsletter_content}" in _CAROUSEL_INSTRUCTION

    def test_contains_previous_output_placeholder(self):
        assert "{previous_output}" in _CAROUSEL_INSTRUCTION

    def test_contains_output_format(self):
        assert "OUTPUT FORMAT" in _CAROUSEL_INSTRUCTION

    def test_contains_version_labels(self):
        assert "*Version 1*" in _CAROUSEL_INSTRUCTION
        assert "*Version 2*" in _CAROUSEL_INSTRUCTION
        assert "*Version 3*" in _CAROUSEL_INSTRUCTION

    def test_contains_tldr_section(self):
        assert "TL;DR" in _CAROUSEL_INSTRUCTION

    def test_contains_slide_3_label(self):
        assert "Slide 3" in _CAROUSEL_INSTRUCTION


# ===========================================================================
# Regeneration system prompt
# ===========================================================================


class TestLinkedInRegenerationSystemPrompt:
    """Verify the regeneration system prompt is the shared system prompt."""

    def test_is_shared_system_prompt(self):
        assert _REGEN_SYSTEM == get_system_prompt()

    def test_is_string(self):
        assert isinstance(_REGEN_SYSTEM, str)

    def test_not_empty(self):
        assert len(_REGEN_SYSTEM) > 0

    def test_contains_data_integrity(self):
        assert "Data Integrity" in _REGEN_SYSTEM

    def test_contains_output_integrity(self):
        assert "Output Integrity" in _REGEN_SYSTEM


# ===========================================================================
# Regeneration user prompt
# ===========================================================================


class TestLinkedInRegenerationUserPrompt:
    """Verify the regeneration user prompt template."""

    def test_contains_previous_output_placeholder(self):
        assert "{previous_output}" in _REGEN_INSTRUCTION

    def test_contains_feedback_placeholder(self):
        assert "{feedback_text}" in _REGEN_INSTRUCTION

    def test_contains_formatted_theme_placeholder(self):
        assert "{formatted_theme}" in _REGEN_INSTRUCTION

    def test_contains_newsletter_content_placeholder(self):
        assert "{newsletter_content}" in _REGEN_INSTRUCTION

    def test_contains_output_format(self):
        assert "OUTPUT FORMAT" in _REGEN_INSTRUCTION

    def test_contains_primary_source_label(self):
        assert "PRIMARY SOURCE" in _REGEN_INSTRUCTION

    def test_contains_primary_authority_label(self):
        assert "PRIMARY AUTHORITY" in _REGEN_INSTRUCTION

    def test_contains_read_only_labels(self):
        assert "READ-ONLY" in _REGEN_INSTRUCTION


# ===========================================================================
# Builder functions
# ===========================================================================


class TestBuildLinkedInCarouselPrompt:
    """Verify the generation builder function."""

    def test_returns_tuple(self):
        result = build_linkedin_carousel_prompt("theme", "content")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_prompt_matches_json_config(self):
        sys_prompt, _ = build_linkedin_carousel_prompt("theme", "content")
        assert sys_prompt == _CAROUSEL_SYSTEM

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
        _, user_prompt = build_linkedin_carousel_prompt("theme", "content", "previous carousel")
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
        result = build_linkedin_regeneration_prompt("previous", "feedback", "theme", "content")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_prompt_matches_json_config(self):
        sys_prompt, _ = build_linkedin_regeneration_prompt(
            "previous", "feedback", "theme", "content"
        )
        assert sys_prompt == _REGEN_SYSTEM

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
        _, prompt_a = build_linkedin_regeneration_prompt("prev", "fix A", "theme", "content")
        _, prompt_b = build_linkedin_regeneration_prompt("prev", "fix B", "theme", "content")
        assert prompt_a != prompt_b
