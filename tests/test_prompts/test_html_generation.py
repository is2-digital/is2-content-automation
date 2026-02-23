"""Tests for ica.prompts.html_generation."""

from __future__ import annotations

import pytest

from ica.prompts.html_generation import (
    HTML_GENERATION_SYSTEM_PROMPT,
    HTML_GENERATION_USER_PROMPT,
    HTML_REGENERATION_SYSTEM_PROMPT,
    HTML_REGENERATION_USER_PROMPT,
    build_html_generation_prompt,
    build_html_regeneration_prompt,
)


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
    """Tests for the HTML_GENERATION_SYSTEM_PROMPT constant."""

    def test_prompt_is_string(self) -> None:
        assert isinstance(HTML_GENERATION_SYSTEM_PROMPT, str)

    def test_prompt_is_not_empty(self) -> None:
        assert len(HTML_GENERATION_SYSTEM_PROMPT) > 0

    def test_contains_role(self) -> None:
        assert "HTML rendering engine" in HTML_GENERATION_SYSTEM_PROMPT

    def test_contains_feedback_placeholder(self) -> None:
        assert "{feedback_section}" in HTML_GENERATION_SYSTEM_PROMPT

    def test_contains_template_preservation_rules(self) -> None:
        assert "TEMPLATE PRESERVATION RULES" in HTML_GENERATION_SYSTEM_PROMPT
        assert "NON-NEGOTIABLE" in HTML_GENERATION_SYSTEM_PROMPT

    def test_contains_do_not_modify_list(self) -> None:
        rules = [
            "CSS class names",
            "Inline style attributes",
            "Table structures",
            "HTML hierarchy or nesting",
        ]
        for rule in rules:
            assert rule in HTML_GENERATION_SYSTEM_PROMPT

    def test_contains_all_seven_sections(self) -> None:
        sections = [
            "INTRODUCTION",
            "QUICK HIGHLIGHTS",
            "FEATURED ARTICLE",
            "MAIN ARTICLES",
            "QUICK HITS",
            "INDUSTRY DEVELOPMENTS",
            "FOOTER",
        ]
        for section in sections:
            assert section in HTML_GENERATION_SYSTEM_PROMPT

    def test_contains_html_class_mappings(self) -> None:
        classes = [
            "nl-content nl-intro",
            "nl-quick-highlights",
            "nl-content nl-main",
            "nl-article-box",
            "nl-quick-hits",
            "nl-industry",
            "nl-footer",
        ]
        for cls in classes:
            assert cls in HTML_GENERATION_SYSTEM_PROMPT

    def test_contains_link_requirement(self) -> None:
        assert 'target="_blank"' in HTML_GENERATION_SYSTEM_PROMPT

    def test_contains_title_date_insertion(self) -> None:
        assert "Artificially Intelligent, Actually Useful" in HTML_GENERATION_SYSTEM_PROMPT
        assert "nl-date" in HTML_GENERATION_SYSTEM_PROMPT

    def test_contains_self_check(self) -> None:
        assert "FINAL SELF-CHECK" in HTML_GENERATION_SYSTEM_PROMPT

    def test_contains_output_requirements(self) -> None:
        assert "Output only valid HTML" in HTML_GENERATION_SYSTEM_PROMPT
        assert "Do not include explanations" in HTML_GENERATION_SYSTEM_PROMPT

    def test_footer_rules(self) -> None:
        assert "Alright, that's a wrap for the week!" in HTML_GENERATION_SYSTEM_PROMPT
        assert "Thoughts?" in HTML_GENERATION_SYSTEM_PROMPT

    def test_cta_button_rules(self) -> None:
        assert "CTA button" in HTML_GENERATION_SYSTEM_PROMPT

    def test_source_link_rules(self) -> None:
        assert "nl-source-link" in HTML_GENERATION_SYSTEM_PROMPT

    def test_bold_emphasis_rules(self) -> None:
        assert "Preserve bold emphasis" in HTML_GENERATION_SYSTEM_PROMPT

    def test_no_n8n_expression_syntax(self) -> None:
        assert "$json" not in HTML_GENERATION_SYSTEM_PROMPT
        assert "$(" not in HTML_GENERATION_SYSTEM_PROMPT


class TestHtmlGenerationUserPrompt:
    """Tests for the HTML_GENERATION_USER_PROMPT constant."""

    def test_prompt_is_string(self) -> None:
        assert isinstance(HTML_GENERATION_USER_PROMPT, str)

    def test_contains_markdown_placeholder(self) -> None:
        assert "{markdown_content}" in HTML_GENERATION_USER_PROMPT

    def test_contains_template_placeholder(self) -> None:
        assert "{html_template}" in HTML_GENERATION_USER_PROMPT

    def test_contains_date_placeholder(self) -> None:
        assert "{newsletter_date}" in HTML_GENERATION_USER_PROMPT


# ---------------------------------------------------------------------------
# Regeneration prompt constant tests
# ---------------------------------------------------------------------------


class TestHtmlRegenerationSystemPrompt:
    """Tests for the HTML_REGENERATION_SYSTEM_PROMPT constant."""

    def test_prompt_is_string(self) -> None:
        assert isinstance(HTML_REGENERATION_SYSTEM_PROMPT, str)

    def test_contains_scoped_update_role(self) -> None:
        assert "scoped update mode" in HTML_REGENERATION_SYSTEM_PROMPT

    def test_contains_not_full_regeneration(self) -> None:
        assert "not a full regeneration" in HTML_REGENERATION_SYSTEM_PROMPT

    def test_contains_five_inputs(self) -> None:
        assert "Previously Generated HTML" in HTML_REGENERATION_SYSTEM_PROMPT
        assert "Final Generated Markdown Content" in HTML_REGENERATION_SYSTEM_PROMPT
        assert "HTML Template" in HTML_REGENERATION_SYSTEM_PROMPT
        assert "User Feedback" in HTML_REGENERATION_SYSTEM_PROMPT
        assert "Newsletter Date" in HTML_REGENERATION_SYSTEM_PROMPT

    def test_contains_scope_enforcement(self) -> None:
        assert "SCOPE ENFORCEMENT" in HTML_REGENERATION_SYSTEM_PROMPT

    def test_contains_must_rules(self) -> None:
        assert "Identify which section(s) the feedback refers to" in HTML_REGENERATION_SYSTEM_PROMPT
        assert "Modify only those sections" in HTML_REGENERATION_SYSTEM_PROMPT

    def test_contains_must_not_rules(self) -> None:
        assert "Re-render the entire newsletter" in HTML_REGENERATION_SYSTEM_PROMPT
        assert "Touch sections not mentioned in feedback" in HTML_REGENERATION_SYSTEM_PROMPT

    def test_contains_allowed_modifications(self) -> None:
        assert "Text changes" in HTML_REGENERATION_SYSTEM_PROMPT
        assert "Link updates" in HTML_REGENERATION_SYSTEM_PROMPT
        assert "Emphasis changes" in HTML_REGENERATION_SYSTEM_PROMPT

    def test_contains_guarantee_clause(self) -> None:
        assert "GUARANTEE CLAUSE" in HTML_REGENERATION_SYSTEM_PROMPT
        assert "make no modification" in HTML_REGENERATION_SYSTEM_PROMPT

    def test_contains_output_requirements(self) -> None:
        assert "Output only valid HTML" in HTML_REGENERATION_SYSTEM_PROMPT
        assert "Return the entire HTML document" in HTML_REGENERATION_SYSTEM_PROMPT

    def test_contains_self_check(self) -> None:
        assert "FINAL SELF-CHECK" in HTML_REGENERATION_SYSTEM_PROMPT

    def test_no_n8n_expression_syntax(self) -> None:
        assert "$json" not in HTML_REGENERATION_SYSTEM_PROMPT
        assert "$(" not in HTML_REGENERATION_SYSTEM_PROMPT


class TestHtmlRegenerationUserPrompt:
    """Tests for the HTML_REGENERATION_USER_PROMPT constant."""

    def test_prompt_is_string(self) -> None:
        assert isinstance(HTML_REGENERATION_USER_PROMPT, str)

    def test_contains_all_placeholders(self) -> None:
        assert "{previous_html}" in HTML_REGENERATION_USER_PROMPT
        assert "{markdown_content}" in HTML_REGENERATION_USER_PROMPT
        assert "{html_template}" in HTML_REGENERATION_USER_PROMPT
        assert "{user_feedback}" in HTML_REGENERATION_USER_PROMPT
        assert "{newsletter_date}" in HTML_REGENERATION_USER_PROMPT


# ---------------------------------------------------------------------------
# build_html_generation_prompt() tests
# ---------------------------------------------------------------------------


class TestBuildHtmlGenerationPrompt:
    """Tests for the build_html_generation_prompt() function."""

    def test_returns_tuple(self) -> None:
        result = build_html_generation_prompt(
            SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_strings(self) -> None:
        system, user = build_html_generation_prompt(
            SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
        )
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_system_prompt_contains_role(self) -> None:
        system, _ = build_html_generation_prompt(
            SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
        )
        assert "HTML rendering engine" in system

    def test_user_prompt_contains_markdown(self) -> None:
        _, user = build_html_generation_prompt(
            SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
        )
        assert SAMPLE_MARKDOWN in user

    def test_user_prompt_contains_template(self) -> None:
        _, user = build_html_generation_prompt(
            SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
        )
        assert SAMPLE_HTML_TEMPLATE in user

    def test_user_prompt_contains_date(self) -> None:
        _, user = build_html_generation_prompt(
            SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
        )
        assert SAMPLE_DATE in user

    def test_no_feedback_section_without_feedback(self) -> None:
        system, _ = build_html_generation_prompt(
            SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
        )
        assert "Editorial Improvement Context" not in system

    def test_feedback_section_with_feedback(self) -> None:
        system, _ = build_html_generation_prompt(
            SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
            aggregated_feedback=SAMPLE_AGGREGATED_FEEDBACK,
        )
        assert "Editorial Improvement Context" in system
        assert SAMPLE_AGGREGATED_FEEDBACK in system

    def test_feedback_section_none(self) -> None:
        system, _ = build_html_generation_prompt(
            SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
            aggregated_feedback=None,
        )
        assert "Editorial Improvement Context" not in system

    def test_feedback_section_empty_string(self) -> None:
        system, _ = build_html_generation_prompt(
            SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
            aggregated_feedback="",
        )
        assert "Editorial Improvement Context" not in system

    def test_feedback_section_whitespace_only(self) -> None:
        system, _ = build_html_generation_prompt(
            SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
            aggregated_feedback="   \n  ",
        )
        assert "Editorial Improvement Context" not in system

    def test_all_placeholders_replaced(self) -> None:
        system, user = build_html_generation_prompt(
            SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE,
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
            SAMPLE_PREVIOUS_HTML, SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE,
            SAMPLE_FEEDBACK, SAMPLE_DATE,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_strings(self) -> None:
        system, user = build_html_regeneration_prompt(
            SAMPLE_PREVIOUS_HTML, SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE,
            SAMPLE_FEEDBACK, SAMPLE_DATE,
        )
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_system_prompt_is_regeneration(self) -> None:
        system, _ = build_html_regeneration_prompt(
            SAMPLE_PREVIOUS_HTML, SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE,
            SAMPLE_FEEDBACK, SAMPLE_DATE,
        )
        assert system == HTML_REGENERATION_SYSTEM_PROMPT

    def test_user_prompt_contains_previous_html(self) -> None:
        _, user = build_html_regeneration_prompt(
            SAMPLE_PREVIOUS_HTML, SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE,
            SAMPLE_FEEDBACK, SAMPLE_DATE,
        )
        assert SAMPLE_PREVIOUS_HTML in user

    def test_user_prompt_contains_markdown(self) -> None:
        _, user = build_html_regeneration_prompt(
            SAMPLE_PREVIOUS_HTML, SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE,
            SAMPLE_FEEDBACK, SAMPLE_DATE,
        )
        assert SAMPLE_MARKDOWN in user

    def test_user_prompt_contains_template(self) -> None:
        _, user = build_html_regeneration_prompt(
            SAMPLE_PREVIOUS_HTML, SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE,
            SAMPLE_FEEDBACK, SAMPLE_DATE,
        )
        assert SAMPLE_HTML_TEMPLATE in user

    def test_user_prompt_contains_feedback(self) -> None:
        _, user = build_html_regeneration_prompt(
            SAMPLE_PREVIOUS_HTML, SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE,
            SAMPLE_FEEDBACK, SAMPLE_DATE,
        )
        assert SAMPLE_FEEDBACK in user

    def test_user_prompt_contains_date(self) -> None:
        _, user = build_html_regeneration_prompt(
            SAMPLE_PREVIOUS_HTML, SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE,
            SAMPLE_FEEDBACK, SAMPLE_DATE,
        )
        assert SAMPLE_DATE in user

    def test_all_placeholders_replaced(self) -> None:
        _, user = build_html_regeneration_prompt(
            SAMPLE_PREVIOUS_HTML, SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE,
            SAMPLE_FEEDBACK, SAMPLE_DATE,
        )
        assert "{previous_html}" not in user
        assert "{markdown_content}" not in user
        assert "{html_template}" not in user
        assert "{user_feedback}" not in user
        assert "{newsletter_date}" not in user


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestHtmlGenerationEdgeCases:
    """Edge case tests for HTML generation prompts."""

    def test_empty_markdown(self) -> None:
        _, user = build_html_generation_prompt("", SAMPLE_HTML_TEMPLATE, SAMPLE_DATE)
        assert "### Final Generated Markdown Content:" in user

    def test_empty_template(self) -> None:
        _, user = build_html_generation_prompt(SAMPLE_MARKDOWN, "", SAMPLE_DATE)
        assert "### HTML Template:" in user

    def test_empty_date(self) -> None:
        _, user = build_html_generation_prompt(SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE, "")
        assert "### Newsletter Date:" in user

    def test_unicode_in_markdown(self) -> None:
        md = "Content with arrows \u2192 and em-dashes \u2014"
        _, user = build_html_generation_prompt(md, SAMPLE_HTML_TEMPLATE, SAMPLE_DATE)
        assert md in user

    def test_html_entities_in_template(self) -> None:
        template = '<p>&amp; &lt; &gt; &quot;</p>'
        _, user = build_html_generation_prompt(SAMPLE_MARKDOWN, template, SAMPLE_DATE)
        assert template in user

    def test_regeneration_empty_feedback(self) -> None:
        _, user = build_html_regeneration_prompt(
            SAMPLE_PREVIOUS_HTML, SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE,
            "", SAMPLE_DATE,
        )
        assert "### User Feedback:" in user

    def test_very_large_html(self) -> None:
        large_html = "<div>" * 1000 + "</div>" * 1000
        _, user = build_html_regeneration_prompt(
            large_html, SAMPLE_MARKDOWN, SAMPLE_HTML_TEMPLATE,
            SAMPLE_FEEDBACK, SAMPLE_DATE,
        )
        assert large_html in user
