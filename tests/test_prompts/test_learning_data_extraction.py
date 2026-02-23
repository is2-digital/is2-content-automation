"""Tests for ica.prompts.learning_data_extraction."""

from __future__ import annotations

import pytest

from ica.prompts.learning_data_extraction import (
    LEARNING_DATA_EXTRACTION_PROMPT,
    build_learning_data_extraction_prompt,
)


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
        assert isinstance(LEARNING_DATA_EXTRACTION_PROMPT, str)

    def test_prompt_is_not_empty(self) -> None:
        assert len(LEARNING_DATA_EXTRACTION_PROMPT) > 0

    def test_contains_role_description(self) -> None:
        assert "AI assistant" in LEARNING_DATA_EXTRACTION_PROMPT
        assert "user feedback" in LEARNING_DATA_EXTRACTION_PROMPT
        assert "learning data" in LEARNING_DATA_EXTRACTION_PROMPT

    def test_contains_three_inputs(self) -> None:
        assert "original *input text*" in LEARNING_DATA_EXTRACTION_PROMPT
        assert "*model output*" in LEARNING_DATA_EXTRACTION_PROMPT
        assert "*user's feedback*" in LEARNING_DATA_EXTRACTION_PROMPT

    def test_contains_goal_steps(self) -> None:
        assert "clear, actionable insights" in LEARNING_DATA_EXTRACTION_PROMPT
        assert "2-3 sentences max" in LEARNING_DATA_EXTRACTION_PROMPT

    def test_contains_focus_areas(self) -> None:
        assert "tone" in LEARNING_DATA_EXTRACTION_PROMPT
        assert "accuracy" in LEARNING_DATA_EXTRACTION_PROMPT
        assert "length" in LEARNING_DATA_EXTRACTION_PROMPT
        assert "structure" in LEARNING_DATA_EXTRACTION_PROMPT

    def test_contains_unclear_feedback_handling(self) -> None:
        assert "unclear or generic" in LEARNING_DATA_EXTRACTION_PROMPT
        assert "infer the likely intent" in LEARNING_DATA_EXTRACTION_PROMPT

    def test_contains_feedback_placeholder(self) -> None:
        assert "{feedback}" in LEARNING_DATA_EXTRACTION_PROMPT

    def test_contains_input_placeholder(self) -> None:
        assert "{input_text}" in LEARNING_DATA_EXTRACTION_PROMPT

    def test_contains_output_placeholder(self) -> None:
        assert "{model_output}" in LEARNING_DATA_EXTRACTION_PROMPT

    def test_contains_expected_output_format(self) -> None:
        assert "learning_feedback" in LEARNING_DATA_EXTRACTION_PROMPT
        assert "Future responses should" in LEARNING_DATA_EXTRACTION_PROMPT

    def test_no_n8n_expression_syntax(self) -> None:
        assert "$json" not in LEARNING_DATA_EXTRACTION_PROMPT
        assert "$(" not in LEARNING_DATA_EXTRACTION_PROMPT


# ---------------------------------------------------------------------------
# build_learning_data_extraction_prompt() tests
# ---------------------------------------------------------------------------


class TestBuildLearningDataExtractionPrompt:
    """Tests for the build_learning_data_extraction_prompt() function."""

    def test_returns_tuple(self) -> None:
        result = build_learning_data_extraction_prompt(
            SAMPLE_FEEDBACK, SAMPLE_INPUT, SAMPLE_OUTPUT,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_strings(self) -> None:
        system, user = build_learning_data_extraction_prompt(
            SAMPLE_FEEDBACK, SAMPLE_INPUT, SAMPLE_OUTPUT,
        )
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_system_prompt_contains_role(self) -> None:
        system, _ = build_learning_data_extraction_prompt(
            SAMPLE_FEEDBACK, SAMPLE_INPUT, SAMPLE_OUTPUT,
        )
        assert "AI assistant" in system
        assert "learning data" in system

    def test_user_prompt_contains_feedback(self) -> None:
        _, user = build_learning_data_extraction_prompt(
            SAMPLE_FEEDBACK, SAMPLE_INPUT, SAMPLE_OUTPUT,
        )
        assert SAMPLE_FEEDBACK in user

    def test_user_prompt_contains_input(self) -> None:
        _, user = build_learning_data_extraction_prompt(
            SAMPLE_FEEDBACK, SAMPLE_INPUT, SAMPLE_OUTPUT,
        )
        assert SAMPLE_INPUT in user

    def test_user_prompt_contains_model_output(self) -> None:
        _, user = build_learning_data_extraction_prompt(
            SAMPLE_FEEDBACK, SAMPLE_INPUT, SAMPLE_OUTPUT,
        )
        assert SAMPLE_OUTPUT in user

    def test_all_placeholders_replaced(self) -> None:
        _, user = build_learning_data_extraction_prompt(
            SAMPLE_FEEDBACK, SAMPLE_INPUT, SAMPLE_OUTPUT,
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
            SAMPLE_FEEDBACK, SAMPLE_INPUT, SAMPLE_OUTPUT,
        )
        assert "### Feedback Data" in user
        assert "**User Feedback:**" in user
        assert "**Input Provided:**" in user
        assert "**Model Output:**" in user
        assert "### Expected Output" in user

    def test_user_prompt_has_json_example(self) -> None:
        _, user = build_learning_data_extraction_prompt(
            SAMPLE_FEEDBACK, SAMPLE_INPUT, SAMPLE_OUTPUT,
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
        assert "JSON format" in LEARNING_DATA_EXTRACTION_PROMPT

    def test_prompt_has_concise_constraint(self) -> None:
        assert "2-3 sentences" in LEARNING_DATA_EXTRACTION_PROMPT

    def test_prompt_focuses_on_improvement(self) -> None:
        assert "improved next time" in LEARNING_DATA_EXTRACTION_PROMPT

    def test_generic_feedback_examples(self) -> None:
        assert '"good"' in LEARNING_DATA_EXTRACTION_PROMPT
        assert '"bad"' in LEARNING_DATA_EXTRACTION_PROMPT
