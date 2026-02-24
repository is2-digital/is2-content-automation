"""Markdown structural validation prompt template.

Ported from the n8n "Markdown Validator" node
(``@n8n/n8n-nodes-langchain.informationExtractor``) in
``SUB/markdown_generator_subworkflow.json``.

The LLM validates non-numeric structural rules (bullet counts, link
formatting, section ordering, etc.) and merges its findings with
pre-computed character-count errors into a single JSON result.

Model: ``LLM_MARKDOWN_VALIDATION_MODEL`` (``openai/gpt-4.1`` via
OpenRouter).
"""

from __future__ import annotations

from ica.llm_configs import get_process_prompts


def build_structural_validation_prompt(
    markdown_content: str,
    char_errors: str,
) -> tuple[str, str]:
    """Build the system and user messages for markdown structural validation.

    Loads the system and instruction prompts from the
    ``markdown-structural-validation`` JSON config via
    :func:`~ica.llm_configs.get_process_prompts`.

    Args:
        markdown_content: The full markdown newsletter content to validate.
        char_errors: JSON string of character-count errors computed
            upstream.  Passed through verbatim to the LLM.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    system_prompt, instruction = get_process_prompts("markdown-structural-validation")

    system_prompt = system_prompt.format(
        char_errors=char_errors,
    )

    user_prompt = instruction.format(
        markdown_content=markdown_content,
    )

    return system_prompt, user_prompt
