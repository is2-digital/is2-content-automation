"""Pydantic models for LLM process configuration JSON files.

Each pipeline process that calls an LLM has a JSON config file with model
selection and prompt content. These models validate and represent that schema.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PromptsConfig(BaseModel):
    """System and instruction prompt pair for an LLM process."""

    system: str = Field(description="Role definition and context")
    instruction: str = Field(description="Rules, constraints, output format")


class MetadataConfig(BaseModel):
    """Editing and sync metadata for a process config."""

    google_doc_id: str | None = Field(
        default=None,
        alias="googleDocId",
        description="Associated Google Doc for editing (null until first edit)",
    )
    last_synced_at: datetime | None = Field(
        default=None,
        alias="lastSyncedAt",
        description="Timestamp of last Google Docs → JSON sync",
    )
    version: int = Field(
        default=1,
        description="Incremented on each sync",
    )

    model_config = {"populate_by_name": True}


class ProcessConfig(BaseModel):
    """Top-level model for an LLM process configuration file.

    Corresponds to the ``ica-llm-config/v1`` JSON schema.
    """

    schema_version: str = Field(
        default="ica-llm-config/v1",
        alias="$schema",
        description="Schema version for forward compatibility",
    )
    process_name: str = Field(
        alias="processName",
        description="Unique identifier matching the JSON filename",
    )
    description: str = Field(
        description="Human-readable purpose (displayed in Slack when browsing configs)",
    )
    model: str = Field(
        description="LLM model ID in OpenRouter provider/model format",
    )
    prompts: PromptsConfig
    metadata: MetadataConfig = Field(default_factory=MetadataConfig)

    model_config = {"populate_by_name": True}
