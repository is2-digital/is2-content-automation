"""Tests for ica.prompts.markdown_voice_validation."""

from __future__ import annotations

from ica.llm_configs import get_process_prompts
from ica.llm_configs.loader import get_system_prompt
from ica.prompts.markdown_voice_validation import (
    build_voice_validation_prompt,
)

# Load prompts from JSON config (same source the builder function uses).
_SYSTEM, _INSTRUCTION = get_process_prompts("markdown-voice-validation")
_COMBINED = _SYSTEM + "\n" + _INSTRUCTION
_SHARED_SYSTEM = get_system_prompt()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_MARKDOWN = """\
# *INTRODUCTION*

AI isn't just a buzzword anymore — it's reshaping how enterprises operate.

# *FEATURED ARTICLE*

## [The Rise of AI Agents](https://example.com/agents)

Autonomous agents are transforming workflows across industries.

**Key Insight:** This isn't hype — it's operational reality.

[Read more →](https://example.com/agents)
"""

SAMPLE_PRIOR_ERRORS = (
    '{"output": {"isValid": false, "errors": ["QH bullet 1: 145 chars (min 150, delta -5)"]}}'
)
EMPTY_PRIOR_ERRORS = '{"output": {"isValid": true, "errors": []}}'


# ---------------------------------------------------------------------------
# Prompt constant tests
# ---------------------------------------------------------------------------


class TestVoiceValidationPromptConstant:
    """Tests for the voice validation prompt constants.

    After the XML-tagged prompt refactoring, ``_SYSTEM`` contains the
    shared system prompt (iS2 Editorial Engine persona) and ``_INSTRUCTION``
    contains the per-process instruction template with XML-tagged sections
    for voice evaluation criteria and prior error handling.
    """

    def test_prompt_is_string(self) -> None:
        assert isinstance(_COMBINED, str)

    def test_prompt_is_not_empty(self) -> None:
        assert len(_COMBINED) > 0

    def test_system_is_shared_system_prompt(self) -> None:
        assert _SYSTEM == _SHARED_SYSTEM

    def test_system_contains_editorial_engine_role(self) -> None:
        assert "iS2 Editorial Engine" in _SYSTEM
        assert "Kevin" in _SYSTEM

    def test_system_contains_headless_api_mode(self) -> None:
        assert "HEADLESS API" in _SYSTEM
        assert "STRICT OUTPUT" in _SYSTEM

    def test_system_contains_zero_hallucination(self) -> None:
        assert "ZERO HALLUCINATION" in _SYSTEM
        assert "Use only provided Input data" in _SYSTEM

    def test_system_contains_voice_guardrails(self) -> None:
        assert "VOICE & FORMATTING GUARDRAILS" in _SYSTEM

    def test_instruction_contains_voice_evaluation(self) -> None:
        assert "Voice_Evaluation_Criteria" in _INSTRUCTION

    def test_instruction_contains_markdown_placeholder(self) -> None:
        assert "{markdown_content}" in _INSTRUCTION

    def test_instruction_contains_prior_error_handling(self) -> None:
        assert "Prior_Error_Handling" in _INSTRUCTION
        assert "{prior_errors_json}" in _INSTRUCTION

    def test_instruction_contains_prior_errors_placeholder(self) -> None:
        assert "{prior_errors_json}" in _INSTRUCTION

    def test_no_n8n_expression_syntax(self) -> None:
        assert "$json" not in _COMBINED
        assert "$(" not in _COMBINED


# ---------------------------------------------------------------------------
# build_voice_validation_prompt() tests
# ---------------------------------------------------------------------------


class TestBuildVoiceValidationPrompt:
    """Tests for the build_voice_validation_prompt() function."""

    def test_returns_tuple(self) -> None:
        result = build_voice_validation_prompt(SAMPLE_MARKDOWN, EMPTY_PRIOR_ERRORS)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_strings(self) -> None:
        system, user = build_voice_validation_prompt(SAMPLE_MARKDOWN, EMPTY_PRIOR_ERRORS)
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_system_prompt_is_voice_prompt(self) -> None:
        system, _ = build_voice_validation_prompt(SAMPLE_MARKDOWN, EMPTY_PRIOR_ERRORS)
        assert system == _SYSTEM

    def test_user_prompt_contains_markdown(self) -> None:
        _, user = build_voice_validation_prompt(SAMPLE_MARKDOWN, EMPTY_PRIOR_ERRORS)
        assert SAMPLE_MARKDOWN in user

    def test_user_prompt_contains_prior_errors(self) -> None:
        _, user = build_voice_validation_prompt(SAMPLE_MARKDOWN, SAMPLE_PRIOR_ERRORS)
        assert SAMPLE_PRIOR_ERRORS in user

    def test_user_prompt_has_input_data_tag(self) -> None:
        _, user = build_voice_validation_prompt(SAMPLE_MARKDOWN, EMPTY_PRIOR_ERRORS)
        assert "Input_Data" in user

    def test_user_prompt_has_prior_error_handling(self) -> None:
        _, user = build_voice_validation_prompt(SAMPLE_MARKDOWN, EMPTY_PRIOR_ERRORS)
        assert "Prior_Error_Handling" in user

    def test_empty_markdown(self) -> None:
        system, user = build_voice_validation_prompt("", EMPTY_PRIOR_ERRORS)
        assert system == _SYSTEM
        assert "Input_Data" in user

    def test_empty_prior_errors(self) -> None:
        _, user = build_voice_validation_prompt(SAMPLE_MARKDOWN, "")
        assert SAMPLE_MARKDOWN in user

    def test_prior_errors_with_multiple_entries(self) -> None:
        errors = '{"output": {"isValid": false, "errors": ["err1", "err2", "err3"]}}'
        _, user = build_voice_validation_prompt(SAMPLE_MARKDOWN, errors)
        assert errors in user

    def test_markdown_with_unicode(self) -> None:
        md = "Content with arrows \u2192 and bullets \u2022"
        _, user = build_voice_validation_prompt(md, EMPTY_PRIOR_ERRORS)
        assert md in user

    def test_prior_errors_preserved_verbatim(self) -> None:
        """Prior errors JSON must not be modified or reformatted."""
        errors = '{"output":{"isValid":false,"errors":["QUICK HIGHLIGHTS bullet 1: 145 chars"]}}'
        _, user = build_voice_validation_prompt(SAMPLE_MARKDOWN, errors)
        assert errors in user


# ---------------------------------------------------------------------------
# Voice-specific rule sections
# ---------------------------------------------------------------------------


class TestVoiceRuleSections:
    """Verify prompt structure after XML-tagged prompt refactoring.

    Voice-specific evaluation rules are in the per-process instruction
    template inside XML tags. The shared system prompt defines the iS2
    Editorial Engine persona.
    """

    def test_shared_system_prompt_has_role_identity(self) -> None:
        assert "ROLE & IDENTITY" in _SYSTEM

    def test_instruction_has_input_data_section(self) -> None:
        assert "Input_Data" in _INSTRUCTION
        assert "Newsletter Content" in _INSTRUCTION

    def test_instruction_has_prior_error_handling_section(self) -> None:
        assert "Prior_Error_Handling" in _INSTRUCTION
        assert "verbatim" in _INSTRUCTION

    def test_combined_includes_both_prompts(self) -> None:
        assert _SYSTEM in _COMBINED
        assert _INSTRUCTION in _COMBINED
