"""Tests for ica.prompts.markdown_structural_validation."""

from __future__ import annotations

from ica.llm_configs import get_process_prompts
from ica.llm_configs.loader import get_system_prompt
from ica.prompts.markdown_structural_validation import (
    build_structural_validation_prompt,
)

# Load prompts from JSON config (same source the builder function uses).
_SYSTEM, _INSTRUCTION = get_process_prompts("markdown-structural-validation")
_COMBINED = _SYSTEM + "\n" + _INSTRUCTION
_SHARED_SYSTEM = get_system_prompt()


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

SAMPLE_MARKDOWN = """\
# *INTRODUCTION*

AI is reshaping the enterprise faster than we think.

# *QUICK HIGHLIGHTS*

- **OpenAI** just launched GPT-5 with unprecedented reasoning.
- **Google** is integrating Gemini across all Workspace apps.
- **Microsoft** announced Copilot for every Office product.

# *FEATURED ARTICLE*

## [AI Agents Are Here](https://example.com/agents)

First paragraph about agents.

Second paragraph with deeper analysis.

**Key Insight:** Agents will change how we work.

[Read more →](https://example.com/agents)

# *MAIN ARTICLE 1*

## [Enterprise AI Adoption](https://example.com/enterprise)

Enterprise adoption is accelerating across all sectors.

**Strategic Take-away:** Invest now or fall behind.

[Source →](https://example.com/enterprise)

# *MAIN ARTICLE 2*

## [AI in Healthcare](https://example.com/health)

Healthcare is seeing massive AI investment.

**Actionable Steps:** Start with imaging analysis.

[Source →](https://example.com/health)

# *QUICK HITS*

## [Startup Raises $100M](https://example.com/startup)

Brief summary of the startup news.

## [New AI Chip](https://example.com/chip)

Brief summary of the chip news.

## [AI Policy Update](https://example.com/policy)

Brief summary of the policy news.

# *INDUSTRY DEVELOPMENTS*

## [OpenAI Announces GPT-5](https://example.com/gpt5)

OpenAI released GPT-5 with improved reasoning capabilities.

## [Google Launches Gemini 2](https://example.com/gemini2)

Google launched the next generation of Gemini.

# *FOOTER*

Alright, that's a wrap for the week!

See you next time.

Thoughts?
"""

SAMPLE_CHAR_ERRORS = '["QUICK HIGHLIGHTS bullet 1: 145 chars (min 150, delta -5)"]'
EMPTY_CHAR_ERRORS = "[]"


# ---------------------------------------------------------------------------
# Prompt constant tests
# ---------------------------------------------------------------------------


class TestStructuralValidationPromptConstant:
    """Tests for the structural validation prompt constants.

    After the shared system prompt refactoring, ``_SYSTEM`` contains the
    application-wide shared system prompt and ``_INSTRUCTION`` contains
    the per-process instruction template (just the ``{markdown_content}``
    placeholder). Structural validation rules that were previously in the
    per-process system prompt have been removed from the JSON config.
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

    def test_system_has_no_char_errors_placeholder(self) -> None:
        """Shared system prompt does not contain ``{char_errors}``."""
        assert "{char_errors}" not in _SYSTEM

    def test_instruction_contains_markdown_placeholder(self) -> None:
        assert "{markdown_content}" in _INSTRUCTION

    def test_no_n8n_expression_syntax(self) -> None:
        assert "$json" not in _COMBINED
        assert "$(" not in _COMBINED


# ---------------------------------------------------------------------------
# build_structural_validation_prompt() tests
# ---------------------------------------------------------------------------


class TestBuildStructuralValidationPrompt:
    """Tests for the build_structural_validation_prompt() function.

    After the shared system prompt refactoring, the system prompt is the
    shared prompt (no ``{char_errors}`` placeholder). The
    ``system_prompt.format(char_errors=...)`` call in the builder is a
    no-op since the shared prompt has no such placeholder. The user prompt
    is the markdown content from the instruction template.
    """

    def test_returns_tuple(self) -> None:
        result = build_structural_validation_prompt(SAMPLE_MARKDOWN, EMPTY_CHAR_ERRORS)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_strings(self) -> None:
        system, user = build_structural_validation_prompt(SAMPLE_MARKDOWN, EMPTY_CHAR_ERRORS)
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_system_prompt_is_shared_prompt(self) -> None:
        system, _ = build_structural_validation_prompt(SAMPLE_MARKDOWN, SAMPLE_CHAR_ERRORS)
        assert system == _SHARED_SYSTEM

    def test_system_prompt_char_errors_format_is_noop(self) -> None:
        """The format(char_errors=...) call is a no-op on the shared prompt."""
        system, _ = build_structural_validation_prompt(SAMPLE_MARKDOWN, SAMPLE_CHAR_ERRORS)
        assert SAMPLE_CHAR_ERRORS not in system
        assert "{char_errors}" not in system

    def test_user_prompt_is_markdown_content(self) -> None:
        _, user = build_structural_validation_prompt(SAMPLE_MARKDOWN, EMPTY_CHAR_ERRORS)
        assert user == SAMPLE_MARKDOWN

    def test_system_prompt_contains_shared_content(self) -> None:
        system, _ = build_structural_validation_prompt(SAMPLE_MARKDOWN, EMPTY_CHAR_ERRORS)
        assert "AI system" in system
        assert "IS2 Digital newsletter" in system

    def test_empty_markdown_content(self) -> None:
        system, user = build_structural_validation_prompt("", EMPTY_CHAR_ERRORS)
        assert user == ""
        assert system == _SHARED_SYSTEM

    def test_markdown_with_special_characters(self) -> None:
        md = "Content with {braces} and $dollar and %percent"
        _, user = build_structural_validation_prompt(md, EMPTY_CHAR_ERRORS)
        assert user == md


# ---------------------------------------------------------------------------
# Section-specific rule coverage
# ---------------------------------------------------------------------------


class TestSectionRuleCoverage:
    """Verify prompt structure after shared system prompt refactoring.

    Structural validation section rules (QUICK HIGHLIGHTS, FEATURED ARTICLE,
    MAIN ARTICLES, etc.) and the three-step role were previously in the
    per-process system prompt. After the refactoring, ``_SYSTEM`` is the
    shared prompt and ``_INSTRUCTION`` is the minimal input template.
    These tests verify the current prompt structure.
    """

    def test_shared_system_prompt_universal_protocols(self) -> None:
        assert "Universal Protocols" in _SYSTEM

    def test_instruction_contains_markdown_placeholder(self) -> None:
        assert "{markdown_content}" in _INSTRUCTION

    def test_combined_includes_both_prompts(self) -> None:
        assert _SYSTEM in _COMBINED
        assert _INSTRUCTION in _COMBINED


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests for structural validation prompt.

    After the shared system prompt refactoring, ``char_errors`` are no
    longer interpolated into the system prompt (the format call is a
    no-op). These tests verify the builder still handles edge cases
    for markdown content correctly.
    """

    def test_large_char_errors_ignored_by_system_prompt(self) -> None:
        """Large char_errors string does not appear in system (no-op format)."""
        errors = "[" + ", ".join(f'"error {i}"' for i in range(100)) + "]"
        system, _ = build_structural_validation_prompt(SAMPLE_MARKDOWN, errors)
        assert system == _SHARED_SYSTEM

    def test_unicode_in_markdown(self) -> None:
        md = "Content with unicode: \u2192 \u2022 \u201c \u201d"
        _, user = build_structural_validation_prompt(md, EMPTY_CHAR_ERRORS)
        assert "\u2192" in user
        assert "\u2022" in user

    def test_multiline_char_errors_ignored_by_system_prompt(self) -> None:
        """Multiline char_errors string does not appear in system (no-op format)."""
        errors = '[\n  "error 1",\n  "error 2"\n]'
        system, _ = build_structural_validation_prompt(SAMPLE_MARKDOWN, errors)
        assert system == _SHARED_SYSTEM
