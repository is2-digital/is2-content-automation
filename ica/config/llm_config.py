"""LLM model configuration for ica.

Centralized model mapping for pipeline steps. Each step uses :func:`get_model`
with an :class:`LLMPurpose` to resolve the model identifier from the
corresponding JSON config file in ``ica/llm_configs/``.
"""

from __future__ import annotations

from enum import StrEnum


class LLMPurpose(StrEnum):
    """Purpose keys for LLM model selection.

    Each value maps to a JSON config process name via
    :data:`_PURPOSE_TO_PROCESS`.  Use with :func:`get_model` for typed lookups.
    """

    # Summarization
    SUMMARY = "llm_summary_model"
    SUMMARY_REGENERATION = "llm_summary_regeneration_model"
    SUMMARY_LEARNING_DATA = "llm_summary_learning_data_model"

    # Markdown generation
    MARKDOWN = "llm_markdown_model"
    MARKDOWN_VALIDATOR = "llm_markdown_validator_model"
    MARKDOWN_VOICE_VALIDATOR = "llm_markdown_voice_validator_model"
    MARKDOWN_REGENERATION = "llm_markdown_regeneration_model"
    MARKDOWN_LEARNING_DATA = "llm_markdown_learning_data_model"

    # HTML generation
    HTML = "llm_html_model"
    HTML_REGENERATION = "llm_html_regeneration_model"
    HTML_LEARNING_DATA = "llm_html_learning_data_model"

    # Theme generation
    THEME = "llm_theme_model"
    THEME_LEARNING_DATA = "llm_theme_learning_data_model"
    THEME_FRESHNESS_CHECK = "llm_theme_freshness_check_model"

    # Social media
    SOCIAL_MEDIA = "llm_social_media_model"
    SOCIAL_POST_CAPTION = "llm_social_post_caption_model"
    SOCIAL_MEDIA_REGENERATION = "llm_social_media_regeneration_model"

    # LinkedIn
    LINKEDIN = "llm_linkedin_model"
    LINKEDIN_REGENERATION = "llm_linkedin_regeneration_model"

    # Email
    EMAIL_SUBJECT = "llm_email_subject_model"
    EMAIL_SUBJECT_REGENERATION = "llm_email_subject_regeneration_model"
    EMAIL_PREVIEW = "llm_email_preview_model"

    # Article collection
    RELEVANCE_ASSESSMENT = "llm_relevance_assessment_model"


# Mapping from LLMPurpose field name to JSON config process name.
# Used by get_model() to resolve the model from the corresponding JSON file.
_PURPOSE_TO_PROCESS: dict[str, str] = {
    "llm_summary_model": "summarization",
    "llm_summary_regeneration_model": "summarization-regeneration",
    "llm_summary_learning_data_model": "learning-data-extraction",
    "llm_markdown_model": "markdown-generation",
    "llm_markdown_validator_model": "markdown-structural-validation",
    "llm_markdown_voice_validator_model": "markdown-voice-validation",
    "llm_markdown_regeneration_model": "markdown-regeneration",
    "llm_markdown_learning_data_model": "learning-data-extraction",
    "llm_html_model": "html-generation",
    "llm_html_regeneration_model": "html-regeneration",
    "llm_html_learning_data_model": "learning-data-extraction",
    "llm_theme_model": "theme-generation",
    "llm_theme_learning_data_model": "learning-data-extraction",
    "llm_theme_freshness_check_model": "freshness-check",
    "llm_social_media_model": "social-media-post",
    "llm_social_post_caption_model": "social-media-caption",
    "llm_social_media_regeneration_model": "social-media-regeneration",
    "llm_linkedin_model": "linkedin-carousel",
    "llm_linkedin_regeneration_model": "linkedin-regeneration",
    "llm_email_subject_model": "email-subject",
    "llm_email_subject_regeneration_model": "email-subject-regeneration",
    "llm_email_preview_model": "email-preview",
    "llm_relevance_assessment_model": "relevance-assessment",
}


def get_model(purpose: LLMPurpose) -> str:
    """Return the model identifier for a given pipeline purpose.

    Resolves the model from the corresponding JSON config file in
    ``ica/llm_configs/{process}-llm.json``.

    Args:
        purpose: The LLM purpose key.

    Returns:
        Model identifier string (e.g. ``"anthropic/claude-sonnet-4.5"``).

    Raises:
        ValueError: If the purpose has no JSON config mapping.
        FileNotFoundError: If the JSON config file does not exist.
    """
    process_name = _PURPOSE_TO_PROCESS.get(purpose.value)
    if process_name is None:
        msg = f"No JSON config mapping for LLMPurpose.{purpose.name}"
        raise ValueError(msg)

    from ica.llm_configs.loader import load_process_config

    return load_process_config(process_name).model
