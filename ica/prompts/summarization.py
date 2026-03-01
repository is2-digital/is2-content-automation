"""Summarization prompt templates — Step 2 of the newsletter pipeline.

Contains two prompt sets:

1. **Initial summarization** — ported from the n8n "Generate Data using LLM"
   node in ``SUB/summarization_subworkflow.json``.  Processes a single article
   into a structured summary with business relevance commentary.

2. **Regeneration** — ported from the n8n "Re-Generate Data using LLM" node
   in the same subworkflow.  Revises a previous summary based on user feedback
   while maintaining the original formatting and accuracy protocols.
"""

from __future__ import annotations

from ica.llm_configs import get_process_prompts

_FEEDBACK_SECTION_TEMPLATE = """\

## Editorial Improvement Context (From Prior Feedback)
The following editorial preferences and improvement notes should guide \
your tone, structure, and summarization style in this and future outputs:

{aggregated_feedback}

Use this feedback to adjust language, flow, and focus — without altering \
factual accuracy or deviating from the core standards above.
"""


def build_summarization_prompt(
    article_content: str,
    aggregated_feedback: str | None = None,
) -> tuple[str, str]:
    """Build the system and user messages for the summarization LLM call.

    Loads the system and instruction prompts from the ``summarization``
    JSON config via :func:`~ica.llm_configs.get_process_prompts`.

    Args:
        article_content: The article body to summarize.  Typically a
            concatenation of URL, title, and page text.
        aggregated_feedback: Optional bullet-point list of prior feedback
            entries.  When provided (non-empty), the *Editorial Improvement
            Context* section is injected into the user prompt.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    system_prompt, instruction = get_process_prompts("summarization")

    if aggregated_feedback and aggregated_feedback.strip():
        feedback_section = _FEEDBACK_SECTION_TEMPLATE.format(
            aggregated_feedback=aggregated_feedback.strip(),
        )
    else:
        feedback_section = ""

    user_prompt = instruction.format(
        feedback_section=feedback_section,
        article_content=article_content,
    )

    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Regeneration prompt (feedback loop)
# ---------------------------------------------------------------------------


def build_summarization_regeneration_prompt(
    original_content: str,
    user_feedback: str,
) -> tuple[str, str]:
    """Build the system and user messages for the summarization regeneration call.

    Loads the system and instruction prompts from the
    ``summarization-regeneration`` JSON config via
    :func:`~ica.llm_configs.get_process_prompts`.

    Used when a human reviewer provides feedback on a generated summary and
    the LLM must revise the content accordingly.

    Args:
        original_content: The previously generated summary text (the output
            from the initial summarization call).
        user_feedback: The reviewer's free-text feedback describing what
            should be changed.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    system_prompt, instruction = get_process_prompts("summarization-regeneration")

    user_prompt = instruction.format(
        original_content=original_content,
        user_feedback=user_feedback,
    )

    return system_prompt, user_prompt
