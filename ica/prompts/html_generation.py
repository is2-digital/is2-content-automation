"""HTML generation prompt templates.

Ported from the n8n "Generate HTML using LLM" and "Re-Generate Data
using LLM" nodes (``@n8n/n8n-nodes-langchain.informationExtractor``) in
``SUB/html_generator_subworkflow.json``.

The LLM populates an existing HTML newsletter template using final
generated markdown content, mapping each markdown section to its
corresponding HTML container while strictly preserving template
structure, CSS, and inline styles.

Model: ``LLM_HTML_MODEL`` / ``LLM_HTML_REGENERATION_MODEL``
(``anthropic/claude-sonnet-4.5`` via OpenRouter).
"""

from __future__ import annotations

from ica.llm_configs import get_process_prompts

_FEEDBACK_SECTION_TEMPLATE = """\


## Editorial Improvement Context (From Prior Feedback)
The following editorial preferences and improvement notes should guide \
your tone, structure, and theme style in this and future outputs:

{aggregated_feedback}

Use this feedback to adjust language, flow, and focus — without altering \
factual accuracy or deviating from the core standards above.
"""


def build_html_generation_prompt(
    markdown_content: str,
    html_template: str,
    newsletter_date: str,
    aggregated_feedback: str | None = None,
) -> tuple[str, str]:
    """Build the system and user messages for HTML generation.

    Loads the system and instruction prompts from the ``html-generation``
    JSON config via :func:`~ica.llm_configs.get_process_prompts`.

    Args:
        markdown_content: The final markdown newsletter content fetched
            from Google Docs.
        html_template: The HTML email template to populate.
        newsletter_date: The newsletter publication date string.
        aggregated_feedback: Optional aggregated editorial feedback from
            prior review cycles.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    system_prompt, instruction = get_process_prompts("html-generation")

    if aggregated_feedback and aggregated_feedback.strip():
        feedback_section = _FEEDBACK_SECTION_TEMPLATE.format(
            aggregated_feedback=aggregated_feedback.strip(),
        )
    else:
        feedback_section = ""

    system_prompt = system_prompt.format(
        feedback_section=feedback_section,
    )

    user_prompt = instruction.format(
        markdown_content=markdown_content,
        html_template=html_template,
        newsletter_date=newsletter_date,
    )

    return system_prompt, user_prompt


def build_html_regeneration_prompt(
    previous_html: str,
    markdown_content: str,
    html_template: str,
    user_feedback: str,
    newsletter_date: str,
) -> tuple[str, str]:
    """Build the system and user messages for scoped HTML regeneration.

    Loads the system and instruction prompts from the ``html-regeneration``
    JSON config via :func:`~ica.llm_configs.get_process_prompts`.

    Args:
        previous_html: The previously generated HTML document (the
            canonical document to edit).
        markdown_content: The final markdown content (reference only,
            used for wording clarification).
        html_template: The HTML template (structural reference).
        user_feedback: The user's feedback specifying which sections
            to change and how.
        newsletter_date: The newsletter publication date string.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    system_prompt, instruction = get_process_prompts("html-regeneration")

    user_prompt = instruction.format(
        previous_html=previous_html,
        markdown_content=markdown_content,
        html_template=html_template,
        user_feedback=user_feedback,
        newsletter_date=newsletter_date,
    )

    return system_prompt, user_prompt
