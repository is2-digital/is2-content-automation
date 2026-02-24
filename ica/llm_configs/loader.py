"""Load and cache LLM process configuration from JSON files.

JSON config files live alongside this module in ``ica/llm_configs/`` with the
naming convention ``{processName}-llm.json``.  Configs are cached in memory and
automatically reloaded when the file's mtime changes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ica.llm_configs.schema import ProcessConfig

# Directory containing JSON config files (same directory as this module)
_CONFIG_DIR = Path(__file__).resolve().parent

# Cache: process_name -> (mtime, ProcessConfig)
_cache: dict[str, tuple[float, ProcessConfig]] = {}


def _config_path(process_name: str) -> Path:
    """Return the expected JSON file path for a process name."""
    return _CONFIG_DIR / f"{process_name}-llm.json"


def load_process_config(process_name: str) -> ProcessConfig:
    """Load and validate a process config from its JSON file.

    Results are cached and invalidated when the file's modification time
    changes.

    Args:
        process_name: The process identifier (e.g. ``"summarization"``).

    Returns:
        Validated :class:`ProcessConfig` instance.

    Raises:
        FileNotFoundError: If the JSON file does not exist.
        pydantic.ValidationError: If the JSON does not match the schema.
    """
    path = _config_path(process_name)
    mtime = path.stat().st_mtime

    cached = _cache.get(process_name)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    raw = json.loads(path.read_text(encoding="utf-8"))
    config = ProcessConfig.model_validate(raw)
    _cache[process_name] = (mtime, config)
    return config


def get_process_model(process_name: str) -> str:
    """Resolve the model identifier for a process.

    Priority (highest to lowest):

    1. **Environment variable** — ``LLM_{PROCESS_NAME}_MODEL`` (uppercased,
       hyphens replaced with underscores).
    2. **JSON config file** — the ``model`` field in
       ``{processName}-llm.json``.
    3. **Hardcoded default** — from :func:`ica.config.llm_config.get_llm_config`
       (falls through to the matching ``LLMConfig`` field if one exists).

    Args:
        process_name: The process identifier (e.g. ``"summarization"``).

    Returns:
        Model identifier string (e.g. ``"anthropic/claude-sonnet-4.5"``).

    Raises:
        FileNotFoundError: If no JSON config exists and no LLMConfig field
            matches.
    """
    # 1. Check environment variable directly
    env_key = f"LLM_{process_name.upper().replace('-', '_')}_MODEL"
    env_value = os.environ.get(env_key)
    if env_value:
        return env_value

    # 2. Try JSON config file
    path = _config_path(process_name)
    if path.exists():
        return load_process_config(process_name).model

    # 3. Fall back to hardcoded default via existing LLMConfig
    from ica.config.llm_config import get_llm_config

    llm_config = get_llm_config()
    field_name = env_key.lower()
    value: str | None = getattr(llm_config, field_name, None)
    if value is not None:
        return value

    msg = (
        f"No model configuration found for process {process_name!r}: "
        f"no env var {env_key}, no JSON config, and no LLMConfig field {field_name}"
    )
    raise FileNotFoundError(msg)


def get_process_prompts(process_name: str) -> tuple[str, str]:
    """Return the system and instruction prompts for a process.

    Args:
        process_name: The process identifier (e.g. ``"summarization"``).

    Returns:
        Tuple of ``(system_prompt, instruction_prompt)``.

    Raises:
        FileNotFoundError: If the JSON config file does not exist.
    """
    config = load_process_config(process_name)
    return config.prompts.system, config.prompts.instruction


def clear_cache() -> None:
    """Clear the in-memory config cache (useful for testing)."""
    _cache.clear()
