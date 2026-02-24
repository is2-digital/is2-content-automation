"""Email review prompt template — part of the Email Subject & Preview pipeline step.

Ported from the n8n "Review data extractor - Review" node
(``@n8n/n8n-nodes-langchain.informationExtractor``) in
``SUB/email_subject_and_preview_subworkflow.json``.

The LLM generates a concise (100-120 word) email introduction/review that
complements the newsletter content.  It focuses on subscriber relationship
building rather than content preview, following a detailed strategic guide.

Model: ``LLM_EMAIL_PREVIEW_MODEL`` (``anthropic/claude-sonnet-4.5`` via
OpenRouter).
"""

from __future__ import annotations

from ica.llm_configs import get_process_prompts

_FEEDBACK_SECTION_TEMPLATE = """\


## Editorial Improvement Context (From Prior Feedback)
The following editorial preferences and improvement notes should guide \
your tone, structure, and theme style in this and future outputs:

{user_review_feedback}

Use this feedback to adjust language, flow, and focus — without altering \
factual accuracy or deviating from the core standards above.
"""


def build_email_review_prompt(
    newsletter_text: str,
    user_review_feedback: str | None = None,
) -> tuple[str, str]:
    """Build the system and user messages for the email review LLM call.

    Loads the system and instruction prompts from the ``email-preview``
    JSON config via :func:`~ica.llm_configs.get_process_prompts`.

    This generates a 100-120 word email introduction that focuses on
    subscriber relationship building rather than content preview.

    Args:
        newsletter_text: The full newsletter content in plain text
            (HTML stripped).  Typically fetched from a Google Doc.
        user_review_feedback: Optional editorial feedback from a prior
            review cycle.  When provided, it is injected into the user
            prompt so the LLM can incorporate the feedback.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    system_prompt, instruction = get_process_prompts("email-preview")

    if user_review_feedback and user_review_feedback.strip():
        feedback_section = _FEEDBACK_SECTION_TEMPLATE.format(
            user_review_feedback=user_review_feedback.strip(),
        )
    else:
        feedback_section = ""

    user_prompt = instruction.format(
        feedback_section=feedback_section,
        newsletter_text=newsletter_text,
    )

    return system_prompt, user_prompt
