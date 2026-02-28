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
        assert "iS2 Editorial Engine" in _COMBINED
        assert "Kevin" in _COMBINED
        assert "Head Operations Analyst" in _COMBINED

    def test_contains_data_source_sections(self) -> None:
        assert "Full Validation Log" in _COMBINED
        assert "Final Approved Content" in _COMBINED
        assert "Manual User Overrides" in _COMBINED

    def test_contains_analysis_protocol(self) -> None:
        assert "LOOP EFFICIENCY" in _COMBINED
        assert "VOICE DRIFT" in _COMBINED
        assert "MANUAL OVERRIDES" in _COMBINED
        assert "LINK/HTML INTEGRITY" in _COMBINED

    def test_contains_xml_structure_tags(self) -> None:
        assert "<Task_Context>" in _COMBINED
        assert "<Data_Sources>" in _COMBINED
        assert "<Analysis_Protocol>" in _COMBINED
        assert "<Output_Format>" in _COMBINED

    def test_contains_output_format_categories(self) -> None:
        assert "[RECURRING TECHNICAL FAIL]" in _COMBINED
        assert "[VOICE CALIBRATION]" in _COMBINED
        assert "[PROMPT OPTIMIZATION]" in _COMBINED

    def test_contains_feedback_placeholder(self) -> None:
        assert "{feedback_section}" in _INSTRUCTION

    def test_contains_input_placeholder(self) -> None:
        assert "{markdown_content}" in _INSTRUCTION

    def test_contains_output_placeholder(self) -> None:
        assert "{validator_errors_section}" in _INSTRUCTION

    def test_contains_expected_output_format(self) -> None:
        assert "3-point summary" in _COMBINED
        assert "for the next run" in _COMBINED

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
        assert "iS2 Editorial Engine" in system
        assert "Kevin" in system
        assert "HEADLESS API" in system

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
        assert "{feedback_section}" not in user
        assert "{markdown_content}" not in user
        assert "{validator_errors_section}" not in user

    def test_empty_feedback(self) -> None:
        _, user = build_learning_data_extraction_prompt("", SAMPLE_INPUT, SAMPLE_OUTPUT)
        assert "Manual User Overrides:" in user
        assert SAMPLE_INPUT in user

    def test_empty_input(self) -> None:
        _, user = build_learning_data_extraction_prompt(SAMPLE_FEEDBACK, "", SAMPLE_OUTPUT)
        assert SAMPLE_FEEDBACK in user
        assert "Final Approved Content:" in user

    def test_empty_model_output(self) -> None:
        _, user = build_learning_data_extraction_prompt(SAMPLE_FEEDBACK, SAMPLE_INPUT, "")
        assert SAMPLE_FEEDBACK in user
        assert "Full Validation Log:" in user

    def test_feedback_with_special_characters(self) -> None:
        feedback = "Use more {concrete} data and $specific numbers"
        _, user = build_learning_data_extraction_prompt(feedback, SAMPLE_INPUT, SAMPLE_OUTPUT)
        assert feedback in user

    def test_user_prompt_has_xml_structure(self) -> None:
        _, user = build_learning_data_extraction_prompt(
            SAMPLE_FEEDBACK,
            SAMPLE_INPUT,
            SAMPLE_OUTPUT,
        )
        assert "<Task_Context>" in user
        assert "<Data_Sources>" in user
        assert "<Analysis_Protocol>" in user
        assert "<Output_Format>" in user

    def test_user_prompt_has_output_categories(self) -> None:
        _, user = build_learning_data_extraction_prompt(
            SAMPLE_FEEDBACK,
            SAMPLE_INPUT,
            SAMPLE_OUTPUT,
        )
        assert "[RECURRING TECHNICAL FAIL]" in user


# ---------------------------------------------------------------------------
# Cross-subworkflow consistency
# ---------------------------------------------------------------------------


class TestCrossSubworkflowConsistency:
    """The learning data prompt is shared across all subworkflows.

    These tests verify that the prompt structure matches the shared
    pattern used in summarization, markdown, and HTML subworkflows.
    """

    def test_prompt_mentions_post_mortem(self) -> None:
        assert "post-mortem" in _COMBINED

    def test_prompt_has_3_point_summary_constraint(self) -> None:
        assert "3-point summary" in _COMBINED

    def test_prompt_focuses_on_next_run(self) -> None:
        assert "for the next run" in _COMBINED

    def test_prompt_has_character_constraint_awareness(self) -> None:
        assert "character" in _COMBINED
        assert "limit" in _COMBINED
