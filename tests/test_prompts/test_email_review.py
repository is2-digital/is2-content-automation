"""Tests for ica.prompts.email_review."""

from __future__ import annotations

from ica.llm_configs import get_process_prompts
from ica.prompts.email_review import (
    _FEEDBACK_SECTION_TEMPLATE,
    build_email_review_prompt,
)

# Load prompts from JSON config (same source the builder function uses).
_SYSTEM, _INSTRUCTION = get_process_prompts("email-preview")


# ---------------------------------------------------------------------------
# System prompt — verify key strategic sections are present
# ---------------------------------------------------------------------------


class TestEmailReviewSystemPrompt:
    """Verify the system prompt is the shared system prompt."""

    def test_is_shared_system_prompt(self):
        from ica.llm_configs.loader import get_system_prompt

        assert _SYSTEM == get_system_prompt()

    def test_contains_data_integrity_section(self):
        assert "Data Integrity" in _SYSTEM

    def test_contains_output_integrity_section(self):
        assert "Output Integrity" in _SYSTEM

    def test_no_feedback_section_in_system_prompt(self):
        """Feedback is injected in the user prompt, not the system prompt."""
        assert "Editorial Improvement Context" not in _SYSTEM


# ---------------------------------------------------------------------------
# User prompt template
# ---------------------------------------------------------------------------


class TestEmailReviewUserPromptTemplate:
    """Verify the user prompt template has the right structure."""

    def test_has_feedback_section_placeholder(self):
        assert "{feedback_section}" in _INSTRUCTION

    def test_has_newsletter_text_placeholder(self):
        assert "{newsletter_text}" in _INSTRUCTION

    def test_contains_compose_instruction(self):
        assert "Compose a full review" in _INSTRUCTION

    def test_contains_plain_text_instruction(self):
        assert "no special characters or emojis" in _INSTRUCTION

    def test_contains_input_label(self):
        assert "Input text data as a source for the review" in _INSTRUCTION


# ---------------------------------------------------------------------------
# Feedback section template
# ---------------------------------------------------------------------------


class TestFeedbackSectionTemplate:
    """Verify the feedback section template."""

    def test_has_user_review_feedback_placeholder(self):
        assert "{user_review_feedback}" in _FEEDBACK_SECTION_TEMPLATE

    def test_contains_editorial_heading(self):
        assert "Editorial Improvement Context" in _FEEDBACK_SECTION_TEMPLATE

    def test_contains_guidance_text(self):
        assert "without altering factual accuracy" in _FEEDBACK_SECTION_TEMPLATE

    def test_contains_adjust_instruction(self):
        assert "adjust language, flow, and focus" in _FEEDBACK_SECTION_TEMPLATE


# ---------------------------------------------------------------------------
# build_email_review_prompt
# ---------------------------------------------------------------------------


class TestBuildEmailReviewPrompt:
    """Test the builder function that assembles system + user messages."""

    SAMPLE_NEWSLETTER = (
        "This week's AI Frontline explores three game-changing developments "
        "in artificial intelligence that are reshaping how small businesses "
        "approach customer engagement, data analysis, and content creation."
    )

    def test_returns_tuple(self):
        result = build_email_review_prompt(self.SAMPLE_NEWSLETTER)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_prompt_is_constant(self):
        system, _ = build_email_review_prompt(self.SAMPLE_NEWSLETTER)
        assert system == _SYSTEM

    def test_newsletter_text_in_user_prompt(self):
        _, user = build_email_review_prompt(self.SAMPLE_NEWSLETTER)
        assert self.SAMPLE_NEWSLETTER in user

    # -- Without feedback --------------------------------------------------

    def test_no_feedback_none(self):
        _, user = build_email_review_prompt(self.SAMPLE_NEWSLETTER, None)
        assert "Editorial Improvement Context" not in user

    def test_no_feedback_empty_string(self):
        _, user = build_email_review_prompt(self.SAMPLE_NEWSLETTER, "")
        assert "Editorial Improvement Context" not in user

    def test_no_feedback_whitespace_only(self):
        _, user = build_email_review_prompt(self.SAMPLE_NEWSLETTER, "   \n  ")
        assert "Editorial Improvement Context" not in user

    # -- With feedback -----------------------------------------------------

    def test_feedback_injected(self):
        feedback = "Make the tone more casual and friendly"
        _, user = build_email_review_prompt(self.SAMPLE_NEWSLETTER, feedback)
        assert "Editorial Improvement Context" in user
        assert "more casual and friendly" in user

    def test_feedback_preserves_multiline(self):
        feedback = "Point one\nPoint two\nPoint three"
        _, user = build_email_review_prompt(self.SAMPLE_NEWSLETTER, feedback)
        assert feedback in user

    def test_feedback_stripped(self):
        feedback = "  \nLeading whitespace feedback\n  "
        _, user = build_email_review_prompt(self.SAMPLE_NEWSLETTER, feedback)
        assert "Leading whitespace feedback" in user
        assert "  \nLeading" not in user

    def test_feedback_section_appears_before_newsletter_text(self):
        feedback = "Be more concise"
        _, user = build_email_review_prompt(self.SAMPLE_NEWSLETTER, feedback)
        feedback_pos = user.index("Editorial Improvement Context")
        content_pos = user.index(self.SAMPLE_NEWSLETTER)
        assert feedback_pos < content_pos

    # -- No leftover placeholders ------------------------------------------

    def test_no_unresolved_placeholders_without_feedback(self):
        _, user = build_email_review_prompt(self.SAMPLE_NEWSLETTER)
        assert "{feedback_section}" not in user
        assert "{newsletter_text}" not in user
        assert "{user_review_feedback}" not in user

    def test_no_unresolved_placeholders_with_feedback(self):
        _, user = build_email_review_prompt(self.SAMPLE_NEWSLETTER, "Some feedback")
        assert "{feedback_section}" not in user
        assert "{newsletter_text}" not in user
        assert "{user_review_feedback}" not in user

    # -- Edge cases --------------------------------------------------------

    def test_empty_newsletter_text(self):
        """An empty newsletter should still produce valid prompts."""
        system, user = build_email_review_prompt("")
        assert system == _SYSTEM
        assert "Compose a full review" in user

    def test_newsletter_with_curly_braces(self):
        """Newsletter content with curly braces should not break formatting."""
        content = 'function() { return {"key": "value"}; }'
        _, user = build_email_review_prompt(content)
        assert content in user

    def test_multiline_newsletter_text(self):
        content = "Paragraph 1\n\nParagraph 2\n\nParagraph 3"
        _, user = build_email_review_prompt(content)
        assert content in user

    def test_long_newsletter_text(self):
        """The prompt should handle large newsletter content without issue."""
        content = "A" * 50_000
        _, user = build_email_review_prompt(content)
        assert content in user

    def test_newsletter_with_html_entities(self):
        """Newsletter text may have residual HTML entities."""
        content = "AI &amp; ML are transforming &lt;small&gt; businesses"
        _, user = build_email_review_prompt(content)
        assert content in user
