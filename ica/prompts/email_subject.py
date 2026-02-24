"""Email subject generation prompt template — part of the Email Subject & Preview pipeline step.

Ported from the n8n "Generate Data using LLM" node
(``@n8n/n8n-nodes-langchain.informationExtractor``) in
``SUB/email_subject_and_preview_subworkflow.json``.

The LLM generates up to 10 email subject lines (max 7 words each) from
the newsletter text, with a recommendation for the best choice.

Model: ``LLM_EMAIL_SUBJECT_MODEL`` (``anthropic/claude-sonnet-4.5`` via
OpenRouter).
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


def build_email_subject_prompt(
    newsletter_text: str,
    aggregated_feedback: str | None = None,
) -> tuple[str, str]:
    """Build the system and user messages for the email subject LLM call.

    Loads the system and instruction prompts from the ``email-subject``
    JSON config via :func:`~ica.llm_configs.get_process_prompts`.

    This generates up to 10 email subject lines (max 7 words each)
    with a recommendation for the best choice.

    Args:
        newsletter_text: The full newsletter content in plain text
            (HTML stripped).
        aggregated_feedback: Optional aggregated editorial feedback from
            prior review cycles (bullet-pointed list).  When provided,
            it is injected into the user prompt so the LLM can
            incorporate the feedback.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    system_prompt, instruction = get_process_prompts("email-subject")

    if aggregated_feedback and aggregated_feedback.strip():
        feedback_section = _FEEDBACK_SECTION_TEMPLATE.format(
            aggregated_feedback=aggregated_feedback.strip(),
        )
    else:
        feedback_section = ""

    user_prompt = instruction.format(
        feedback_section=feedback_section,
        newsletter_text=newsletter_text,
    )

    return system_prompt, user_prompt
