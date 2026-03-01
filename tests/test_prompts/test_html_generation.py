"""Tests for ica.prompts.html_generation."""

from __future__ import annotations

from ica.llm_configs import get_process_prompts
from ica.prompts.html_generation import (
    build_html_generation_prompt,
    build_html_regeneration_prompt,
)

# Load prompts from JSON config (same source the builder function uses).
_GEN_SYSTEM, _GEN_INSTRUCTION = get_process_prompts("html-generation")
_REGEN_SYSTEM, _REGEN_INSTRUCTION = get_process_prompts("html-regeneration")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_MARKDOWN = """\
# *INTRODUCTION*

AI isn't just a buzzword — it's reshaping enterprises.

# *QUICK HIGHLIGHTS*

- **OpenAI** launched GPT-5.
- **Google** integrated Gemini.
- **Microsoft** announced Copilot.

# *FOOTER*

Alright, that's a wrap for the week!

Thoughts?
"""

SAMPLE_HTML_TEMPLATE = """\
<html>
<head><title>Newsletter</title></head>
<body>
<td class="nl-content nl-intro"></td>
<td class="nl-quick-highlights"></td>
<td class="nl-footer"></td>
</body>
</html>
"""

SAMPLE_DATE = "February 22, 2026"
SAMPLE_FEEDBACK = "Make the introduction more engaging and bold."
SAMPLE_AGGREGATED_FEEDBACK = "Prefer shorter paragraphs. Use more bold for key terms."

SAMPLE_PREVIOUS_HTML = """\
<html>
<head><title>Artificially Intelligent, Actually Useful. - February 22, 2026</title></head>
<body>
<td class="nl-content nl-intro"><p>AI isn't just a buzzword.</p></td>
<td class="nl-footer"><p>Alright, that's a wrap for the week!</p></td>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Generation prompt constant tests
# ---------------------------------------------------------------------------


class TestHtmlGenerationSystemPrompt:
    """Tests for the _GEN_SYSTEM constant (shared system prompt)."""

    def test_is_shared_system_prompt(self) -> None:
        from ica.llm_configs.loader import get_system_prompt

        assert get_system_prompt() == _GEN_SYSTEM

    def test_prompt_is_string(self) -> None:
        assert isinstance(_GEN_SYSTEM, str)

    def test_prompt_is_not_empty(self) -> None:
        assert len(_GEN_SYSTEM) > 0

    def test_contains_editorial_engine_identity(self) -> None:
        assert "iS2 Editorial Engine" in _GEN_SYSTEM

    def test_contains_headless_api_mode(self) -> None:
        assert "HEADLESS API" in _GEN_SYSTEM


class TestHtmlGenerationUserPrompt:
    """Tests for the _GEN_INSTRUCTION constant."""

    def test_prompt_is_string(self) -> None:
        assert isinstance(_GEN_INSTRUCTION, str)

    def test_contains_markdown_placeholder(self) -> None:
        assert "{markdown_content}" in _GEN_INSTRUCTION

    def test_contains_template_placeholder(self) -> None:
        assert "{html_template}" in _GEN_INSTRUCTION

    def test_contains_formatted_theme_placeholder(self) -> None:
        assert "{formatted_theme}" in _GEN_INSTRUCTION


# ---------------------------------------------------------------------------
# Regeneration prompt constant tests
# ---------------------------------------------------------------------------


class TestHtmlRegenerationSystemPrompt:
    """Tests for the _REGEN_SYSTEM constant (shared system prompt)."""

    def test_is_shared_system_prompt(self) -> None:
        from ica.llm_configs.loader import get_system_prompt

        assert get_system_prompt() == _REGEN_SYSTEM

    def test_prompt_is_string(self) -> None:
        assert isinstance(_REGEN_SYSTEM, str)

    def test_contains_editorial_engine_identity(self) -> None:
        assert "iS2 Editorial Engine" in _REGEN_SYSTEM

    def test_contains_headless_api_mode(self) -> None:
        assert "HEADLESS API" in _REGEN_SYSTEM


class TestHtmlRegenerationUserPrompt:
    """Tests for the _REGEN_INSTRUCTION constant."""

    def test_prompt_is_string(self) -> None:
        assert isinstance(_REGEN_INSTRUCTION, str)

    def test_contains_all_placeholders(self) -> None:
        assert "{original_html}" in _REGEN_INSTRUCTION
        assert "{user_feedback}" in _REGEN_INSTRUCTION
        assert "{formatted_theme}" in _REGEN_INSTRUCTION


# ---------------------------------------------------------------------------
# build_html_generation_prompt() tests
# ---------------------------------------------------------------------------


class TestBuildHtmlGenerationPrompt:
    """Tests for the build_html_generation_prompt() function."""

    def test_returns_tuple(self) -> None:
        result = build_html_generation_prompt(
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_DATE,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_strings(self) -> None:
        system, user = build_html_generation_prompt(
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_DATE,
        )
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_system_prompt_is_shared(self) -> None:
        from ica.llm_configs.loader import get_system_prompt

        system, _ = build_html_generation_prompt(
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_DATE,
        )
        assert system == get_system_prompt()

    def test_user_prompt_contains_markdown(self) -> None:
        _, user = build_html_generation_prompt(
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_DATE,
        )
        assert SAMPLE_MARKDOWN in user

    def test_user_prompt_contains_template(self) -> None:
        _, user = build_html_generation_prompt(
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_DATE,
        )
        assert SAMPLE_HTML_TEMPLATE in user

    def test_user_prompt_contains_formatted_theme(self) -> None:
        theme = '{"articles": [{"title": "Test"}]}'
        _, user = build_html_generation_prompt(
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_DATE,
            formatted_theme=theme,
        )
        assert theme in user

    def test_no_feedback_section_without_feedback(self) -> None:
        system, _ = build_html_generation_prompt(
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_DATE,
        )
        assert "Editorial Improvement Context" not in system

    def test_feedback_does_not_alter_shared_system_prompt(self) -> None:
        from ica.llm_configs.loader import get_system_prompt

        system, _ = build_html_generation_prompt(
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_DATE,
            aggregated_feedback=SAMPLE_AGGREGATED_FEEDBACK,
        )
        assert system == get_system_prompt()

    def test_feedback_section_none(self) -> None:
        system, _ = build_html_generation_prompt(
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_DATE,
            aggregated_feedback=None,
        )
        assert "Editorial Improvement Context" not in system

    def test_feedback_section_empty_string(self) -> None:
        system, _ = build_html_generation_prompt(
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_DATE,
            aggregated_feedback="",
        )
        assert "Editorial Improvement Context" not in system

    def test_feedback_section_whitespace_only(self) -> None:
        system, _ = build_html_generation_prompt(
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_DATE,
            aggregated_feedback="   \n  ",
        )
        assert "Editorial Improvement Context" not in system

    def test_all_placeholders_replaced(self) -> None:
        system, user = build_html_generation_prompt(
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_DATE,
            aggregated_feedback=SAMPLE_AGGREGATED_FEEDBACK,
        )
        assert "{feedback_section}" not in system
        assert "{markdown_content}" not in user
        assert "{html_template}" not in user
        assert "{newsletter_date}" not in user
        assert "{aggregated_feedback}" not in system


# ---------------------------------------------------------------------------
# build_html_regeneration_prompt() tests
# ---------------------------------------------------------------------------


class TestBuildHtmlRegenerationPrompt:
    """Tests for the build_html_regeneration_prompt() function."""

    def test_returns_tuple(self) -> None:
        result = build_html_regeneration_prompt(
            SAMPLE_PREVIOUS_HTML,
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_FEEDBACK,
            SAMPLE_DATE,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_strings(self) -> None:
        system, user = build_html_regeneration_prompt(
            SAMPLE_PREVIOUS_HTML,
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_FEEDBACK,
            SAMPLE_DATE,
        )
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_system_prompt_is_regeneration(self) -> None:
        system, _ = build_html_regeneration_prompt(
            SAMPLE_PREVIOUS_HTML,
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_FEEDBACK,
            SAMPLE_DATE,
        )
        assert system == _REGEN_SYSTEM

    def test_user_prompt_contains_previous_html(self) -> None:
        _, user = build_html_regeneration_prompt(
            SAMPLE_PREVIOUS_HTML,
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_FEEDBACK,
            SAMPLE_DATE,
        )
        assert SAMPLE_PREVIOUS_HTML in user

    def test_user_prompt_contains_formatted_theme(self) -> None:
        theme = '{"articles": [{"title": "Test"}]}'
        _, user = build_html_regeneration_prompt(
            SAMPLE_PREVIOUS_HTML,
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_FEEDBACK,
            SAMPLE_DATE,
            formatted_theme=theme,
        )
        assert theme in user

    def test_user_prompt_contains_feedback(self) -> None:
        _, user = build_html_regeneration_prompt(
            SAMPLE_PREVIOUS_HTML,
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_FEEDBACK,
            SAMPLE_DATE,
        )
        assert SAMPLE_FEEDBACK in user

    def test_user_prompt_contains_date(self) -> None:
        _, user = build_html_regeneration_prompt(
            SAMPLE_PREVIOUS_HTML,
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_FEEDBACK,
            SAMPLE_DATE,
        )
        assert SAMPLE_DATE in user

    def test_all_placeholders_replaced(self) -> None:
        _, user = build_html_regeneration_prompt(
            SAMPLE_PREVIOUS_HTML,
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_FEEDBACK,
            SAMPLE_DATE,
        )
        assert "{original_html}" not in user
        assert "{user_feedback}" not in user
        assert "{formatted_theme}" not in user


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestHtmlGenerationEdgeCases:
    """Edge case tests for HTML generation prompts."""

    def test_empty_markdown(self) -> None:
        _, user = build_html_generation_prompt("", SAMPLE_HTML_TEMPLATE, SAMPLE_DATE)
        assert "Markdown Content:" in user

    def test_empty_template(self) -> None:
        _, user = build_html_generation_prompt(SAMPLE_MARKDOWN, "", SAMPLE_DATE)
        assert "HTML Master Template:" in user

    def test_empty_formatted_theme(self) -> None:
        _, user = build_html_generation_prompt(SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE)
        assert "Master Link List" in user

    def test_unicode_in_markdown(self) -> None:
        md = "Content with arrows \u2192 and em-dashes \u2014"
        _, user = build_html_generation_prompt(md, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE)
        assert md in user

    def test_html_entities_in_template(self) -> None:
        template = "<p>&amp; &lt; &gt; &quot;</p>"
        _, user = build_html_generation_prompt(SAMPLE_MARKDOWN, template, SAMPLE_DATE)
        assert template in user

    def test_regeneration_empty_feedback(self) -> None:
        _, user = build_html_regeneration_prompt(
            SAMPLE_PREVIOUS_HTML,
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            "",
            SAMPLE_DATE,
        )
        assert "Fix Instructions:" in user

    def test_very_large_html(self) -> None:
        large_html = "<div>" * 1000 + "</div>" * 1000
        _, user = build_html_regeneration_prompt(
            large_html,
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_FEEDBACK,
            SAMPLE_DATE,
        )
        assert large_html in user
