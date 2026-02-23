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

STRUCTURAL_VALIDATION_PROMPT = """\
You are a strict newsletter validator.

IMPORTANT (NON-NEGOTIABLE):
- ALL character length validation has already been computed upstream.
- You MUST NOT re-count characters or recalculate deltas.
- You MUST treat provided character errors as authoritative and final.

Your role is to:
1. Accept provided character errors exactly as-is
2. Validate all remaining non-numeric rules
3. Merge both into a single errors array

PROVIDED CHARACTER ERRORS (DO NOT MODIFY):
{char_errors}

YOUR VALIDATION SCOPE (NON-NUMERIC RULES ONLY):

QUICK HIGHLIGHTS:
- Exactly 3 bullets
- Order: Featured -> Main 1 -> Main 2
- Each starts with data point or factual claim
- Each contains at least one bolded key term

FEATURED ARTICLE:
- Headline must be clickable Markdown link
- Paragraphs must be separate
- Key Insight starts with bolded two-word label
- CTA on own line, 2-4 words, ends with arrow, no trailing punctuation

MAIN ARTICLES (1 & 2):
- One content paragraph + one callout paragraph
- Callout label: "Strategic Take-away" or "Actionable Steps"
- Clickable headline + source link

INDUSTRY DEVELOPMENTS:
- Exactly 2 items, single paragraph each
- Clickable link headlines, no arrows
- At least one major AI player (OpenAI, Google, Microsoft, Meta, Anthropic, Amazon)

FOOTER:
- Line 1: "Alright, that's a wrap for the week!"
- Final line: "Thoughts?"

OUTPUT: {{ "output": {{ "isValid": boolean, "errors": [] }} }}\
"""


def build_structural_validation_prompt(
    markdown_content: str,
    char_errors: str,
) -> tuple[str, str]:
    """Build the system and user messages for markdown structural validation.

    The structural validator checks non-numeric rules (bullet counts,
    link formatting, section structure) and merges its findings with
    upstream character-count errors.

    Args:
        markdown_content: The full markdown newsletter content to validate.
        char_errors: JSON string of character-count errors computed
            upstream.  Passed through verbatim to the LLM.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    system_prompt = STRUCTURAL_VALIDATION_PROMPT.format(
        char_errors=char_errors,
    )

    user_prompt = markdown_content

    return system_prompt, user_prompt
