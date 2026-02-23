"""Tests for ica.prompts.markdown_structural_validation."""

from __future__ import annotations

import pytest

from ica.prompts.markdown_structural_validation import (
    STRUCTURAL_VALIDATION_PROMPT,
    build_structural_validation_prompt,
)


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
    """Tests for the STRUCTURAL_VALIDATION_PROMPT constant."""

    def test_prompt_is_string(self) -> None:
        assert isinstance(STRUCTURAL_VALIDATION_PROMPT, str)

    def test_prompt_is_not_empty(self) -> None:
        assert len(STRUCTURAL_VALIDATION_PROMPT) > 0

    def test_contains_char_errors_placeholder(self) -> None:
        assert "{char_errors}" in STRUCTURAL_VALIDATION_PROMPT

    def test_contains_validator_role(self) -> None:
        assert "strict newsletter validator" in STRUCTURAL_VALIDATION_PROMPT

    def test_contains_non_negotiable_directive(self) -> None:
        assert "NON-NEGOTIABLE" in STRUCTURAL_VALIDATION_PROMPT

    def test_contains_no_recount_directive(self) -> None:
        assert "MUST NOT re-count characters" in STRUCTURAL_VALIDATION_PROMPT

    def test_contains_quick_highlights_rules(self) -> None:
        assert "Exactly 3 bullets" in STRUCTURAL_VALIDATION_PROMPT

    def test_contains_featured_article_rules(self) -> None:
        assert "clickable Markdown link" in STRUCTURAL_VALIDATION_PROMPT

    def test_contains_main_articles_rules(self) -> None:
        assert "Strategic Take-away" in STRUCTURAL_VALIDATION_PROMPT
        assert "Actionable Steps" in STRUCTURAL_VALIDATION_PROMPT

    def test_contains_industry_developments_rules(self) -> None:
        assert "Exactly 2 items" in STRUCTURAL_VALIDATION_PROMPT

    def test_contains_major_ai_players(self) -> None:
        for player in ("OpenAI", "Google", "Microsoft", "Meta", "Anthropic", "Amazon"):
            assert player in STRUCTURAL_VALIDATION_PROMPT

    def test_contains_footer_rules(self) -> None:
        assert "Alright, that's a wrap for the week!" in STRUCTURAL_VALIDATION_PROMPT
        assert "Thoughts?" in STRUCTURAL_VALIDATION_PROMPT

    def test_contains_output_format(self) -> None:
        assert '"isValid"' in STRUCTURAL_VALIDATION_PROMPT
        assert '"errors"' in STRUCTURAL_VALIDATION_PROMPT

    def test_contains_cta_rules(self) -> None:
        assert "CTA on own line" in STRUCTURAL_VALIDATION_PROMPT
        assert "ends with arrow" in STRUCTURAL_VALIDATION_PROMPT

    def test_contains_key_insight_rule(self) -> None:
        assert "Key Insight starts with bolded two-word label" in STRUCTURAL_VALIDATION_PROMPT

    def test_contains_bullet_order_rule(self) -> None:
        assert "Featured -> Main 1 -> Main 2" in STRUCTURAL_VALIDATION_PROMPT

    def test_no_n8n_expression_syntax(self) -> None:
        assert "{{" not in STRUCTURAL_VALIDATION_PROMPT or \
            STRUCTURAL_VALIDATION_PROMPT.count("{{") == STRUCTURAL_VALIDATION_PROMPT.count("}}")
        # The only {{ }} should be the escaped JSON output format
        assert "$json" not in STRUCTURAL_VALIDATION_PROMPT
        assert "$(" not in STRUCTURAL_VALIDATION_PROMPT


# ---------------------------------------------------------------------------
# build_structural_validation_prompt() tests
# ---------------------------------------------------------------------------


class TestBuildStructuralValidationPrompt:
    """Tests for the build_structural_validation_prompt() function."""

    def test_returns_tuple(self) -> None:
        result = build_structural_validation_prompt(SAMPLE_MARKDOWN, EMPTY_CHAR_ERRORS)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_strings(self) -> None:
        system, user = build_structural_validation_prompt(SAMPLE_MARKDOWN, EMPTY_CHAR_ERRORS)
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_system_prompt_contains_char_errors(self) -> None:
        system, _ = build_structural_validation_prompt(SAMPLE_MARKDOWN, SAMPLE_CHAR_ERRORS)
        assert SAMPLE_CHAR_ERRORS in system

    def test_user_prompt_is_markdown_content(self) -> None:
        _, user = build_structural_validation_prompt(SAMPLE_MARKDOWN, EMPTY_CHAR_ERRORS)
        assert user == SAMPLE_MARKDOWN

    def test_empty_char_errors(self) -> None:
        system, _ = build_structural_validation_prompt(SAMPLE_MARKDOWN, EMPTY_CHAR_ERRORS)
        assert "[]" in system

    def test_char_errors_with_multiple_entries(self) -> None:
        errors = '["error 1", "error 2", "error 3"]'
        system, _ = build_structural_validation_prompt(SAMPLE_MARKDOWN, errors)
        assert errors in system

    def test_system_prompt_retains_validation_rules(self) -> None:
        system, _ = build_structural_validation_prompt(SAMPLE_MARKDOWN, EMPTY_CHAR_ERRORS)
        assert "Exactly 3 bullets" in system
        assert "Exactly 2 items" in system

    def test_placeholder_fully_replaced(self) -> None:
        system, _ = build_structural_validation_prompt(SAMPLE_MARKDOWN, SAMPLE_CHAR_ERRORS)
        assert "{char_errors}" not in system

    def test_empty_markdown_content(self) -> None:
        system, user = build_structural_validation_prompt("", EMPTY_CHAR_ERRORS)
        assert user == ""
        assert "strict newsletter validator" in system

    def test_markdown_with_special_characters(self) -> None:
        md = "Content with {braces} and $dollar and %percent"
        _, user = build_structural_validation_prompt(md, EMPTY_CHAR_ERRORS)
        assert user == md

    def test_char_errors_json_preserved_verbatim(self) -> None:
        errors = '["FEATURED ARTICLE P1: 280 chars (min 300, delta -20)"]'
        system, _ = build_structural_validation_prompt(SAMPLE_MARKDOWN, errors)
        assert errors in system


# ---------------------------------------------------------------------------
# Section-specific rule coverage
# ---------------------------------------------------------------------------


class TestSectionRuleCoverage:
    """Verify that the prompt covers all required validation sections."""

    def test_quick_highlights_section(self) -> None:
        assert "QUICK HIGHLIGHTS" in STRUCTURAL_VALIDATION_PROMPT

    def test_featured_article_section(self) -> None:
        assert "FEATURED ARTICLE" in STRUCTURAL_VALIDATION_PROMPT

    def test_main_articles_section(self) -> None:
        assert "MAIN ARTICLES" in STRUCTURAL_VALIDATION_PROMPT

    def test_industry_developments_section(self) -> None:
        assert "INDUSTRY DEVELOPMENTS" in STRUCTURAL_VALIDATION_PROMPT

    def test_footer_section(self) -> None:
        assert "FOOTER" in STRUCTURAL_VALIDATION_PROMPT

    def test_no_quick_hits_section(self) -> None:
        # Structural validation doesn't cover Quick Hits directly
        # (only character counts, which are upstream)
        pass

    def test_three_role_steps(self) -> None:
        assert "Accept provided character errors exactly as-is" in STRUCTURAL_VALIDATION_PROMPT
        assert "Validate all remaining non-numeric rules" in STRUCTURAL_VALIDATION_PROMPT
        assert "Merge both into a single errors array" in STRUCTURAL_VALIDATION_PROMPT


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests for structural validation prompt."""

    def test_very_large_char_errors(self) -> None:
        errors = "[" + ", ".join(f'"error {i}"' for i in range(100)) + "]"
        system, _ = build_structural_validation_prompt(SAMPLE_MARKDOWN, errors)
        assert errors in system

    def test_unicode_in_markdown(self) -> None:
        md = "Content with unicode: \u2192 \u2022 \u201c \u201d"
        _, user = build_structural_validation_prompt(md, EMPTY_CHAR_ERRORS)
        assert "\u2192" in user
        assert "\u2022" in user

    def test_multiline_char_errors(self) -> None:
        errors = '[\n  "error 1",\n  "error 2"\n]'
        system, _ = build_structural_validation_prompt(SAMPLE_MARKDOWN, errors)
        assert errors in system
