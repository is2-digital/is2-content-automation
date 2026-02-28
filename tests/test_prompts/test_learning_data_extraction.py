"""Tests for ica.prompts.learning_data_extraction."""

from __future__ import annotations

from ica.llm_configs import get_process_prompts
from ica.prompts.learning_data_extraction import (
    build_learning_data_extraction_prompt,
)

# Load prompts from JSON config (same source the builder function uses).
_SYSTEM, _INSTRUCTION = get_process_prompts("learning-data-extraction")
_COMBINED = _SYSTEM + "\n" + _INSTRUCTION


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_FEEDBACK = "The summary was too long and lacked focus on business relevance."
SAMPLE_INPUT = "Article about AI agents in enterprise workflows..."
SAMPLE_OUTPUT = "AI agents are transforming enterprise workflows by automating complex tasks..."


# ---------------------------------------------------------------------------
# Prompt constant tests
# ---------------------------------------------------------------------------


class TestLearningDataExtractionPromptConstant:
    """Tests for the LEARNING_DATA_EXTRACTION_PROMPT constant."""

    def test_prompt_is_string(self) -> None:
        assert isinstance(_COMBINED, str)

    def test_prompt_is_not_empty(self) -> None:
        assert len(_COMBINED) > 0

    def test_contains_role_description(self) -> None:
        assert "AI assistant" in _COMBINED
        assert "user feedback" in _COMBINED
        assert "learning data" in _COMBINED

    def test_contains_three_inputs(self) -> None:
        assert "original *input text*" in _COMBINED
        assert "*model output*" in _COMBINED
        assert "*user's feedback*" in _COMBINED

    def test_contains_goal_steps(self) -> None:
        assert "clear, actionable insights" in _COMBINED
        assert "2-3 sentences max" in _COMBINED

    def test_contains_focus_areas(self) -> None:
        assert "tone" in _COMBINED
        assert "accuracy" in _COMBINED
        assert "length" in _COMBINED
        assert "structure" in _COMBINED

    def test_contains_unclear_feedback_handling(self) -> None:
        assert "unclear or generic" in _COMBINED
        assert "infer the likely intent" in _COMBINED

    def test_contains_feedback_placeholder(self) -> None:
        assert "{feedback}" in _INSTRUCTION

    def test_contains_input_placeholder(self) -> None:
        assert "{input_text}" in _INSTRUCTION

    def test_contains_output_placeholder(self) -> None:
        assert "{model_output}" in _INSTRUCTION

    def test_contains_expected_output_format(self) -> None:
        assert "learning_feedback" in _COMBINED
        assert "Future responses should" in _COMBINED

    def test_no_n8n_expression_syntax(self) -> None:
        assert "$json" not in _COMBINED
        assert "$(" not in _COMBINED


# ---------------------------------------------------------------------------
# build_learning_data_extraction_prompt() tests
# ---------------------------------------------------------------------------


class TestBuildLearningDataExtractionPrompt:
    """Tests for the build_learning_data_extraction_prompt() function."""

    def test_returns_tuple(self) -> None:
        result = build_learning_data_extraction_prompt(
            SAMPLE_FEEDBACK,
            SAMPLE_INPUT,
            SAMPLE_OUTPUT,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_strings(self) -> None:
        system, user = build_learning_data_extraction_prompt(
            SAMPLE_FEEDBACK,
            SAMPLE_INPUT,
            SAMPLE_OUTPUT,
        )
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_system_prompt_is_shared_system_prompt(self) -> None:
        system, _ = build_learning_data_extraction_prompt(
            SAMPLE_FEEDBACK,
            SAMPLE_INPUT,
            SAMPLE_OUTPUT,
        )
        assert "AI system" in system
        assert "IS2 Digital newsletter" in system

    def test_user_prompt_contains_feedback(self) -> None:
        _, user = build_learning_data_extraction_prompt(
            SAMPLE_FEEDBACK,
            SAMPLE_INPUT,
            SAMPLE_OUTPUT,
        )
        assert SAMPLE_FEEDBACK in user

    def test_user_prompt_contains_input(self) -> None:
        _, user = build_learning_data_extraction_prompt(
            SAMPLE_FEEDBACK,
            SAMPLE_INPUT,
            SAMPLE_OUTPUT,
        )
        assert SAMPLE_INPUT in user

    def test_user_prompt_contains_model_output(self) -> None:
        _, user = build_learning_data_extraction_prompt(
            SAMPLE_FEEDBACK,
            SAMPLE_INPUT,
            SAMPLE_OUTPUT,
        )
        assert SAMPLE_OUTPUT in user

    def test_all_placeholders_replaced(self) -> None:
        _, user = build_learning_data_extraction_prompt(
            SAMPLE_FEEDBACK,
            SAMPLE_INPUT,
            SAMPLE_OUTPUT,
        )
        assert "{feedback}" not in user
        assert "{input_text}" not in user
        assert "{model_output}" not in user

    def test_empty_feedback(self) -> None:
        _, user = build_learning_data_extraction_prompt("", SAMPLE_INPUT, SAMPLE_OUTPUT)
        assert "**User Feedback:**" in user
        assert SAMPLE_INPUT in user

    def test_empty_input(self) -> None:
        _, user = build_learning_data_extraction_prompt(SAMPLE_FEEDBACK, "", SAMPLE_OUTPUT)
        assert SAMPLE_FEEDBACK in user
        assert "**Input Provided:**" in user

    def test_empty_model_output(self) -> None:
        _, user = build_learning_data_extraction_prompt(SAMPLE_FEEDBACK, SAMPLE_INPUT, "")
        assert SAMPLE_FEEDBACK in user
        assert "**Model Output:**" in user

    def test_feedback_with_special_characters(self) -> None:
        feedback = "Use more {concrete} data and $specific numbers"
        _, user = build_learning_data_extraction_prompt(feedback, SAMPLE_INPUT, SAMPLE_OUTPUT)
        assert feedback in user

    def test_user_prompt_has_section_headers(self) -> None:
        _, user = build_learning_data_extraction_prompt(
            SAMPLE_FEEDBACK,
            SAMPLE_INPUT,
            SAMPLE_OUTPUT,
        )
        assert "### Feedback Data" in user
        assert "**User Feedback:**" in user
        assert "**Input Provided:**" in user
        assert "**Model Output:**" in user
        assert "### Expected Output" in user

    def test_user_prompt_has_json_example(self) -> None:
        _, user = build_learning_data_extraction_prompt(
            SAMPLE_FEEDBACK,
            SAMPLE_INPUT,
            SAMPLE_OUTPUT,
        )
        assert '"learning_feedback"' in user


# ---------------------------------------------------------------------------
# Cross-subworkflow consistency
# ---------------------------------------------------------------------------


class TestCrossSubworkflowConsistency:
    """The learning data prompt is shared across all subworkflows.

    These tests verify that the prompt structure matches the shared
    pattern used in summarization, markdown, and HTML subworkflows.
    """

    def test_prompt_mentions_json_output(self) -> None:
        assert "JSON format" in _COMBINED

    def test_prompt_has_concise_constraint(self) -> None:
        assert "2-3 sentences" in _COMBINED

    def test_prompt_focuses_on_improvement(self) -> None:
        assert "improved next time" in _COMBINED

    def test_generic_feedback_examples(self) -> None:
        assert '"good"' in _COMBINED
        assert '"bad"' in _COMBINED
