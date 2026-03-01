"""Tests for ica.prompts.relevance_assessment.

Tests cover:
- Prompt constant content (loaded from JSON config)
- build_relevance_prompt(): return type, placeholder substitution, edge cases
"""

from __future__ import annotations

from ica.llm_configs import get_process_prompts
from ica.prompts.relevance_assessment import build_relevance_prompt

# Load prompts from JSON config (same source the builder function uses).
_SYSTEM, _INSTRUCTION = get_process_prompts("relevance-assessment")


# ===========================================================================
# Prompt constant tests
# ===========================================================================


class TestRelevanceAssessmentPromptConstant:
    """Tests for the relevance-assessment JSON config instruction prompt."""

    def test_instruction_is_string(self) -> None:
        assert isinstance(_INSTRUCTION, str)

    def test_instruction_is_not_empty(self) -> None:
        assert len(_INSTRUCTION) > 0

    def test_contains_title_placeholder(self) -> None:
        assert "{title}" in _INSTRUCTION

    def test_contains_excerpt_placeholder(self) -> None:
        assert "{excerpt}" in _INSTRUCTION

    def test_contains_json_output_format(self) -> None:
        assert "JSON" in _INSTRUCTION

    def test_contains_decision_field(self) -> None:
        assert "decision" in _INSTRUCTION

    def test_contains_reason_field(self) -> None:
        assert "reason" in _INSTRUCTION

    def test_contains_accept_option(self) -> None:
        assert "accept" in _INSTRUCTION

    def test_contains_reject_option(self) -> None:
        assert "reject" in _INSTRUCTION

    def test_contains_evaluation_criteria(self) -> None:
        assert "Evaluation_Criteria" in _INSTRUCTION or "criteria" in _INSTRUCTION.lower()

    def test_mentions_solopreneurs_or_smb(self) -> None:
        combined = _SYSTEM + "\n" + _INSTRUCTION
        assert "solopreneur" in combined.lower() or "smb" in combined.lower()

    def test_no_n8n_expression_syntax(self) -> None:
        combined = _SYSTEM + "\n" + _INSTRUCTION
        assert "$json" not in combined
        assert "$(" not in combined


# ===========================================================================
# build_relevance_prompt() tests
# ===========================================================================


class TestBuildRelevancePrompt:
    """Tests for the build_relevance_prompt() function."""

    def test_returns_tuple(self) -> None:
        result = build_relevance_prompt(title="Test", excerpt="Test excerpt")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_strings(self) -> None:
        system, user = build_relevance_prompt(title="Test", excerpt="Excerpt")
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_system_prompt_loaded_from_json(self) -> None:
        system, _ = build_relevance_prompt(title="Test", excerpt="Excerpt")
        json_system, _ = get_process_prompts("relevance-assessment")
        assert system == json_system

    def test_user_prompt_contains_title(self) -> None:
        _, user = build_relevance_prompt(title="AI Agents for Small Business", excerpt="...")
        assert "AI Agents for Small Business" in user

    def test_user_prompt_contains_excerpt(self) -> None:
        _, user = build_relevance_prompt(
            title="Title",
            excerpt="This article discusses how AI tools can help solopreneurs",
        )
        assert "This article discusses how AI tools can help solopreneurs" in user

    def test_placeholders_fully_replaced(self) -> None:
        _, user = build_relevance_prompt(title="Test", excerpt="Excerpt")
        assert "{title}" not in user
        assert "{excerpt}" not in user

    def test_empty_title(self) -> None:
        _, user = build_relevance_prompt(title="", excerpt="Excerpt")
        assert "Excerpt" in user

    def test_empty_excerpt(self) -> None:
        _, user = build_relevance_prompt(title="Title", excerpt="")
        assert "Title" in user

    def test_special_characters_in_title(self) -> None:
        title = 'Title with "quotes" & <brackets> and $dollar'
        _, user = build_relevance_prompt(title=title, excerpt="Excerpt")
        assert title in user

    def test_unicode_in_excerpt(self) -> None:
        excerpt = "AI trends \u2192 automation \u2014 key insights"
        _, user = build_relevance_prompt(title="Title", excerpt=excerpt)
        assert excerpt in user

    def test_very_long_excerpt(self) -> None:
        excerpt = "A" * 5000
        _, user = build_relevance_prompt(title="Title", excerpt=excerpt)
        assert excerpt in user

    def test_multiline_excerpt(self) -> None:
        excerpt = "Line 1\nLine 2\nLine 3"
        _, user = build_relevance_prompt(title="Title", excerpt=excerpt)
        assert excerpt in user
