"""Loader utilities for LLM process JSON configuration files.

Provides cached loading with file-mtime invalidation, model resolution
with env-var > JSON > default priority, and prompt retrieval.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ica.llm_configs.schema import ProcessConfig, SystemPromptConfig

logger = logging.getLogger(__name__)

# Directory containing JSON config files (same directory as this module).
_CONFIGS_DIR = Path(__file__).parent

# Cache: process_name -> (mtime, ProcessConfig)
_cache: dict[str, tuple[float, ProcessConfig]] = {}

# Cache: (mtime, SystemPromptConfig) for the shared system prompt.
_system_prompt_cache: tuple[float, SystemPromptConfig] | None = None


def _config_path(process_name: str) -> Path:
    """Return the expected JSON file path for a process name."""
    return _CONFIGS_DIR / f"{process_name}-llm.json"


def _system_prompt_path() -> Path:
    """Return the path to the shared system prompt JSON file."""
    return _CONFIGS_DIR / "system-prompt.json"


def load_system_prompt_config() -> SystemPromptConfig:
    """Load the shared system prompt config from ``system-prompt.json``.

    Results are cached and automatically invalidated when the file's
    modification time changes.

    Returns:
        Validated :class:`SystemPromptConfig` instance.

    Raises:
        FileNotFoundError: If ``system-prompt.json`` does not exist.
        ValueError: If the JSON content fails schema validation.
    """
    global _system_prompt_cache

    path = _system_prompt_path()

    if not path.exists():
        msg = f"System prompt file not found: {path}"
        raise FileNotFoundError(msg)

    mtime = path.stat().st_mtime

    if _system_prompt_cache is not None and _system_prompt_cache[0] == mtime:
        return _system_prompt_cache[1]

    raw = path.read_text(encoding="utf-8")
    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"Invalid JSON in {path}: {exc}"
        raise ValueError(msg) from exc

    try:
        config = SystemPromptConfig.model_validate(data)
    except Exception as exc:
        msg = f"Schema validation failed for {path}: {exc}"
        raise ValueError(msg) from exc

    _system_prompt_cache = (mtime, config)
    logger.debug("Loaded shared system prompt (version %d)", config.metadata.version)
    return config


def get_system_prompt() -> str:
    """Load the shared system prompt string from ``system-prompt.json``.

    Convenience wrapper around :func:`load_system_prompt_config`.

    Returns:
        The system prompt string.

    Raises:
        FileNotFoundError: If ``system-prompt.json`` does not exist.
        ValueError: If the JSON content fails schema validation.
    """
    return load_system_prompt_config().prompt


def save_system_prompt(config: SystemPromptConfig) -> None:
    """Write a SystemPromptConfig back to ``system-prompt.json``.

    Serialises the model using camelCase aliases and invalidates the
    in-memory cache so the next load reads fresh data.

    Args:
        config: The system prompt config to persist.
    """
    global _system_prompt_cache

    path = _system_prompt_path()
    data = config.model_dump(by_alias=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    _system_prompt_cache = None
    logger.debug("Saved shared system prompt (version %d)", config.metadata.version)


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
    """Return the model identifier for a process from its JSON config.

    Args:
        process_name: The process identifier (e.g. ``"summarization"``).

    Returns:
        Model identifier string in OpenRouter ``provider/model`` format.

    Raises:
        FileNotFoundError: If the JSON config file does not exist.
        ValueError: If the JSON content fails schema validation.
    """
    return load_process_config(process_name).model


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
    """Return the system and instruction prompts for a process.

    The system prompt comes from the shared ``system-prompt.json`` file,
    while the instruction prompt comes from the per-process config.

    Args:
        process_name: The process identifier (e.g. ``"summarization"``).

    Returns:
        Tuple of ``(system_prompt, instruction_prompt)`` strings.
    """
    system_prompt = get_system_prompt()
    config = load_process_config(process_name)
    return system_prompt, config.prompts.instruction
