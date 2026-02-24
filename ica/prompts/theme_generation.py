"""Theme generation prompt template — Step 3 of the newsletter pipeline.

Ported from the n8n "Generate Data using LLM" node
(``@n8n/n8n-nodes-langchain.informationExtractor``) in
``SUB/theme_generation_subworkflow.json``.

The LLM generates two candidate newsletter themes from a JSON array of
article summaries.  Each theme assigns articles to structured slots
(Featured Article, Main Articles, Quick Hits, Industry Developments) using
``%XX_`` markers, verifies content distribution requirements (2-2-2 balance,
source mix), and ends with a recommendation for which theme to use.

Model: ``LLM_THEME_MODEL`` (``anthropic/claude-sonnet-4.5`` via OpenRouter).
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


def build_theme_generation_prompt(
    summaries_json: str,
    aggregated_feedback: str | None = None,
) -> tuple[str, str]:
    """Build the system and user messages for the theme generation LLM call.

    Loads the system and instruction prompts from the ``theme-generation``
    JSON config via :func:`~ica.llm_configs.get_process_prompts`.

    Args:
        summaries_json: JSON string of the article summaries array.  Each
            element should contain at minimum ``Title``, ``Summary``,
            ``BusinessRelevance``, and ``Order`` fields.
        aggregated_feedback: Optional bullet-point list of prior editorial
            feedback entries from the ``notes`` table
            (type ``user_newsletter_themes``, last 40 entries).  When
            provided (non-empty), the *Editorial Improvement Context*
            section is injected into the user prompt.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    system_prompt, instruction = get_process_prompts("theme-generation")

    if aggregated_feedback and aggregated_feedback.strip():
        feedback_section = _FEEDBACK_SECTION_TEMPLATE.format(
            aggregated_feedback=aggregated_feedback.strip(),
        )
    else:
        feedback_section = ""

    user_prompt = instruction.format(
        feedback_section=feedback_section,
        summaries_json=summaries_json,
    )

    return system_prompt, user_prompt
