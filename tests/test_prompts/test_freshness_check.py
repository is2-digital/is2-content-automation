"""Tests for ica.prompts.freshness_check."""

from __future__ import annotations

import pytest

from ica.prompts.freshness_check import (
    FRESHNESS_CHECK_PROMPT,
    build_freshness_check_prompt,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_THEME_BODY = """\
THEME: AI Agents Are Reshaping Enterprise Workflows

%FA_TITLE: How AI Agents Are Changing the Way We Work
%FA_SOURCE: TechCrunch
%FA_URL: https://example.com/agents
%FA_CATEGORY: automation
%FA_WHY_FEATURED: First comprehensive enterprise agent deployment study

%M1_TITLE: Google Launches Gemini Agent API
%M1_SOURCE: The Verge
%M1_URL: https://example.com/gemini-agents
%M1_CATEGORY: product_launch

%M2_TITLE: Microsoft Copilot Gets Agent Capabilities
%M2_SOURCE: ZDNet
%M2_URL: https://example.com/copilot-agents
%M2_CATEGORY: product_update
"""


# ---------------------------------------------------------------------------
# Prompt constant tests
# ---------------------------------------------------------------------------


class TestFreshnessCheckPromptConstant:
    """Tests for the FRESHNESS_CHECK_PROMPT constant."""

    def test_prompt_is_string(self) -> None:
        assert isinstance(FRESHNESS_CHECK_PROMPT, str)

    def test_prompt_is_not_empty(self) -> None:
        assert len(FRESHNESS_CHECK_PROMPT) > 0

    def test_contains_theme_placeholder(self) -> None:
        assert "{theme_body}" in FRESHNESS_CHECK_PROMPT

    def test_contains_newsletter_site_url(self) -> None:
        assert "https://www.is2digital.com/newsletters" in FRESHNESS_CHECK_PROMPT

    def test_contains_freshness_check_context(self) -> None:
        assert "editorial freshness" in FRESHNESS_CHECK_PROMPT

    def test_contains_repetitiveness_check(self) -> None:
        assert "not repetitive" in FRESHNESS_CHECK_PROMPT

    def test_contains_recent_newsletters_reference(self) -> None:
        assert "3 most recent" in FRESHNESS_CHECK_PROMPT

    def test_contains_structured_output_request(self) -> None:
        assert "structured output" in FRESHNESS_CHECK_PROMPT

    def test_contains_change_explanation_request(self) -> None:
        assert "what to change" in FRESHNESS_CHECK_PROMPT
        assert "explain why" in FRESHNESS_CHECK_PROMPT

    def test_no_n8n_expression_syntax(self) -> None:
        assert "$json" not in FRESHNESS_CHECK_PROMPT
        assert "$(" not in FRESHNESS_CHECK_PROMPT


# ---------------------------------------------------------------------------
# build_freshness_check_prompt() tests
# ---------------------------------------------------------------------------


class TestBuildFreshnessCheckPrompt:
    """Tests for the build_freshness_check_prompt() function."""

    def test_returns_tuple(self) -> None:
        result = build_freshness_check_prompt(SAMPLE_THEME_BODY)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_strings(self) -> None:
        system, user = build_freshness_check_prompt(SAMPLE_THEME_BODY)
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_system_prompt_contains_role(self) -> None:
        system, _ = build_freshness_check_prompt(SAMPLE_THEME_BODY)
        assert "newsletter" in system
        assert "editorial" in system

    def test_user_prompt_contains_theme_body(self) -> None:
        _, user = build_freshness_check_prompt(SAMPLE_THEME_BODY)
        assert SAMPLE_THEME_BODY in user

    def test_placeholder_fully_replaced(self) -> None:
        _, user = build_freshness_check_prompt(SAMPLE_THEME_BODY)
        assert "{theme_body}" not in user

    def test_user_prompt_contains_site_url(self) -> None:
        _, user = build_freshness_check_prompt(SAMPLE_THEME_BODY)
        assert "https://www.is2digital.com/newsletters" in user

    def test_empty_theme_body(self) -> None:
        system, user = build_freshness_check_prompt("")
        assert "newsletter" in system
        assert "editorial freshness" in user

    def test_theme_body_with_special_characters(self) -> None:
        body = "Theme with {braces} and $dollar and %markers"
        _, user = build_freshness_check_prompt(body)
        assert body in user

    def test_theme_body_with_unicode(self) -> None:
        body = "Theme with arrows \u2192 and em-dashes \u2014"
        _, user = build_freshness_check_prompt(body)
        assert body in user

    def test_multiline_theme_body_preserved(self) -> None:
        _, user = build_freshness_check_prompt(SAMPLE_THEME_BODY)
        assert "%FA_TITLE:" in user
        assert "%M1_TITLE:" in user
        assert "%M2_TITLE:" in user

    def test_system_prompt_describes_freshness_role(self) -> None:
        system, _ = build_freshness_check_prompt(SAMPLE_THEME_BODY)
        assert "fresh" in system or "non-repetitive" in system


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestFreshnessCheckEdgeCases:
    """Edge case tests for freshness check prompt."""

    def test_very_long_theme_body(self) -> None:
        body = "A" * 10000
        _, user = build_freshness_check_prompt(body)
        assert body in user

    def test_theme_body_with_markers(self) -> None:
        body = "%FA_TITLE: Test\n%M1_TITLE: Test 2"
        _, user = build_freshness_check_prompt(body)
        assert "%FA_TITLE: Test" in user
        assert "%M1_TITLE: Test 2" in user

    def test_whitespace_only_theme_body(self) -> None:
        _, user = build_freshness_check_prompt("   \n  \n  ")
        assert "editorial freshness" in user
