"""LLM model configuration for ica.

Centralized model mapping ported from the n8n llm_global_config_utility.json
workflow. Each pipeline step reads this config to get model names dynamically,
allowing model changes in one place.

Every field can be overridden via an environment variable of the same name
(e.g. ``LLM_SUMMARY_MODEL=openai/gpt-4.1``).
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMPurpose(StrEnum):
    """Purpose keys for LLM model selection.

    Each value corresponds to the field name on :class:`LLMConfig`.
    Use with :func:`get_model` for typed lookups.
    """

    # Summarization
    SUMMARY = "llm_summary_model"
    SUMMARY_REGENERATION = "llm_summary_regeneration_model"
    SUMMARY_LEARNING_DATA = "llm_summary_learning_data_model"

    # Markdown generation
    MARKDOWN = "llm_markdown_model"
    MARKDOWN_VALIDATOR = "llm_markdown_validator_model"
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


# Default model identifiers (OpenRouter format)
_CLAUDE_SONNET = "anthropic/claude-sonnet-4.5"
_GPT_4_1 = "openai/gpt-4.1"
_GEMINI_FLASH = "google/gemini-2.5-flash"


class LLMConfig(BaseSettings):
    """LLM model mappings loaded from environment variables.

    Defaults match the n8n ``llm_global_config_utility.json`` source workflow.
    Override any field via its corresponding environment variable.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Summarization ---
    llm_summary_model: str = _CLAUDE_SONNET
    llm_summary_regeneration_model: str = _CLAUDE_SONNET
    llm_summary_learning_data_model: str = _CLAUDE_SONNET

    # --- Markdown generation ---
    llm_markdown_model: str = _CLAUDE_SONNET
    llm_markdown_validator_model: str = _GPT_4_1
    llm_markdown_regeneration_model: str = _CLAUDE_SONNET
    llm_markdown_learning_data_model: str = _CLAUDE_SONNET

    # --- HTML generation ---
    llm_html_model: str = _CLAUDE_SONNET
    llm_html_regeneration_model: str = _CLAUDE_SONNET
    llm_html_learning_data_model: str = _CLAUDE_SONNET

    # --- Theme generation ---
    llm_theme_model: str = _CLAUDE_SONNET
    llm_theme_learning_data_model: str = _CLAUDE_SONNET
    llm_theme_freshness_check_model: str = _GEMINI_FLASH

    # --- Social media ---
    llm_social_media_model: str = _CLAUDE_SONNET
    llm_social_post_caption_model: str = _CLAUDE_SONNET
    llm_social_media_regeneration_model: str = _CLAUDE_SONNET

    # --- LinkedIn ---
    llm_linkedin_model: str = _CLAUDE_SONNET
    llm_linkedin_regeneration_model: str = _CLAUDE_SONNET

    # --- Email ---
    llm_email_subject_model: str = _CLAUDE_SONNET
    llm_email_subject_regeneration_model: str = _CLAUDE_SONNET
    llm_email_preview_model: str = _CLAUDE_SONNET


@lru_cache(maxsize=1)
def get_llm_config() -> LLMConfig:
    """Return a cached LLMConfig instance.

    Use this as a FastAPI dependency or call directly. The instance
    is created once and reused for the lifetime of the process.
    """
    return LLMConfig()


def get_model(purpose: LLMPurpose) -> str:
    """Return the model identifier for a given pipeline purpose.

    Args:
        purpose: The LLM purpose key.

    Returns:
        Model identifier string (e.g. ``"anthropic/claude-sonnet-4.5"``).
    """
    config = get_llm_config()
    return getattr(config, purpose.value)
