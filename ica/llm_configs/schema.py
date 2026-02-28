"""Pydantic models for LLM process JSON configuration files.

Matches the ``ica-llm-config/v1`` schema defined in the scope document
(Section 5). Each JSON file in ``ica/llm_configs/`` is validated against
:class:`ProcessConfig` at load time.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Prompts(BaseModel):
    """Instruction prompt content for a pipeline process.

    The system prompt is application-wide and managed separately
    via :class:`SystemPromptConfig`.
    """

    instruction: str = Field(min_length=1)


class SystemPromptMetadata(BaseModel):
    """Editing metadata for the shared system prompt config."""

    last_synced_at: str | None = Field(default=None, alias="lastSyncedAt")
    version: int = Field(default=1, ge=1)

    model_config = {"populate_by_name": True}


class SystemPromptConfig(BaseModel):
    """Schema for the application-wide shared system prompt.

    Loaded from ``system-prompt.json`` in ``ica/llm_configs/``.
    This is the single source of truth for the system prompt used
    across all pipeline processes.

    Example JSON::

        {
            "$schema": "ica-system-prompt/v1",
            "description": "Shared system prompt for ...",
            "prompt": "You are an AI system ...",
            "metadata": { "lastSyncedAt": null, "version": 1 }
        }
    """

    schema_version: str = Field(alias="$schema")
    description: str = Field(default="")
    prompt: str = Field(min_length=1)
    metadata: SystemPromptMetadata = Field(default_factory=SystemPromptMetadata)

    model_config = {"populate_by_name": True}


class Metadata(BaseModel):
    """Editing metadata for Google Docs sync workflow."""

    google_doc_id: str | None = Field(default=None, alias="googleDocId")
    last_synced_at: str | None = Field(default=None, alias="lastSyncedAt")
    version: int = Field(default=1, ge=1)

    model_config = {"populate_by_name": True}


class ProcessConfig(BaseModel):
    """Top-level schema for an LLM process configuration file.

    Example JSON::

        {
            "$schema": "ica-llm-config/v1",
            "processName": "summarization",
            "description": "Article summarization ...",
            "model": "anthropic/claude-sonnet-4.5",
            "prompts": { "instruction": "..." },
            "metadata": { "googleDocId": null, "lastSyncedAt": null, "version": 1 }
        }
    """

    schema_version: str = Field(alias="$schema")
    process_name: str = Field(min_length=1, alias="processName")
    description: str = Field(default="")
    model: str = Field(min_length=1)
    prompts: Prompts
    metadata: Metadata = Field(default_factory=Metadata)

    model_config = {"populate_by_name": True}
