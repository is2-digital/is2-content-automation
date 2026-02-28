"""LLM process configuration package.

Provides Pydantic models and loading utilities for per-process JSON config
files that externalize model selection and prompt content.
"""

from ica.llm_configs.loader import (
    get_process_model,
    get_process_prompts,
    get_system_prompt,
    load_process_config,
)
from ica.llm_configs.schema import (
    Metadata,
    ProcessConfig,
    Prompts,
    SystemPromptConfig,
    SystemPromptMetadata,
)

__all__ = [
    "Metadata",
    "ProcessConfig",
    "Prompts",
    "SystemPromptConfig",
    "SystemPromptMetadata",
    "get_process_model",
    "get_process_prompts",
    "get_system_prompt",
    "load_process_config",
]
