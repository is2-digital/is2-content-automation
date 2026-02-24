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
    """Verify the system prompt contains all required strategic sections."""

    def test_contains_role_preamble(self):
        assert "professional AI research editor" in _SYSTEM

    def test_contains_definitive_review_instruction(self):
        assert "definitive review" in _SYSTEM

    # --- Strategic Purpose ---

    def test_contains_strategic_purpose(self):
        assert "Strategic Purpose and Function" in _SYSTEM

    def test_contains_primary_function(self):
        assert "subscriber relationship messages" in _SYSTEM

    def test_contains_critical_distinction(self):
        assert "Critical Distinction from Newsletter Content" in _SYSTEM

    def test_contains_essential_rule(self):
        assert (
            "Email and newsletter introductions must serve distinct functions"
            in _SYSTEM
        )

    # --- Pre-Draft Analysis ---

    def test_contains_pre_draft_analysis(self):
        assert "Pre-Draft Analysis Process" in _SYSTEM

    def test_contains_content_relationship_assessment(self):
        assert "Content Relationship Assessment" in _SYSTEM

    def test_contains_narrative_thread_evaluation(self):
        assert "Narrative Thread Evaluation" in _SYSTEM

    def test_contains_redundancy_prevention(self):
        assert "Redundancy Prevention Check" in _SYSTEM

    # --- Structure Framework ---

    def test_contains_proven_structure_framework(self):
        assert "Proven Structure Framework" in _SYSTEM

    def test_contains_hi_friend_opening(self):
        assert '"Hi Friend,"' in _SYSTEM

    def test_contains_option_1_natural_narrative(self):
        assert "Natural Narrative Connection" in _SYSTEM

    def test_contains_option_2_responsive(self):
        assert "Responsive Approach" in _SYSTEM

    def test_contains_option_3_direct_subscriber(self):
        assert "Direct Subscriber Request" in _SYSTEM

    def test_contains_methodology_statement_variations(self):
        assert "Methodology Statement Variations" in _SYSTEM

    def test_contains_ps_element(self):
        assert "P.S. Element" in _SYSTEM

    # --- Voice and Tone ---

    def test_contains_voice_and_tone_guidelines(self):
        assert "Voice and Tone Guidelines" in _SYSTEM

    def test_contains_reader_as_hero(self):
        assert "Reader-as-Hero Positioning" in _SYSTEM

    def test_contains_conversational_warmth(self):
        assert "Conversational Warmth with Professional Authority" in _SYSTEM

    def test_contains_authentic_responsiveness(self):
        assert "Authentic Responsiveness" in _SYSTEM

    def test_contains_never_fabricate(self):
        assert "Never fabricate subscriber quotes" in _SYSTEM

    # --- Content Adaptation ---

    def test_contains_length_standard(self):
        assert "100-120 words maximum" in _SYSTEM

    def test_contains_technical_strategic_content(self):
        assert "Technical/Strategic Content" in _SYSTEM

    def test_contains_practical_implementation_content(self):
        assert "Practical/Implementation Content" in _SYSTEM

    # --- Quality Control ---

    def test_contains_quality_control_framework(self):
        assert "Quality Control Framework" in _SYSTEM

    def test_contains_unique_value_question(self):
        assert "Unique Value" in _SYSTEM

    def test_contains_redundancy_check_question(self):
        assert "Redundancy Check" in _SYSTEM

    def test_contains_authentic_connection_question(self):
        assert "Authentic Connection" in _SYSTEM

    def test_contains_fresh_positioning_question(self):
        assert "Fresh Positioning" in _SYSTEM

    def test_contains_avoid_em_dashes(self):
        assert "Avoids em-dashes" in _SYSTEM

    # --- Success Indicators ---

    def test_contains_success_indicators(self):
        assert "Success Indicators" in _SYSTEM

    def test_contains_common_issues_to_avoid(self):
        assert "Common Issues to Avoid" in _SYSTEM

    # --- Continuous Improvement ---

    def test_contains_continuous_improvement(self):
        assert "Continuous Improvement" in _SYSTEM

    def test_contains_voice_evolution(self):
        assert "Voice Evolution" in _SYSTEM

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
        _, user = build_email_review_prompt(
            self.SAMPLE_NEWSLETTER, "Some feedback"
        )
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
