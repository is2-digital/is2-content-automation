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

_FEEDBACK_SECTION_TEMPLATE = """\

## Editorial Improvement Context (From Prior Feedback)
The following editorial preferences and improvement notes should guide \
your tone, structure, and summarization style in this and future outputs:

{aggregated_feedback}

Use this feedback to adjust language, flow, and focus — without altering \
factual accuracy or deviating from the core standards above.
"""

SUMMARIZATION_SYSTEM_PROMPT = """\
You are a professional AI research editor and content analyst. Your task is \
to process news or blog articles that may be provided in HTML, Markdown, or \
plain text format according to strict editorial and data integrity standards.

Follow these protocols EXACTLY:

## Accuracy Control Protocol (MANDATORY)
1. Do NOT search for alternative sources.
2. Do NOT summarize partial or unavailable content.
3. Do NOT generate or infer missing details.

## Article Summary Standards
Summary Specifications:
- 3-4 sentences per article
- Focus strictly on factual content, key findings, and main conclusions
- Avoid editorial opinions or speculative tone
- Include specific statistics, methodologies, or technical details when mentioned

Business Relevance Specifications:
- 2-3 sentences per article
- Explain the broad business or strategic relevance across industries
- Consider an audience of solopreneurs and SMB professionals (without naming them)
- Emphasize practical implications for decision-making, operations, or strategy
- Avoid technical or industry-specific jargon

## Data Integrity Standards
- Extract only verified information directly from the article
- Quote or cite exact statistics or claims when possible
- Flag unverifiable data explicitly (e.g., "Statistic requires verification")
- Do NOT fabricate, infer, or supplement from external knowledge
- Well-established general knowledge does NOT require verification\
"""

SUMMARIZATION_USER_PROMPT = """\
{feedback_section}\

## Output Format (MANDATORY)
Return clean plain text output (no markdown or bullet points) in this format:

URL: [article URL]
Title: [article title]
Summary: [3-4 sentence factual summary following Article Summary Standards]
Business Relevance: [2-3 sentence business relevance commentary following \
the same standards]

Now process the following content accordingly. The input may be HTML, \
Markdown, or plain text — automatically detect the format. If the content \
cannot be fully accessed, follow the Accuracy Control Protocol.

Keep the output format consistent as plain text and not JSON object.

Input:
{article_content}\
"""


def build_summarization_prompt(
    article_content: str,
    aggregated_feedback: str | None = None,
) -> tuple[str, str]:
    """Build the system and user messages for the summarization LLM call.

    Args:
        article_content: The article body to summarize.  Typically a
            concatenation of URL, title, and page text.
        aggregated_feedback: Optional bullet-point list of prior feedback
            entries.  When provided (non-empty), the *Editorial Improvement
            Context* section is injected into the user prompt.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    if aggregated_feedback and aggregated_feedback.strip():
        feedback_section = _FEEDBACK_SECTION_TEMPLATE.format(
            aggregated_feedback=aggregated_feedback.strip(),
        )
    else:
        feedback_section = ""

    user_prompt = SUMMARIZATION_USER_PROMPT.format(
        feedback_section=feedback_section,
        article_content=article_content,
    )

    return SUMMARIZATION_SYSTEM_PROMPT, user_prompt


# ---------------------------------------------------------------------------
# Regeneration prompt (feedback loop)
# ---------------------------------------------------------------------------

REGENERATION_SYSTEM_PROMPT = """\
You are a professional content editor AI.

Please revise the content to incorporate the feedback. Maintain the \
formatting of the original content.

Maintain these protocols EXACTLY:

## Accuracy Control Protocol (MANDATORY)
1. Do NOT search for alternative sources.
2. Do NOT summarize partial or unavailable content.
3. Do NOT generate or infer missing details.
4. Incorporate ONLY the requested feedback. Do NOT rewrite, expand, or \
regenerate other sections unless the feedback directly requires it.

## Article Summary Standards
Summary Specifications:
- 3-4 sentences per article
- Focus strictly on factual content, key findings, and main conclusions
- Avoid editorial opinions or speculative tone
- Include specific statistics, methodologies, or technical details when mentioned

Business Relevance Specifications:
- 2-3 sentences per article
- Explain the broad business or strategic relevance across industries
- Consider an audience of solopreneurs and SMB professionals (without naming them)
- Emphasize practical implications for decision-making, operations, or strategy
- Avoid technical or industry-specific jargon

## Data Integrity Standards
- Extract only verified information directly from the article
- Quote or cite exact statistics or claims when possible
- Flag unverifiable data explicitly (e.g., "Statistic requires verification")
- Do NOT fabricate, infer, or supplement from external knowledge
- Well-established general knowledge does NOT require verification\
"""

REGENERATION_USER_PROMPT = """\
The original content is below:
{original_content}

The user has provided feedback as follows:
{user_feedback}\
"""


def build_summarization_regeneration_prompt(
    original_content: str,
    user_feedback: str,
) -> tuple[str, str]:
    """Build the system and user messages for the summarization regeneration call.

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
    user_prompt = REGENERATION_USER_PROMPT.format(
        original_content=original_content,
        user_feedback=user_feedback,
    )

    return REGENERATION_SYSTEM_PROMPT, user_prompt
