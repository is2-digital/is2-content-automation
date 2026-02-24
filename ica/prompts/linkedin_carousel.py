"""LinkedIn carousel prompt templates — part of the LinkedIn Carousel Generator pipeline step.

Ported from the n8n ``SUB/linkedin_carousel_generator_subworkflow.json``:

- "Generate Linkedin Carousel using LLM" — initial generation of LinkedIn
  post copy (3 versions) + 10 carousel slides with character validation.
- "Re-Generate Linkedin Carousel using LLM" — feedback-driven revision
  pass that applies user edits to the previously generated content.

Model: ``LLM_LINKEDIN_MODEL`` / ``LLM_LINKEDIN_REGENERATION_MODEL``
(both ``anthropic/claude-sonnet-4.5`` via OpenRouter).
"""

from __future__ import annotations

from ica.llm_configs import get_process_prompts


def build_linkedin_carousel_prompt(
    formatted_theme: str,
    newsletter_content: str,
    previous_output: str = "",
) -> tuple[str, str]:
    """Build the system and user messages for the LinkedIn carousel LLM call.

    Loads the system and instruction prompts from the ``linkedin-carousel``
    JSON config via :func:`~ica.llm_configs.get_process_prompts`.

    Generates LinkedIn post copy (3 versions) + 10 carousel slides from
    the newsletter content and formatted theme.

    Args:
        formatted_theme: The structured theme object with article titles,
            categories, URLs, and order.
        newsletter_content: The full HTML newsletter content (from Google
            Docs).
        previous_output: Previously generated output — used in the retry
            loop when character errors exist.  Empty string on first pass.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    system_prompt, instruction = get_process_prompts("linkedin-carousel")

    user_prompt = instruction.format(
        formatted_theme=formatted_theme,
        newsletter_content=newsletter_content,
        previous_output=previous_output if previous_output else "None",
    )

    return system_prompt, user_prompt


def build_linkedin_regeneration_prompt(
    previous_output: str,
    feedback_text: str,
    formatted_theme: str,
    newsletter_content: str,
) -> tuple[str, str]:
    """Build the system and user messages for LinkedIn carousel regeneration.

    Loads the system and instruction prompts from the ``linkedin-regeneration``
    JSON config via :func:`~ica.llm_configs.get_process_prompts`.

    Revision pass that applies user feedback to previously generated
    content while preserving structure, order, and formatting.

    Args:
        previous_output: The previously generated LinkedIn carousel
            output (used as the primary source for revision).
        feedback_text: The user's free-text feedback from the Slack form.
        formatted_theme: The structured theme object (used read-only
            for validation of titles and URLs).
        newsletter_content: The full HTML newsletter content (used
            read-only for tone/factual validation).

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    system_prompt, instruction = get_process_prompts("linkedin-regeneration")

    user_prompt = instruction.format(
        previous_output=previous_output,
        feedback_text=feedback_text,
        formatted_theme=formatted_theme,
        newsletter_content=newsletter_content,
    )

    return system_prompt, user_prompt
