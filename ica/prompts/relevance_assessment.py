"""Relevance assessment prompt template.

Evaluates whether a search result article is a good fit for the IS2
newsletter audience (solopreneurs and SMB professionals interested in
AI for business).

Model: ``LLM_RELEVANCE_ASSESSMENT_MODEL`` (``google/gemini-2.5-flash`` via
OpenRouter).
"""

from __future__ import annotations

from ica.llm_configs import get_process_prompts


def build_relevance_prompt(
    title: str,
    excerpt: str,
) -> tuple[str, str]:
    """Build the system and user messages for relevance assessment.

    Loads the system and instruction prompts from the ``relevance-assessment``
    JSON config via :func:`~ica.llm_configs.get_process_prompts`.

    Args:
        title: The article title from the search result.
        excerpt: The article excerpt/description snippet from the search result.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    system_prompt, instruction = get_process_prompts("relevance-assessment")

    user_prompt = instruction.format(
        title=title,
        excerpt=excerpt,
    )

    return system_prompt, user_prompt
