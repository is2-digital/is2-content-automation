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

_FEEDBACK_SECTION_TEMPLATE = """\


## Editorial Improvement Context (From Prior Feedback)
The following editorial preferences and improvement notes should guide \
your tone, structure, and theme style in this and future outputs:

{aggregated_feedback}

Use this feedback to adjust language, flow, and focus — without altering \
factual accuracy or deviating from the core standards above.
"""

EMAIL_SUBJECT_SYSTEM_PROMPT = """\
You are a professional AI research editor and content analyst. Your task is \
to process the email newsletter in text format.

Start by reviewing the newsletter text, \
based on that data create up to 10 definitive email subjects that will be \
used for this newsletter.

Follow these protocols EXACTLY:

---

## Accuracy Control Protocol (MANDATORY)
1. Do NOT search for alternative sources.
2. Make those subject relevant to the newsletter text and be trending, \
and represent the newsletter content.
3. Make subjects short and maximum is 7 words.
4. Be creative.\
"""

EMAIL_SUBJECT_USER_PROMPT = """\
{feedback_section}\


## Output Format (MANDATORY)
Return clean plain text output (no markdown or bullet points or colon) \
in this format for each created subject, do not duplicate.

Subject_[number]: [Text subject]

Put a separator string "-----" after each created subject.

As the final output, after generated subjects, create a recommendation \
to pick best subject and explain why, use in this format.

RECOMMENDATION: Subject [Put generated subject number] - \
[the subject text, generated above what you recommend to use]

---

Input:
{newsletter_text}\
"""


def build_email_subject_prompt(
    newsletter_text: str,
    aggregated_feedback: str | None = None,
) -> tuple[str, str]:
    """Build the system and user messages for the email subject LLM call.

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
    if aggregated_feedback and aggregated_feedback.strip():
        feedback_section = _FEEDBACK_SECTION_TEMPLATE.format(
            aggregated_feedback=aggregated_feedback.strip(),
        )
    else:
        feedback_section = ""

    user_prompt = EMAIL_SUBJECT_USER_PROMPT.format(
        feedback_section=feedback_section,
        newsletter_text=newsletter_text,
    )

    return EMAIL_SUBJECT_SYSTEM_PROMPT, user_prompt
