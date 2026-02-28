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

    After the shared system prompt refactoring, ``_SYSTEM`` contains the
    application-wide shared system prompt and ``_INSTRUCTION`` contains the
    per-process instruction template with input/prior-errors placeholders.
    """

    def test_prompt_is_string(self) -> None:
        assert isinstance(_COMBINED, str)

    def test_prompt_is_not_empty(self) -> None:
        assert len(_COMBINED) > 0

    def test_system_is_shared_system_prompt(self) -> None:
        assert _SYSTEM == _SHARED_SYSTEM

    def test_system_contains_ai_system_role(self) -> None:
        assert "AI system" in _SYSTEM
        assert "IS2 Digital newsletter" in _SYSTEM

    def test_system_contains_data_integrity(self) -> None:
        assert "Data Integrity" in _SYSTEM
        assert "Use ONLY the data and content explicitly provided" in _SYSTEM

    def test_system_contains_output_integrity(self) -> None:
        assert "Output Integrity" in _SYSTEM
        assert "exact format specified per process" in _SYSTEM

    def test_system_contains_audience_context(self) -> None:
        assert "Audience Context" in _SYSTEM
        assert "solopreneurs and SMB professionals" in _SYSTEM

    def test_instruction_contains_input_header(self) -> None:
        assert "### INPUT" in _INSTRUCTION

    def test_instruction_contains_markdown_placeholder(self) -> None:
        assert "{markdown_content}" in _INSTRUCTION

    def test_instruction_contains_prior_errors_header(self) -> None:
        assert "PRIOR_ERRORS_JSON" in _INSTRUCTION
        assert "DO NOT MODIFY" in _INSTRUCTION

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

    def test_user_prompt_has_input_header(self) -> None:
        _, user = build_voice_validation_prompt(SAMPLE_MARKDOWN, EMPTY_PRIOR_ERRORS)
        assert "### INPUT" in user

    def test_user_prompt_has_prior_errors_header(self) -> None:
        _, user = build_voice_validation_prompt(SAMPLE_MARKDOWN, EMPTY_PRIOR_ERRORS)
        assert "PRIOR_ERRORS_JSON" in user
        assert "DO NOT MODIFY" in user

    def test_empty_markdown(self) -> None:
        system, user = build_voice_validation_prompt("", EMPTY_PRIOR_ERRORS)
        assert system == _SYSTEM
        assert "### INPUT" in user

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
    """Verify prompt structure after shared system prompt refactoring.

    Voice-specific evaluation rules (section checks, evaluation rules,
    merge directives, etc.) were previously embedded in the per-process
    system prompt. After the refactoring, ``_SYSTEM`` is the shared prompt
    and ``_INSTRUCTION`` is the minimal input template. These tests verify
    the current prompt structure.
    """

    def test_shared_system_prompt_universal_protocols(self) -> None:
        assert "Universal Protocols" in _SYSTEM

    def test_instruction_has_input_section(self) -> None:
        assert "### INPUT" in _INSTRUCTION
        assert "newsletter content" in _INSTRUCTION

    def test_instruction_has_prior_errors_section(self) -> None:
        assert "PRIOR_ERRORS_JSON" in _INSTRUCTION
        assert "AUTHORITATIVE" in _INSTRUCTION

    def test_combined_includes_both_prompts(self) -> None:
        assert _SYSTEM in _COMBINED
        assert _INSTRUCTION in _COMBINED
