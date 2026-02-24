"""Markdown voice validation prompt template.

Ported from the n8n "Markdown Voice Validator" node
(``@n8n/n8n-nodes-langchain.informationExtractor``) in
``SUB/markdown_generator_subworkflow.json``.

The LLM evaluates voice, tone, and editorial integrity by section —
introduction, featured article, main articles, and overall — then merges
any VOICE-prefixed errors with prior validator errors into a single JSON
result.

Model: ``LLM_MARKDOWN_VALIDATION_MODEL`` (``openai/gpt-4.1`` via
OpenRouter).
"""

from __future__ import annotations

from ica.llm_configs import get_process_prompts


def build_voice_validation_prompt(
    markdown_content: str,
    prior_errors_json: str,
) -> tuple[str, str]:
    """Build the system and user messages for markdown voice validation.

    Loads the system and instruction prompts from the
    ``markdown-voice-validation`` JSON config via
    :func:`~ica.llm_configs.get_process_prompts`.

    Args:
        markdown_content: The full markdown newsletter content to validate.
        prior_errors_json: JSON string of prior validator output
            (structural + character-count errors).  Passed through
            verbatim so the LLM can merge them.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    system_prompt, instruction = get_process_prompts("markdown-voice-validation")

    user_prompt = instruction.format(
        markdown_content=markdown_content,
        prior_errors_json=prior_errors_json,
    )

    return system_prompt, user_prompt
