"""Tests for ica.prompts.summarization."""

from __future__ import annotations

from ica.llm_configs import get_process_prompts
from ica.prompts.summarization import (
    _FEEDBACK_SECTION_TEMPLATE,
    build_summarization_prompt,
)

# Load prompts from JSON config (same source the builder function uses).
_SYSTEM_PROMPT, _INSTRUCTION = get_process_prompts("summarization")


# ---------------------------------------------------------------------------
# Constant sanity checks
# ---------------------------------------------------------------------------


class TestSystemPrompt:
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

    def test_no_feedback_section_in_system_prompt(self):
        """Feedback is injected in the user prompt, not the system prompt."""
        assert "Editorial Improvement Context" not in _SYSTEM_PROMPT


class TestUserPromptTemplate:
    """Verify the user prompt template contains required placeholders."""

    def test_has_feedback_section_placeholder(self):
        assert "{feedback_section}" in _INSTRUCTION

    def test_has_article_content_placeholder(self):
        assert "{article_content}" in _INSTRUCTION

    def test_contains_output_schema(self):
        assert "Output_Schema" in _INSTRUCTION

    def test_contains_url_field(self):
        assert "URL:" in _INSTRUCTION

    def test_contains_title_field(self):
        assert "Title:" in _INSTRUCTION

    def test_contains_summary_field(self):
        assert "Summary:" in _INSTRUCTION

    def test_contains_business_relevance_field(self):
        assert "Business Relevance:" in _INSTRUCTION

    def test_contains_constraint_rules(self):
        assert "Constraint_Rules" in _INSTRUCTION


class TestFeedbackSectionTemplate:
    """Verify the feedback section template."""

    def test_has_aggregated_feedback_placeholder(self):
        assert "{aggregated_feedback}" in _FEEDBACK_SECTION_TEMPLATE

    def test_contains_editorial_heading(self):
        assert "Editorial Improvement Context" in _FEEDBACK_SECTION_TEMPLATE

    def test_contains_guidance_text(self):
        assert "without altering factual accuracy" in _FEEDBACK_SECTION_TEMPLATE


# ---------------------------------------------------------------------------
# build_summarization_prompt
# ---------------------------------------------------------------------------


class TestBuildSummarizationPrompt:
    """Test the builder function that assembles system + user messages."""

    SAMPLE_CONTENT = (
        "https://example.com/article "
        "AI Revolution in SMB "
        "<p>Article body about AI in small business...</p>"
    )

    def test_returns_tuple(self):
        result = build_summarization_prompt(self.SAMPLE_CONTENT)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_prompt_matches_json_config(self):
        system, _ = build_summarization_prompt(self.SAMPLE_CONTENT)
        assert system == _SYSTEM_PROMPT

    def test_article_content_in_user_prompt(self):
        _, user = build_summarization_prompt(self.SAMPLE_CONTENT)
        assert self.SAMPLE_CONTENT in user

    # -- Without feedback --------------------------------------------------

    def test_no_feedback_none(self):
        _, user = build_summarization_prompt(self.SAMPLE_CONTENT, None)
        assert "Editorial Improvement Context" not in user

    def test_no_feedback_empty_string(self):
        _, user = build_summarization_prompt(self.SAMPLE_CONTENT, "")
        assert "Editorial Improvement Context" not in user

    def test_no_feedback_whitespace_only(self):
        _, user = build_summarization_prompt(self.SAMPLE_CONTENT, "   \n  ")
        assert "Editorial Improvement Context" not in user

    # -- With feedback -----------------------------------------------------

    def test_feedback_injected(self):
        feedback = "• Use shorter sentences\n• Avoid jargon"
        _, user = build_summarization_prompt(self.SAMPLE_CONTENT, feedback)
        assert "Editorial Improvement Context" in user
        assert "Use shorter sentences" in user
        assert "Avoid jargon" in user

    def test_feedback_preserves_bullet_list(self):
        feedback = "• Point one\n• Point two\n• Point three"
        _, user = build_summarization_prompt(self.SAMPLE_CONTENT, feedback)
        assert feedback in user

    def test_feedback_stripped(self):
        feedback = "  \n• Leading whitespace feedback\n  "
        _, user = build_summarization_prompt(self.SAMPLE_CONTENT, feedback)
        assert "Leading whitespace feedback" in user
        # Should not have leading/trailing whitespace around feedback
        assert "  \n•" not in user

    def test_feedback_section_present_in_user_prompt(self):
        feedback = "• Emphasize statistics"
        _, user = build_summarization_prompt(self.SAMPLE_CONTENT, feedback)
        assert "Editorial Improvement Context" in user
        assert "Emphasize statistics" in user

    # -- No leftover placeholders ------------------------------------------

    def test_no_unresolved_placeholders_without_feedback(self):
        _, user = build_summarization_prompt(self.SAMPLE_CONTENT)
        assert "{feedback_section}" not in user
        assert "{article_content}" not in user
        assert "{aggregated_feedback}" not in user

    def test_no_unresolved_placeholders_with_feedback(self):
        _, user = build_summarization_prompt(self.SAMPLE_CONTENT, "• Some feedback")
        assert "{feedback_section}" not in user
        assert "{article_content}" not in user
        assert "{aggregated_feedback}" not in user

    # -- Edge cases --------------------------------------------------------

    def test_empty_article_content(self):
        """An empty article should still produce valid prompts."""
        system, user = build_summarization_prompt("")
        assert system == _SYSTEM_PROMPT
        assert "Output_Schema" in user

    def test_article_with_curly_braces(self):
        """Article content with curly braces should not break formatting."""
        content = 'function() { return {"key": "value"}; }'
        _, user = build_summarization_prompt(content)
        assert content in user

    def test_multiline_article_content(self):
        content = "Line 1\nLine 2\nLine 3"
        _, user = build_summarization_prompt(content)
        assert content in user
