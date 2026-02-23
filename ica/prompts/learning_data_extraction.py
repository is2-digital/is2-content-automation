"""Learning data extraction prompt template — shared across all subworkflows.

Ported from the n8n "Learning data extractor" node
(``@n8n/n8n-nodes-langchain.informationExtractor``) found in multiple
subworkflows:

- ``SUB/summarization_subworkflow.json``
- ``SUB/markdown_generator_subworkflow.json``
- ``SUB/html_generator_subworkflow.json``

The LLM converts raw user feedback into a concise, structured summary
(2-3 sentences) that is stored as learning data for future content
improvement.

Model: varies per step — ``LLM_SUMMARY_LEARNING_DATA_MODEL``,
``LLM_MARKDOWN_LEARNING_DATA_MODEL``, ``LLM_HTML_LEARNING_DATA_MODEL``
(all ``anthropic/claude-sonnet-4.5`` via OpenRouter).
"""

from __future__ import annotations

LEARNING_DATA_EXTRACTION_PROMPT = """\
You are an AI assistant that converts raw user feedback into a short, \
structured summary that can be stored as learning data for future \
content improvement.

You will be given:
- The original *input text* (the content or article summary prompt),
- The *model output* that was generated,
- The *user's feedback*.

Your goal:
1. Summarize the key points of the user's feedback into clear, \
actionable insights.
2. Keep the summary short (2-3 sentences max).
3. Focus on what should be improved next time (e.g., tone, accuracy, \
length, structure, detail).
4. If feedback is unclear or generic (like "good" or "bad"), infer \
the likely intent from the input and output context.

---

### Feedback Data
**User Feedback:**
{feedback}

**Input Provided:**
{input_text}

**Model Output:**
{model_output}

---

### Expected Output
Return only a concise structured learning note in JSON format like this:

{{ "learning_feedback": "Future responses should provide shorter, more \
focused summaries emphasizing factual accuracy and concise language." }}\
"""


def build_learning_data_extraction_prompt(
    feedback: str,
    input_text: str,
    model_output: str,
) -> tuple[str, str]:
    """Build the system and user messages for learning data extraction.

    This prompt converts raw user feedback into a concise learning note
    that gets stored in a feedback table for future LLM prompt injection.

    Args:
        feedback: The user's free-text feedback from the Slack form.
        input_text: The original input provided to the LLM (e.g. the
            formatted article content or theme data).
        model_output: The LLM-generated output that the user is
            providing feedback on.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
        The system prompt is a brief role description; the user prompt
        contains the full extraction instructions with interpolated data.
    """
    system_prompt = (
        "You are an AI assistant that converts raw user feedback into "
        "a short, structured summary that can be stored as learning "
        "data for future content improvement."
    )

    user_prompt = LEARNING_DATA_EXTRACTION_PROMPT.format(
        feedback=feedback,
        input_text=input_text,
        model_output=model_output,
    )

    return system_prompt, user_prompt
