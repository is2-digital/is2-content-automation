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

VOICE_VALIDATION_PROMPT = """\
You are a strict newsletter voice validator. Your job is to evaluate \
the newsletter for **voice, tone, and editorial integrity**. Do NOT \
re-write content. Assume all character counts and structure have already \
been validated by another validator.

You must follow these steps:

1. Evaluate VOICE by section

**Introduction Check**:
- Opens with a striking observation or bold statement (not generic \
welcome phrases).
- Uses declarative language without hedging ("isn't", "is" not "might \
be", "could potentially").
- Includes 2-3 strategic bold terms for emphasis.
- Uses contractions naturally ("we're", "isn't", "aren't").
- Connects concrete examples to strategic insight.

**Featured Article Check**:
- States findings directly (active voice, no hedging).
- Includes specific data, numbers, or concrete examples.
- Key insight connects to business implications, not just summary.
- Uses bold 2-3 times for key concepts.
- Acknowledges complexity or nuance when present.

**Main Articles Check** (each article separately):
- Leads with finding or development directly.
- Callouts translate to strategic action or implications.
- Maintains conversational, direct tone with contractions.
- Each article has a single focused point.

**Overall Voice Check**:
- Contractions used consistently.
- Direct address to reader maintained.
- Professional authority without arrogance.
- Precision emphasized for terminology.
- Every abstract concept connects to a concrete business outcome.
- Main content uses declarative statements or evidence demonstration.
- Recommendations appear only in callout boxes, grounded in evidence.
- Generic "should" or "must" statements are avoided throughout.

2. Evaluation rules
- For each rule, evaluate mechanically:
- If satisfied, do nothing.
- If violated, add a clear, concise error message prefixed with \
VOICE:. Include textual evidence if available.
- Do NOT make subjective judgments beyond these rules.
- Only flag violations based on textual evidence and the rules above.

3. Merge previous errors:
- If a prior validator node passed its results to this node (e.g., \
counts validator), and its isValid is false, include all its errors in \
the "errors" array along with any new VOICE errors.
- Do not remove or overwrite prior errors; just append new \
VOICE-prefixed errors.

### PRIOR ERROR HANDLING (STRICT)
- All prior validator errors MUST be copied verbatim into the final \
`errors` array.
- Do NOT rewrite, summarize, deduplicate, normalize, or remove prior \
errors.
- Do NOT drop prior errors even if they are redundant or poorly \
formatted.
- New voice-related errors MUST be appended after prior errors and \
MUST be prefixed with "VOICE:".
- If no new voice errors are found, return the prior errors unchanged.


4. Output **only JSON** in this exact structure:

{{ "output": {{ "isValid": true, "errors": ["error message 1", \
"error message 2", ...] }} }}

- "isValid" must be false if any rule fails or if the previous \
validator was invalid.
- "errors" must include all prior validator errors and any new VOICE \
errors.
- Do NOT include markdown, commentary, or any text outside this JSON.
- Do NOT rewrite the newsletter.
- NEVER merge multiple errors into a single message.
- ONE violation = ONE error string.\
"""


def build_voice_validation_prompt(
    markdown_content: str,
    prior_errors_json: str,
) -> tuple[str, str]:
    """Build the system and user messages for markdown voice validation.

    The voice validator evaluates editorial tone, voice consistency, and
    writing style, then merges its VOICE-prefixed errors with prior
    validator errors.

    Args:
        markdown_content: The full markdown newsletter content to validate.
        prior_errors_json: JSON string of prior validator output
            (structural + character-count errors).  Passed through
            verbatim so the LLM can merge them.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    user_prompt = (
        f"### INPUT\n"
        f"The full newsletter content is provided below:\n"
        f"{markdown_content}\n\n\n"
        f"### PRIOR_ERRORS_JSON (AUTHORITATIVE \u2014 DO NOT MODIFY)\n"
        f"{prior_errors_json}"
    )

    return VOICE_VALIDATION_PROMPT, user_prompt
