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

    After the XML-tagged prompt refactoring, ``_SYSTEM`` contains the
    shared system prompt (iS2 Editorial Engine persona) and ``_INSTRUCTION``
    contains the per-process instruction template with ``{markdown_content}``
    and ``{char_errors}`` placeholders inside XML tags.
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

    def test_system_has_no_char_errors_placeholder(self) -> None:
        """Shared system prompt does not contain ``{char_errors}``."""
        assert "{char_errors}" not in _SYSTEM

    def test_instruction_contains_markdown_placeholder(self) -> None:
        assert "{markdown_content}" in _INSTRUCTION

    def test_instruction_contains_char_errors_placeholder(self) -> None:
        assert "{char_errors}" in _INSTRUCTION

    def test_no_n8n_expression_syntax(self) -> None:
        assert "$json" not in _COMBINED
        assert "$(" not in _COMBINED


# ---------------------------------------------------------------------------
# build_structural_validation_prompt() tests
# ---------------------------------------------------------------------------


class TestBuildStructuralValidationPrompt:
    """Tests for the build_structural_validation_prompt() function.

    After the XML-tagged prompt refactoring, the instruction template
    contains ``{markdown_content}`` and ``{char_errors}`` placeholders.
    Both are interpolated into the user prompt by the builder function.
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
        """char_errors does not appear in the system prompt."""
        system, _ = build_structural_validation_prompt(SAMPLE_MARKDOWN, SAMPLE_CHAR_ERRORS)
        assert SAMPLE_CHAR_ERRORS not in system
        assert "{char_errors}" not in system

    def test_user_prompt_contains_markdown_content(self) -> None:
        _, user = build_structural_validation_prompt(SAMPLE_MARKDOWN, EMPTY_CHAR_ERRORS)
        assert SAMPLE_MARKDOWN in user

    def test_user_prompt_contains_char_errors(self) -> None:
        _, user = build_structural_validation_prompt(SAMPLE_MARKDOWN, SAMPLE_CHAR_ERRORS)
        assert SAMPLE_CHAR_ERRORS in user

    def test_system_prompt_contains_shared_content(self) -> None:
        system, _ = build_structural_validation_prompt(SAMPLE_MARKDOWN, EMPTY_CHAR_ERRORS)
        assert "iS2 Editorial Engine" in system
        assert "Kevin" in system

    def test_empty_markdown_content(self) -> None:
        system, user = build_structural_validation_prompt("", EMPTY_CHAR_ERRORS)
        assert EMPTY_CHAR_ERRORS in user
        assert system == _SHARED_SYSTEM

    def test_markdown_with_special_characters(self) -> None:
        md = "Content with {braces} and $dollar and %percent"
        _, user = build_structural_validation_prompt(md, EMPTY_CHAR_ERRORS)
        assert md in user

    def test_no_unresolved_placeholders(self) -> None:
        _, user = build_structural_validation_prompt(SAMPLE_MARKDOWN, SAMPLE_CHAR_ERRORS)
        assert "{markdown_content}" not in user
        assert "{char_errors}" not in user


# ---------------------------------------------------------------------------
# Section-specific rule coverage
# ---------------------------------------------------------------------------


class TestSectionRuleCoverage:
    """Verify prompt structure after XML-tagged prompt refactoring.

    Structural validation rules (QUICK HIGHLIGHTS, FEATURED ARTICLE,
    MAIN ARTICLES, etc.) are in the per-process instruction template
    inside XML tags. The shared system prompt defines the iS2 Editorial
    Engine persona.
    """

    def test_shared_system_prompt_has_role_identity(self) -> None:
        assert "ROLE & IDENTITY" in _SYSTEM

    def test_instruction_contains_markdown_placeholder(self) -> None:
        assert "{markdown_content}" in _INSTRUCTION

    def test_instruction_contains_validation_authority(self) -> None:
        """Instruction has XML-tagged validation rules."""
        assert "Validation_Authority" in _INSTRUCTION

    def test_instruction_contains_structural_rules(self) -> None:
        """Instruction contains section-specific structural rules."""
        assert "QUICK HIGHLIGHTS" in _INSTRUCTION
        assert "FEATURED ARTICLE" in _INSTRUCTION
        assert "MAIN ARTICLES" in _INSTRUCTION
        assert "INDUSTRY DEVELOPMENTS" in _INSTRUCTION
        assert "FOOTER" in _INSTRUCTION

    def test_combined_includes_both_prompts(self) -> None:
        assert _SYSTEM in _COMBINED
        assert _INSTRUCTION in _COMBINED


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests for structural validation prompt.

    Both ``markdown_content`` and ``char_errors`` are interpolated into
    the instruction template. The system prompt is always the shared
    prompt unchanged.
    """

    def test_large_char_errors_in_user_prompt(self) -> None:
        """Large char_errors string appears in user prompt, not system."""
        errors = "[" + ", ".join(f'"error {i}"' for i in range(100)) + "]"
        system, user = build_structural_validation_prompt(SAMPLE_MARKDOWN, errors)
        assert system == _SHARED_SYSTEM
        assert errors in user

    def test_unicode_in_markdown(self) -> None:
        md = "Content with unicode: \u2192 \u2022 \u201c \u201d"
        _, user = build_structural_validation_prompt(md, EMPTY_CHAR_ERRORS)
        assert "\u2192" in user
        assert "\u2022" in user

    def test_multiline_char_errors_in_user_prompt(self) -> None:
        """Multiline char_errors string appears in user prompt, not system."""
        errors = '[\n  "error 1",\n  "error 2"\n]'
        system, user = build_structural_validation_prompt(SAMPLE_MARKDOWN, errors)
        assert system == _SHARED_SYSTEM
        assert errors in user
