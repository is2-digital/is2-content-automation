"""Tests for the summarization regeneration prompt in ica.prompts.summarization."""

from __future__ import annotations

import pytest

from ica.prompts.summarization import (
    REGENERATION_SYSTEM_PROMPT,
    REGENERATION_USER_PROMPT,
    build_summarization_regeneration_prompt,
)


# ---------------------------------------------------------------------------
# Regeneration system prompt — constant sanity checks
# ---------------------------------------------------------------------------


class TestRegenerationSystemPrompt:
    """Verify the regeneration system prompt contains all required sections."""

    def test_contains_editor_role(self):
        assert "professional content editor AI" in REGENERATION_SYSTEM_PROMPT

    def test_contains_revise_instruction(self):
        assert "revise the content to incorporate the feedback" in REGENERATION_SYSTEM_PROMPT

    def test_contains_maintain_formatting(self):
        assert "Maintain the formatting of the original content" in REGENERATION_SYSTEM_PROMPT

    # -- Accuracy Control Protocol -----------------------------------------

    def test_contains_accuracy_control_protocol(self):
        assert "Accuracy Control Protocol (MANDATORY)" in REGENERATION_SYSTEM_PROMPT

    def test_contains_do_not_search(self):
        assert "Do NOT search for alternative sources" in REGENERATION_SYSTEM_PROMPT

    def test_contains_do_not_summarize_partial(self):
        assert "Do NOT summarize partial or unavailable content" in REGENERATION_SYSTEM_PROMPT

    def test_contains_do_not_infer(self):
        assert "Do NOT generate or infer missing details" in REGENERATION_SYSTEM_PROMPT

    def test_contains_feedback_only_rule(self):
        assert (
            "Incorporate ONLY the requested feedback"
            in REGENERATION_SYSTEM_PROMPT
        )

    def test_contains_do_not_rewrite(self):
        assert (
            "Do NOT rewrite, expand, or regenerate other sections"
            in REGENERATION_SYSTEM_PROMPT
        )

    # -- Article Summary Standards -----------------------------------------

    def test_contains_article_summary_standards(self):
        assert "Article Summary Standards" in REGENERATION_SYSTEM_PROMPT

    def test_contains_summary_specifications(self):
        assert "3-4 sentences per article" in REGENERATION_SYSTEM_PROMPT

    def test_contains_business_relevance_specs(self):
        assert "Business Relevance Specifications" in REGENERATION_SYSTEM_PROMPT

    def test_contains_solopreneur_audience(self):
        assert "solopreneurs and SMB professionals" in REGENERATION_SYSTEM_PROMPT

    # -- Data Integrity Standards ------------------------------------------

    def test_contains_data_integrity_standards(self):
        assert "Data Integrity Standards" in REGENERATION_SYSTEM_PROMPT

    def test_contains_do_not_fabricate(self):
        assert "Do NOT fabricate, infer, or supplement" in REGENERATION_SYSTEM_PROMPT

    def test_contains_flag_unverifiable(self):
        assert "Statistic requires verification" in REGENERATION_SYSTEM_PROMPT

    # -- Negative checks ---------------------------------------------------

    def test_no_original_content_placeholder(self):
        """Original content belongs in the user prompt, not the system prompt."""
        assert "{original_content}" not in REGENERATION_SYSTEM_PROMPT

    def test_no_user_feedback_placeholder(self):
        """User feedback belongs in the user prompt, not the system prompt."""
        assert "{user_feedback}" not in REGENERATION_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Regeneration user prompt template
# ---------------------------------------------------------------------------


class TestRegenerationUserPromptTemplate:
    """Verify the user prompt template has required placeholders."""

    def test_has_original_content_placeholder(self):
        assert "{original_content}" in REGENERATION_USER_PROMPT

    def test_has_user_feedback_placeholder(self):
        assert "{user_feedback}" in REGENERATION_USER_PROMPT

    def test_contains_original_content_label(self):
        assert "The original content is below:" in REGENERATION_USER_PROMPT

    def test_contains_feedback_label(self):
        assert "The user has provided feedback as follows:" in REGENERATION_USER_PROMPT


# ---------------------------------------------------------------------------
# build_summarization_regeneration_prompt
# ---------------------------------------------------------------------------


class TestBuildSummarizationRegenerationPrompt:
    """Test the builder function for regeneration prompts."""

    SAMPLE_CONTENT = (
        "URL: https://example.com/article\n"
        "Title: AI Revolution in SMB\n"
        "Summary: AI is transforming small businesses. "
        "New tools enable automation of routine tasks. "
        "Recent studies show 40% productivity gains.\n"
        "Business Relevance: Small businesses can leverage AI tools "
        "to compete with larger enterprises."
    )
    SAMPLE_FEEDBACK = "Make the summary more concise and add the specific study name."

    def test_returns_tuple(self):
        result = build_summarization_regeneration_prompt(
            self.SAMPLE_CONTENT, self.SAMPLE_FEEDBACK
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_prompt_is_constant(self):
        system, _ = build_summarization_regeneration_prompt(
            self.SAMPLE_CONTENT, self.SAMPLE_FEEDBACK
        )
        assert system is REGENERATION_SYSTEM_PROMPT

    def test_original_content_in_user_prompt(self):
        _, user = build_summarization_regeneration_prompt(
            self.SAMPLE_CONTENT, self.SAMPLE_FEEDBACK
        )
        assert self.SAMPLE_CONTENT in user

    def test_user_feedback_in_user_prompt(self):
        _, user = build_summarization_regeneration_prompt(
            self.SAMPLE_CONTENT, self.SAMPLE_FEEDBACK
        )
        assert self.SAMPLE_FEEDBACK in user

    def test_original_content_appears_before_feedback(self):
        _, user = build_summarization_regeneration_prompt(
            self.SAMPLE_CONTENT, self.SAMPLE_FEEDBACK
        )
        content_pos = user.index(self.SAMPLE_CONTENT)
        feedback_pos = user.index(self.SAMPLE_FEEDBACK)
        assert content_pos < feedback_pos

    def test_no_unresolved_placeholders(self):
        _, user = build_summarization_regeneration_prompt(
            self.SAMPLE_CONTENT, self.SAMPLE_FEEDBACK
        )
        assert "{original_content}" not in user
        assert "{user_feedback}" not in user

    # -- Various feedback inputs -------------------------------------------

    def test_multiline_feedback(self):
        feedback = "1. Be more concise\n2. Add statistics\n3. Fix the title"
        _, user = build_summarization_regeneration_prompt(
            self.SAMPLE_CONTENT, feedback
        )
        assert feedback in user

    def test_empty_feedback(self):
        """Even empty feedback should produce a valid prompt."""
        system, user = build_summarization_regeneration_prompt(
            self.SAMPLE_CONTENT, ""
        )
        assert system is REGENERATION_SYSTEM_PROMPT
        assert self.SAMPLE_CONTENT in user

    def test_feedback_with_special_characters(self):
        feedback = 'Use "quoted" text and include {braces} & <angles>'
        _, user = build_summarization_regeneration_prompt(
            self.SAMPLE_CONTENT, feedback
        )
        assert feedback in user

    # -- Various content inputs --------------------------------------------

    def test_empty_content(self):
        """Empty original content should still produce valid prompts."""
        system, user = build_summarization_regeneration_prompt("", "Fix it")
        assert system is REGENERATION_SYSTEM_PROMPT
        assert "Fix it" in user

    def test_content_with_curly_braces(self):
        content = 'function() { return {"key": "value"}; }'
        _, user = build_summarization_regeneration_prompt(content, "Looks good")
        assert content in user

    def test_multiline_content(self):
        content = "URL: https://example.com\nTitle: Test\nSummary: Line 1.\nBusiness Relevance: Line 2."
        _, user = build_summarization_regeneration_prompt(
            content, "Add more detail"
        )
        assert content in user
