"""Tests for the summarization regeneration prompt in ica.prompts.summarization."""

from __future__ import annotations

from ica.llm_configs import get_process_prompts
from ica.prompts.summarization import build_summarization_regeneration_prompt

# Load prompts from JSON config (same source the builder function uses).
_SYSTEM_PROMPT, _INSTRUCTION = get_process_prompts("summarization-regeneration")


# ---------------------------------------------------------------------------
# Constant sanity checks
# ---------------------------------------------------------------------------


class TestRegenerationSystemPrompt:
    """Verify the system prompt is the shared system prompt."""

    def test_is_shared_system_prompt(self):
        from ica.llm_configs.loader import get_system_prompt

        assert get_system_prompt() == _SYSTEM_PROMPT

    def test_contains_headless_api_mode(self):
        assert "HEADLESS API" in _SYSTEM_PROMPT

    def test_contains_zero_hallucination(self):
        assert "ZERO HALLUCINATION" in _SYSTEM_PROMPT

    def test_contains_voice_guardrails(self):
        assert "VOICE & FORMATTING GUARDRAILS" in _SYSTEM_PROMPT

    def test_no_original_content_placeholder(self):
        """Original content belongs in the user prompt, not the system prompt."""
        assert "{original_content}" not in _SYSTEM_PROMPT

    def test_no_user_feedback_placeholder(self):
        """User feedback belongs in the user prompt, not the system prompt."""
        assert "{user_feedback}" not in _SYSTEM_PROMPT


class TestRegenerationInstructionTemplate:
    """Verify the instruction template from JSON has required placeholders."""

    def test_has_original_content_placeholder(self):
        assert "{original_content}" in _INSTRUCTION

    def test_has_user_feedback_placeholder(self):
        assert "{user_feedback}" in _INSTRUCTION

    def test_contains_revision_task(self):
        assert "Revision_Task" in _INSTRUCTION

    def test_contains_rules(self):
        assert "Rules" in _INSTRUCTION

    def test_contains_preserve_structure(self):
        assert "Preserve the existing structure" in _INSTRUCTION

    def test_contains_do_not_expand(self):
        assert "Do NOT expand or rewrite sections" in _INSTRUCTION


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
        result = build_summarization_regeneration_prompt(self.SAMPLE_CONTENT, self.SAMPLE_FEEDBACK)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_prompt_matches_json_config(self):
        system, _ = build_summarization_regeneration_prompt(
            self.SAMPLE_CONTENT, self.SAMPLE_FEEDBACK
        )
        assert system == _SYSTEM_PROMPT

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
        _, user = build_summarization_regeneration_prompt(self.SAMPLE_CONTENT, feedback)
        assert feedback in user

    def test_empty_feedback(self):
        """Even empty feedback should produce a valid prompt."""
        system, user = build_summarization_regeneration_prompt(self.SAMPLE_CONTENT, "")
        assert system == _SYSTEM_PROMPT
        assert self.SAMPLE_CONTENT in user

    def test_feedback_with_special_characters(self):
        feedback = 'Use "quoted" text and include {braces} & <angles>'
        _, user = build_summarization_regeneration_prompt(self.SAMPLE_CONTENT, feedback)
        assert feedback in user

    # -- Various content inputs --------------------------------------------

    def test_empty_content(self):
        """Empty original content should still produce valid prompts."""
        system, user = build_summarization_regeneration_prompt("", "Fix it")
        assert system == _SYSTEM_PROMPT
        assert "Fix it" in user

    def test_content_with_curly_braces(self):
        content = 'function() { return {"key": "value"}; }'
        _, user = build_summarization_regeneration_prompt(content, "Looks good")
        assert content in user

    def test_multiline_content(self):
        content = (
            "URL: https://example.com\nTitle: Test\nSummary: Line 1.\nBusiness Relevance: Line 2."
        )
        _, user = build_summarization_regeneration_prompt(content, "Add more detail")
        assert content in user
