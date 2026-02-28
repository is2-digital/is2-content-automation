"""Markdown generation prompt template — Step 4 of the newsletter pipeline.

Ported from the n8n "Generate Markdown using LLM" node
(``@n8n/n8n-nodes-langchain.informationExtractor``) in
``SUB/markdown_generator_subworkflow.json``.

The LLM generates a complete newsletter draft in clean Markdown from a
``formatted_theme`` JSON object produced by Step 3 (Theme Generation).
The prompt encodes Kevin's 9 voice-calibration patterns, the required
8-section Markdown structure, character limits per section, CTA rules,
URL constraints, and instructions for handling validator error feedback
on regeneration attempts.

Model: ``LLM_MARKDOWN_MODEL`` (``anthropic/claude-sonnet-4.5`` via OpenRouter).
"""

from __future__ import annotations

from ica.llm_configs import get_process_prompts

_FEEDBACK_SECTION_TEMPLATE = """\


## Editorial Improvement Context (From Prior Feedback)
The following editorial preferences and improvement notes should guide \
your tone, structure, and style in this and future outputs:

{aggregated_feedback}

Use this feedback to adjust language, flow, and focus — without altering \
factual accuracy or deviating from the core standards above.
"""

# ---------------------------------------------------------------------------
# Validator errors section template (injected when errors are present)
# ---------------------------------------------------------------------------

_VALIDATOR_ERRORS_SECTION_TEMPLATE = """\


## Validator Errors (MUST BE RESOLVED)
The following validator errors were detected in the previous output. \
You MUST fix all of these errors in your regenerated output.

{validator_errors}
"""


def build_markdown_generation_prompt(
    formatted_theme: str,
    *,
    aggregated_feedback: str = "",
    previous_markdown: str = "NO_PREVIOUS_DRAFT",
    validator_errors: str = "",
) -> tuple[str, str]:
    """Build the system and user messages for the markdown generation call.

    Loads the system and instruction prompts from the ``markdown-generation``
    JSON config via :func:`~ica.llm_configs.get_process_prompts`.

    Args:
        formatted_theme: JSON string containing the formatted theme data
            produced by Step 3 (theme generation).
        aggregated_feedback: Bullet-formatted list of learning data entries
            from the ``notes`` table (type ``user_markdowngenerator``).
            Empty string when no prior feedback exists.
        previous_markdown: The previously generated newsletter markdown.
            ``"NO_PREVIOUS_DRAFT"`` on the first generation attempt;
            populated on validator-driven regeneration attempts.
        validator_errors: JSON-formatted validator errors from the
            character-count, structural, and voice validators. Empty string
            on the first generation attempt.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    system_prompt, instruction = get_process_prompts("markdown-generation")

    feedback_section = (
        _FEEDBACK_SECTION_TEMPLATE.format(aggregated_feedback=aggregated_feedback)
        if aggregated_feedback
        else ""
    )

    validator_errors_section = (
        _VALIDATOR_ERRORS_SECTION_TEMPLATE.format(validator_errors=validator_errors)
        if validator_errors
        else ""
    )

    user_prompt = instruction.format(
        feedback_section=feedback_section,
        validator_errors_section=validator_errors_section,
        formatted_theme=formatted_theme,
        previous_markdown=previous_markdown or "NO_PREVIOUS_DRAFT",
    )

    return system_prompt, user_prompt


def build_markdown_regeneration_prompt(
    original_markdown: str,
    user_feedback: str,
) -> tuple[str, str]:
    """Build the system and user messages for user-feedback regeneration.

    Loads the system and instruction prompts from the
    ``markdown-regeneration`` JSON config via
    :func:`~ica.llm_configs.get_process_prompts`.

    Used when a human reviewer provides feedback on the generated markdown
    via the Slack feedback form and the LLM must revise the content.

    Args:
        original_markdown: The previously generated newsletter markdown
            that the user reviewed.
        user_feedback: The reviewer's free-text feedback describing what
            should be changed.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple. The regeneration prompt
        is self-contained in the system message; the user message is the
        feedback text itself (for consistency with the LLM call pattern).
    """
    system_prompt, instruction = get_process_prompts("markdown-regeneration")

    user_prompt = instruction.format(
        original_markdown=original_markdown,
        user_feedback=user_feedback,
    )

    return system_prompt, user_prompt
