"""Tests for ica.prompts.markdown_voice_validation."""

from __future__ import annotations

from ica.llm_configs import get_process_prompts
from ica.prompts.markdown_voice_validation import (
    build_voice_validation_prompt,
)

# Load prompts from JSON config (same source the builder function uses).
_SYSTEM, _INSTRUCTION = get_process_prompts("markdown-voice-validation")
_COMBINED = _SYSTEM + "\n" + _INSTRUCTION


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
    """Tests for the VOICE_VALIDATION_PROMPT constant."""

    def test_prompt_is_string(self) -> None:
        assert isinstance(_COMBINED, str)

    def test_prompt_is_not_empty(self) -> None:
        assert len(_COMBINED) > 0

    def test_contains_voice_validator_role(self) -> None:
        assert "strict newsletter voice validator" in _COMBINED

    def test_contains_voice_tone_editorial(self) -> None:
        assert "voice, tone, and editorial integrity" in _COMBINED

    def test_contains_no_rewrite_directive(self) -> None:
        assert "Do NOT re-write content" in _COMBINED

    def test_contains_introduction_check(self) -> None:
        assert "Introduction Check" in _COMBINED

    def test_contains_featured_article_check(self) -> None:
        assert "Featured Article Check" in _COMBINED

    def test_contains_main_articles_check(self) -> None:
        assert "Main Articles Check" in _COMBINED

    def test_contains_overall_voice_check(self) -> None:
        assert "Overall Voice Check" in _COMBINED

    def test_introduction_check_rules(self) -> None:
        assert "striking observation or bold statement" in _COMBINED
        assert "declarative language without hedging" in _COMBINED
        assert "2-3 strategic bold terms" in _COMBINED

    def test_featured_article_check_rules(self) -> None:
        assert "active voice, no hedging" in _COMBINED
        assert "specific data, numbers, or concrete examples" in _COMBINED

    def test_main_articles_check_rules(self) -> None:
        assert "single focused point" in _COMBINED
        assert "Callouts translate to strategic action" in _COMBINED

    def test_overall_voice_rules(self) -> None:
        assert "Contractions used consistently" in _COMBINED
        assert "Direct address to reader" in _COMBINED
        assert "Professional authority without arrogance" in _COMBINED
        assert "concrete business outcome" in _COMBINED

    def test_contains_voice_prefix_rule(self) -> None:
        assert "VOICE:" in _COMBINED

    def test_contains_prior_error_handling(self) -> None:
        assert "PRIOR ERROR HANDLING" in _COMBINED
        assert "copied verbatim" in _COMBINED

    def test_contains_do_not_modify_prior_errors(self) -> None:
        assert "Do NOT rewrite, summarize, deduplicate" in _COMBINED

    def test_contains_output_format(self) -> None:
        assert '"isValid"' in _COMBINED
        assert '"errors"' in _COMBINED

    def test_contains_one_violation_one_error(self) -> None:
        assert "ONE violation = ONE error string" in _COMBINED

    def test_no_n8n_expression_syntax(self) -> None:
        assert "$json" not in _COMBINED
        assert "$(" not in _COMBINED

    def test_hedging_examples(self) -> None:
        assert '"might be"' in _COMBINED
        assert '"could potentially"' in _COMBINED

    def test_contraction_examples(self) -> None:
        assert '"we\'re"' in _COMBINED
        assert '"isn\'t"' in _COMBINED

    def test_no_should_must_rule(self) -> None:
        assert '"should" or "must" statements are avoided' in _COMBINED


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
    """Verify all required voice evaluation sections are covered."""

    def test_four_section_checks(self) -> None:
        sections = [
            "Introduction Check",
            "Featured Article Check",
            "Main Articles Check",
            "Overall Voice Check",
        ]
        for section in sections:
            assert section in _COMBINED

    def test_evaluation_rules_section(self) -> None:
        assert "Evaluation rules" in _COMBINED
        assert "evaluate mechanically" in _COMBINED

    def test_merge_previous_errors_section(self) -> None:
        assert "Merge previous errors" in _COMBINED

    def test_json_only_output_directive(self) -> None:
        assert "Do NOT include markdown, commentary" in _COMBINED

    def test_callout_boxes_evidence_rule(self) -> None:
        assert "Recommendations appear only in callout boxes" in _COMBINED
        assert "grounded in evidence" in _COMBINED
