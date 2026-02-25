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
    """Tests for the _GEN_SYSTEM constant."""

    def test_prompt_is_string(self) -> None:
        assert isinstance(_GEN_SYSTEM, str)

    def test_prompt_is_not_empty(self) -> None:
        assert len(_GEN_SYSTEM) > 0

    def test_contains_role(self) -> None:
        assert "HTML rendering engine" in _GEN_SYSTEM

    def test_contains_feedback_placeholder(self) -> None:
        assert "{feedback_section}" in _GEN_SYSTEM

    def test_contains_template_preservation_rules(self) -> None:
        assert "TEMPLATE PRESERVATION RULES" in _GEN_SYSTEM
        assert "NON-NEGOTIABLE" in _GEN_SYSTEM

    def test_contains_do_not_modify_list(self) -> None:
        rules = [
            "CSS class names",
            "Inline style attributes",
            "Table structures",
            "HTML hierarchy or nesting",
        ]
        for rule in rules:
            assert rule in _GEN_SYSTEM

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
            assert section in _GEN_SYSTEM

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
            assert cls in _GEN_SYSTEM

    def test_contains_link_requirement(self) -> None:
        assert 'target="_blank"' in _GEN_SYSTEM

    def test_contains_title_date_insertion(self) -> None:
        assert "Artificially Intelligent, Actually Useful" in _GEN_SYSTEM
        assert "nl-date" in _GEN_SYSTEM

    def test_contains_self_check(self) -> None:
        assert "FINAL SELF-CHECK" in _GEN_SYSTEM

    def test_contains_output_requirements(self) -> None:
        assert "Output only valid HTML" in _GEN_SYSTEM
        assert "Do not include explanations" in _GEN_SYSTEM

    def test_footer_rules(self) -> None:
        assert "Alright, that's a wrap for the week!" in _GEN_SYSTEM
        assert "Thoughts?" in _GEN_SYSTEM

    def test_cta_button_rules(self) -> None:
        assert "CTA button" in _GEN_SYSTEM

    def test_source_link_rules(self) -> None:
        assert "nl-source-link" in _GEN_SYSTEM

    def test_bold_emphasis_rules(self) -> None:
        assert "Preserve bold emphasis" in _GEN_SYSTEM

    def test_no_n8n_expression_syntax(self) -> None:
        assert "$json" not in _GEN_SYSTEM
        assert "$(" not in _GEN_SYSTEM


class TestHtmlGenerationUserPrompt:
    """Tests for the _GEN_INSTRUCTION constant."""

    def test_prompt_is_string(self) -> None:
        assert isinstance(_GEN_INSTRUCTION, str)

    def test_contains_markdown_placeholder(self) -> None:
        assert "{markdown_content}" in _GEN_INSTRUCTION

    def test_contains_template_placeholder(self) -> None:
        assert "{html_template}" in _GEN_INSTRUCTION

    def test_contains_date_placeholder(self) -> None:
        assert "{newsletter_date}" in _GEN_INSTRUCTION


# ---------------------------------------------------------------------------
# Regeneration prompt constant tests
# ---------------------------------------------------------------------------


class TestHtmlRegenerationSystemPrompt:
    """Tests for the _REGEN_SYSTEM constant."""

    def test_prompt_is_string(self) -> None:
        assert isinstance(_REGEN_SYSTEM, str)

    def test_contains_scoped_update_role(self) -> None:
        assert "scoped update mode" in _REGEN_SYSTEM

    def test_contains_not_full_regeneration(self) -> None:
        assert "not a full regeneration" in _REGEN_SYSTEM

    def test_contains_five_inputs(self) -> None:
        assert "Previously Generated HTML" in _REGEN_SYSTEM
        assert "Final Generated Markdown Content" in _REGEN_SYSTEM
        assert "HTML Template" in _REGEN_SYSTEM
        assert "User Feedback" in _REGEN_SYSTEM
        assert "Newsletter Date" in _REGEN_SYSTEM

    def test_contains_scope_enforcement(self) -> None:
        assert "SCOPE ENFORCEMENT" in _REGEN_SYSTEM

    def test_contains_must_rules(self) -> None:
        assert "Identify which section(s) the feedback refers to" in _REGEN_SYSTEM
        assert "Modify only those sections" in _REGEN_SYSTEM

    def test_contains_must_not_rules(self) -> None:
        assert "Re-render the entire newsletter" in _REGEN_SYSTEM
        assert "Touch sections not mentioned in feedback" in _REGEN_SYSTEM

    def test_contains_allowed_modifications(self) -> None:
        assert "Text changes" in _REGEN_SYSTEM
        assert "Link updates" in _REGEN_SYSTEM
        assert "Emphasis changes" in _REGEN_SYSTEM

    def test_contains_guarantee_clause(self) -> None:
        assert "GUARANTEE CLAUSE" in _REGEN_SYSTEM
        assert "make no modification" in _REGEN_SYSTEM

    def test_contains_output_requirements(self) -> None:
        assert "Output only valid HTML" in _REGEN_SYSTEM
        assert "Return the entire HTML document" in _REGEN_SYSTEM

    def test_contains_self_check(self) -> None:
        assert "FINAL SELF-CHECK" in _REGEN_SYSTEM

    def test_no_n8n_expression_syntax(self) -> None:
        assert "$json" not in _REGEN_SYSTEM
        assert "$(" not in _REGEN_SYSTEM


class TestHtmlRegenerationUserPrompt:
    """Tests for the _REGEN_INSTRUCTION constant."""

    def test_prompt_is_string(self) -> None:
        assert isinstance(_REGEN_INSTRUCTION, str)

    def test_contains_all_placeholders(self) -> None:
        assert "{previous_html}" in _REGEN_INSTRUCTION
        assert "{markdown_content}" in _REGEN_INSTRUCTION
        assert "{html_template}" in _REGEN_INSTRUCTION
        assert "{user_feedback}" in _REGEN_INSTRUCTION
        assert "{newsletter_date}" in _REGEN_INSTRUCTION


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

    def test_system_prompt_contains_role(self) -> None:
        system, _ = build_html_generation_prompt(
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_DATE,
        )
        assert "HTML rendering engine" in system

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

    def test_user_prompt_contains_date(self) -> None:
        _, user = build_html_generation_prompt(
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_DATE,
        )
        assert SAMPLE_DATE in user

    def test_no_feedback_section_without_feedback(self) -> None:
        system, _ = build_html_generation_prompt(
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_DATE,
        )
        assert "Editorial Improvement Context" not in system

    def test_feedback_section_with_feedback(self) -> None:
        system, _ = build_html_generation_prompt(
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_DATE,
            aggregated_feedback=SAMPLE_AGGREGATED_FEEDBACK,
        )
        assert "Editorial Improvement Context" in system
        assert SAMPLE_AGGREGATED_FEEDBACK in system

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

    def test_user_prompt_contains_markdown(self) -> None:
        _, user = build_html_regeneration_prompt(
            SAMPLE_PREVIOUS_HTML,
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_FEEDBACK,
            SAMPLE_DATE,
        )
        assert SAMPLE_MARKDOWN in user

    def test_user_prompt_contains_template(self) -> None:
        _, user = build_html_regeneration_prompt(
            SAMPLE_PREVIOUS_HTML,
            SAMPLE_MARKDOWN,
            SAMPLE_HTML_TEMPLATE,
            SAMPLE_FEEDBACK,
            SAMPLE_DATE,
        )
        assert SAMPLE_HTML_TEMPLATE in user

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
        assert "### User Feedback:" in user

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
