"""Summarization prompt template — Step 2 of the newsletter pipeline.

Ported from the n8n "Generate Data using LLM" node in
``SUB/summarization_subworkflow.json``. This prompt processes a single article
(HTML, Markdown, or plain text) into a structured summary with business
relevance commentary.

Variables
---------
article_content : str
    The article text to summarize (URL + title + body, may be HTML/MD/text).
aggregated_feedback : str | None
    Bullet-point list of prior editorial feedback from the
    ``summarization_user_feedback`` table (last 40 entries). Pass ``None``
    or an empty string to omit the feedback section.
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
