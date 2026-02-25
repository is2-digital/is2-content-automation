"""Loader utilities for LLM process JSON configuration files.

Provides cached loading with file-mtime invalidation, model resolution
with env-var > JSON > default priority, and prompt retrieval.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ica.llm_configs.schema import ProcessConfig

logger = logging.getLogger(__name__)

# Directory containing JSON config files (same directory as this module).
_CONFIGS_DIR = Path(__file__).parent

# Cache: process_name -> (mtime, ProcessConfig)
_cache: dict[str, tuple[float, ProcessConfig]] = {}


def _config_path(process_name: str) -> Path:
    """Return the expected JSON file path for a process name."""
    return _CONFIGS_DIR / f"{process_name}-llm.json"


def load_process_config(process_name: str) -> ProcessConfig:
    """Load and validate a process configuration from JSON.

    Results are cached and automatically invalidated when the file's
    modification time changes.

    Args:
        process_name: The process identifier (e.g. ``"summarization"``).
            Maps to ``{process_name}-llm.json`` in the configs directory.

    Returns:
        Validated :class:`ProcessConfig` instance.

    Raises:
        FileNotFoundError: If the JSON file does not exist.
        ValueError: If the JSON content fails schema validation.
    """
    path = _config_path(process_name)

    if not path.exists():
        msg = f"Config file not found: {path}"
        raise FileNotFoundError(msg)

    mtime = path.stat().st_mtime

    cached = _cache.get(process_name)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    raw = path.read_text(encoding="utf-8")
    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"Invalid JSON in {path}: {exc}"
        raise ValueError(msg) from exc

    try:
        config = ProcessConfig.model_validate(data)
    except Exception as exc:
        msg = f"Schema validation failed for {path}: {exc}"
        raise ValueError(msg) from exc

    _cache[process_name] = (mtime, config)
    logger.debug("Loaded config for %s (version %d)", process_name, config.metadata.version)
    return config


def get_process_model(process_name: str) -> str:
    """Resolve the model identifier for a process.

    Priority (highest to lowest):

    1. Environment variable via existing ``LLMConfig`` (e.g. ``LLM_SUMMARY_MODEL``)
    2. ``model`` field in the JSON config file
    3. Hardcoded default in ``LLMConfig``

    This function checks whether the env-var-loaded value differs from the
    hardcoded default. If it does, the env var takes precedence. Otherwise
    the JSON config value is used.

    Args:
        process_name: The process identifier (e.g. ``"summarization"``).

    Returns:
        Model identifier string in OpenRouter ``provider/model`` format.
    """
    from ica.config.llm_config import LLMConfig, get_llm_config

    config = load_process_config(process_name)

    # Find the matching LLMConfig field name for this process.
    # Convention: processName "summarization" -> field "llm_summary_model", etc.
    # We match by checking if the JSON model differs from the LLMConfig value.
    # If the env-loaded LLMConfig value differs from the class default,
    # an env var override is active and takes priority.
    llm_cfg = get_llm_config()

    # Try to find the LLMConfig field that corresponds to this process.
    # The JSON "model" field holds the default for this process.
    # We need to check if any env var overrides it.
    field_name = _resolve_llm_config_field(process_name)
    if field_name is not None:
        env_value: str = getattr(llm_cfg, field_name)
        class_default = LLMConfig.model_fields[field_name].default
        if env_value != class_default:
            # Env var override is active — it takes priority.
            return env_value

    return config.model


# Mapping from process name to LLMConfig field name.
# Populated lazily to avoid import-time coupling issues.
_PROCESS_TO_FIELD: dict[str, str] | None = None


def _resolve_llm_config_field(process_name: str) -> str | None:
    """Map a process name to its corresponding LLMConfig field name.

    Returns ``None`` if no mapping exists (e.g. the process has no
    matching ``LLMPurpose`` entry).
    """
    global _PROCESS_TO_FIELD
    if _PROCESS_TO_FIELD is None:
        _PROCESS_TO_FIELD = _build_process_field_mapping()
    return _PROCESS_TO_FIELD.get(process_name)


def _build_process_field_mapping() -> dict[str, str]:
    """Build mapping from JSON process names to LLMConfig field names.

    The JSON ``processName`` values use kebab-case (e.g. ``"email-subject"``)
    while ``LLMConfig`` fields use snake_case with ``llm_`` prefix and
    ``_model`` suffix (e.g. ``"llm_email_subject_model"``).
    """
    return {
        "summarization": "llm_summary_model",
        "summarization-regeneration": "llm_summary_regeneration_model",
        "summarization-learning-data": "llm_summary_learning_data_model",
        "theme-generation": "llm_theme_model",
        "theme-learning-data": "llm_theme_learning_data_model",
        "freshness-check": "llm_theme_freshness_check_model",
        "markdown-generation": "llm_markdown_model",
        "markdown-regeneration": "llm_markdown_regeneration_model",
        "markdown-learning-data": "llm_markdown_learning_data_model",
        "markdown-structural-validation": "llm_markdown_validator_model",
        "markdown-voice-validation": "llm_markdown_validator_model",
        "html-generation": "llm_html_model",
        "html-regeneration": "llm_html_regeneration_model",
        "html-learning-data": "llm_html_learning_data_model",
        "email-subject": "llm_email_subject_model",
        "email-subject-regeneration": "llm_email_subject_regeneration_model",
        "email-preview": "llm_email_preview_model",
        "social-media-post": "llm_social_media_model",
        "social-media-caption": "llm_social_post_caption_model",
        "social-media-regeneration": "llm_social_media_regeneration_model",
        "linkedin-carousel": "llm_linkedin_model",
        "linkedin-regeneration": "llm_linkedin_regeneration_model",
        "learning-data-extraction": "llm_summary_learning_data_model",
    }


def save_process_config(process_name: str, config: ProcessConfig) -> None:
    """Write a ProcessConfig back to its JSON file.

    Serialises the model using camelCase aliases and invalidates the
    in-memory cache so the next :func:`load_process_config` call reads
    fresh data.

    Args:
        process_name: The process identifier (e.g. ``"summarization"``).
        config: The config to persist.
    """
    path = _config_path(process_name)
    data = config.model_dump(by_alias=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    _cache.pop(process_name, None)
    logger.debug("Saved config for %s (version %d)", process_name, config.metadata.version)


def get_process_prompts(process_name: str) -> tuple[str, str]:
    """Return the system and instruction prompts from a process config.

    Args:
        process_name: The process identifier (e.g. ``"summarization"``).

    Returns:
        Tuple of ``(system_prompt, instruction_prompt)`` strings.
    """
    config = load_process_config(process_name)
    return config.prompts.system, config.prompts.instruction
