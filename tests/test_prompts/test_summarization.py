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
    """Verify the system prompt contains all required protocol sections."""

    def test_contains_accuracy_control_protocol(self):
        assert "Accuracy Control Protocol (MANDATORY)" in _SYSTEM_PROMPT

    def test_contains_do_not_search(self):
        assert "Do NOT search for alternative sources" in _SYSTEM_PROMPT

    def test_contains_do_not_summarize_partial(self):
        assert "Do NOT summarize partial or unavailable content" in _SYSTEM_PROMPT

    def test_contains_do_not_infer(self):
        assert "Do NOT generate or infer missing details" in _SYSTEM_PROMPT

    def test_contains_article_summary_standards(self):
        assert "Article Summary Standards" in _SYSTEM_PROMPT

    def test_contains_summary_specifications(self):
        assert "3-4 sentences per article" in _SYSTEM_PROMPT

    def test_contains_business_relevance_specs(self):
        assert "Business Relevance Specifications" in _SYSTEM_PROMPT

    def test_contains_solopreneur_audience(self):
        assert "solopreneurs and SMB professionals" in _SYSTEM_PROMPT

    def test_contains_data_integrity_standards(self):
        assert "Data Integrity Standards" in _SYSTEM_PROMPT

    def test_contains_do_not_fabricate(self):
        assert "Do NOT fabricate, infer, or supplement" in _SYSTEM_PROMPT

    def test_contains_flag_unverifiable(self):
        assert "Statistic requires verification" in _SYSTEM_PROMPT

    def test_no_feedback_section_in_system_prompt(self):
        """Feedback is injected in the user prompt, not the system prompt."""
        assert "Editorial Improvement Context" not in _SYSTEM_PROMPT


class TestUserPromptTemplate:
    """Verify the user prompt template contains required placeholders."""

    def test_has_feedback_section_placeholder(self):
        assert "{feedback_section}" in _INSTRUCTION

    def test_has_article_content_placeholder(self):
        assert "{article_content}" in _INSTRUCTION

    def test_contains_output_format(self):
        assert "Output Format (MANDATORY)" in _INSTRUCTION

    def test_contains_url_field(self):
        assert "URL: [article URL]" in _INSTRUCTION

    def test_contains_title_field(self):
        assert "Title: [article title]" in _INSTRUCTION

    def test_contains_summary_field(self):
        assert "Summary:" in _INSTRUCTION

    def test_contains_business_relevance_field(self):
        assert "Business Relevance:" in _INSTRUCTION

    def test_contains_plain_text_instruction(self):
        assert "plain text and not JSON object" in _INSTRUCTION


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

    def test_feedback_section_appears_before_output_format(self):
        feedback = "• Be more concise"
        _, user = build_summarization_prompt(self.SAMPLE_CONTENT, feedback)
        feedback_pos = user.index("Editorial Improvement Context")
        output_pos = user.index("Output Format (MANDATORY)")
        assert feedback_pos < output_pos

    def test_feedback_section_appears_before_article_content(self):
        feedback = "• Emphasize statistics"
        _, user = build_summarization_prompt(self.SAMPLE_CONTENT, feedback)
        feedback_pos = user.index("Editorial Improvement Context")
        content_pos = user.index(self.SAMPLE_CONTENT)
        assert feedback_pos < content_pos

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
        assert "Output Format (MANDATORY)" in user

    def test_article_with_curly_braces(self):
        """Article content with curly braces should not break formatting."""
        content = 'function() { return {"key": "value"}; }'
        _, user = build_summarization_prompt(content)
        assert content in user

    def test_multiline_article_content(self):
        content = "Line 1\nLine 2\nLine 3"
        _, user = build_summarization_prompt(content)
        assert content in user
