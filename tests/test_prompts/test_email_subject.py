"""Tests for ica.prompts.email_subject."""

from __future__ import annotations

from ica.prompts.email_subject import (
    EMAIL_SUBJECT_SYSTEM_PROMPT,
    EMAIL_SUBJECT_USER_PROMPT,
    _FEEDBACK_SECTION_TEMPLATE,
    build_email_subject_prompt,
)


# ---------------------------------------------------------------------------
# System prompt — verify key instructions are present
# ---------------------------------------------------------------------------


class TestEmailSubjectSystemPrompt:
    """Verify the system prompt contains all required sections."""

    def test_contains_role_preamble(self):
        assert "professional AI research editor" in EMAIL_SUBJECT_SYSTEM_PROMPT

    def test_contains_content_analyst(self):
        assert "content analyst" in EMAIL_SUBJECT_SYSTEM_PROMPT

    def test_contains_10_subjects_instruction(self):
        assert "up to 10" in EMAIL_SUBJECT_SYSTEM_PROMPT

    def test_contains_definitive(self):
        assert "definitive email subjects" in EMAIL_SUBJECT_SYSTEM_PROMPT

    # --- Accuracy Control Protocol ---

    def test_contains_accuracy_control(self):
        assert "Accuracy Control Protocol" in EMAIL_SUBJECT_SYSTEM_PROMPT

    def test_contains_mandatory_label(self):
        assert "MANDATORY" in EMAIL_SUBJECT_SYSTEM_PROMPT

    def test_contains_no_alternative_sources(self):
        assert "Do NOT search for alternative sources" in EMAIL_SUBJECT_SYSTEM_PROMPT

    def test_contains_trending_instruction(self):
        assert "trending" in EMAIL_SUBJECT_SYSTEM_PROMPT

    def test_contains_7_word_max(self):
        assert "maximum is 7 words" in EMAIL_SUBJECT_SYSTEM_PROMPT

    def test_contains_be_creative(self):
        assert "Be creative" in EMAIL_SUBJECT_SYSTEM_PROMPT

    def test_is_string(self):
        assert isinstance(EMAIL_SUBJECT_SYSTEM_PROMPT, str)

    def test_not_empty(self):
        assert len(EMAIL_SUBJECT_SYSTEM_PROMPT) > 100


# ---------------------------------------------------------------------------
# User prompt template — verify placeholders and output format
# ---------------------------------------------------------------------------


class TestEmailSubjectUserPrompt:
    """Verify the user prompt template structure."""

    def test_contains_feedback_placeholder(self):
        assert "{feedback_section}" in EMAIL_SUBJECT_USER_PROMPT

    def test_contains_newsletter_placeholder(self):
        assert "{newsletter_text}" in EMAIL_SUBJECT_USER_PROMPT

    def test_contains_output_format(self):
        assert "Output Format" in EMAIL_SUBJECT_USER_PROMPT

    def test_contains_mandatory_label(self):
        assert "MANDATORY" in EMAIL_SUBJECT_USER_PROMPT

    def test_contains_subject_number_format(self):
        assert "Subject_[number]" in EMAIL_SUBJECT_USER_PROMPT

    def test_contains_separator_instruction(self):
        assert '"-----"' in EMAIL_SUBJECT_USER_PROMPT

    def test_contains_recommendation_format(self):
        assert "RECOMMENDATION:" in EMAIL_SUBJECT_USER_PROMPT

    def test_contains_no_markdown_instruction(self):
        assert "no markdown" in EMAIL_SUBJECT_USER_PROMPT

    def test_contains_no_duplicate_instruction(self):
        assert "do not duplicate" in EMAIL_SUBJECT_USER_PROMPT

    def test_contains_input_label(self):
        assert "Input:" in EMAIL_SUBJECT_USER_PROMPT


# ---------------------------------------------------------------------------
# Feedback section template
# ---------------------------------------------------------------------------


class TestFeedbackSectionTemplate:
    """Verify the feedback section template."""

    def test_contains_editorial_improvement_header(self):
        assert "Editorial Improvement Context" in _FEEDBACK_SECTION_TEMPLATE

    def test_contains_feedback_placeholder(self):
        assert "{aggregated_feedback}" in _FEEDBACK_SECTION_TEMPLATE

    def test_contains_tone_instruction(self):
        assert "tone, structure, and theme style" in _FEEDBACK_SECTION_TEMPLATE

    def test_contains_accuracy_guard(self):
        assert "without altering factual accuracy" in _FEEDBACK_SECTION_TEMPLATE

    def test_interpolation_works(self):
        result = _FEEDBACK_SECTION_TEMPLATE.format(
            aggregated_feedback="Use shorter subjects"
        )
        assert "Use shorter subjects" in result


# ---------------------------------------------------------------------------
# build_email_subject_prompt — builder function
# ---------------------------------------------------------------------------


class TestBuildEmailSubjectPrompt:
    """Verify the builder function returns correct prompt tuples."""

    def test_returns_tuple(self):
        result = build_email_subject_prompt("some newsletter text")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_prompt_is_constant(self):
        sys_prompt, _ = build_email_subject_prompt("text")
        assert sys_prompt is EMAIL_SUBJECT_SYSTEM_PROMPT

    def test_user_prompt_contains_newsletter_text(self):
        _, user_prompt = build_email_subject_prompt("My newsletter content here")
        assert "My newsletter content here" in user_prompt

    def test_no_feedback_omits_section(self):
        _, user_prompt = build_email_subject_prompt("text", aggregated_feedback=None)
        assert "Editorial Improvement Context" not in user_prompt

    def test_empty_feedback_omits_section(self):
        _, user_prompt = build_email_subject_prompt("text", aggregated_feedback="")
        assert "Editorial Improvement Context" not in user_prompt

    def test_whitespace_only_feedback_omits_section(self):
        _, user_prompt = build_email_subject_prompt("text", aggregated_feedback="   ")
        assert "Editorial Improvement Context" not in user_prompt

    def test_feedback_injects_section(self):
        _, user_prompt = build_email_subject_prompt(
            "text", aggregated_feedback="Use punchier subjects"
        )
        assert "Editorial Improvement Context" in user_prompt
        assert "Use punchier subjects" in user_prompt

    def test_feedback_strips_whitespace(self):
        _, user_prompt = build_email_subject_prompt(
            "text", aggregated_feedback="  trimmed  "
        )
        assert "trimmed" in user_prompt
        # Leading/trailing spaces should be stripped
        assert "  trimmed  " not in user_prompt

    def test_output_format_present_in_user_prompt(self):
        _, user_prompt = build_email_subject_prompt("newsletter")
        assert "Subject_[number]" in user_prompt
        assert "RECOMMENDATION:" in user_prompt

    def test_system_prompt_unchanged_with_feedback(self):
        sys_no_fb, _ = build_email_subject_prompt("text")
        sys_with_fb, _ = build_email_subject_prompt(
            "text", aggregated_feedback="feedback"
        )
        assert sys_no_fb == sys_with_fb

    def test_different_newsletter_text_produces_different_user_prompt(self):
        _, prompt_a = build_email_subject_prompt("Newsletter A")
        _, prompt_b = build_email_subject_prompt("Newsletter B")
        assert prompt_a != prompt_b
        assert "Newsletter A" in prompt_a
        assert "Newsletter B" in prompt_b
