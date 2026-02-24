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

from ica.llm_configs import get_process_prompts


def build_learning_data_extraction_prompt(
    feedback: str,
    input_text: str,
    model_output: str,
) -> tuple[str, str]:
    """Build the system and user messages for learning data extraction.

    Loads the system and instruction prompts from the
    ``learning-data-extraction`` JSON config via
    :func:`~ica.llm_configs.get_process_prompts`.

    Args:
        feedback: The user's free-text feedback from the Slack form.
        input_text: The original input provided to the LLM (e.g. the
            formatted article content or theme data).
        model_output: The LLM-generated output that the user is
            providing feedback on.

    Returns:
        A ``(system_prompt, user_prompt)`` tuple ready to pass to the LLM.
    """
    system_prompt, instruction = get_process_prompts("learning-data-extraction")

    user_prompt = instruction.format(
        feedback=feedback,
        input_text=input_text,
        model_output=model_output,
    )

    return system_prompt, user_prompt
