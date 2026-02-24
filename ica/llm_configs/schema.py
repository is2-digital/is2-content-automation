"""Pydantic models for LLM process JSON configuration files.

Matches the ``ica-llm-config/v1`` schema defined in the scope document
(Section 5). Each JSON file in ``ica/llm_configs/`` is validated against
:class:`ProcessConfig` at load time.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Prompts(BaseModel):
    """System and instruction prompt content."""

    system: str = Field(min_length=1)
    instruction: str = Field(min_length=1)


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
            "prompts": { "system": "...", "instruction": "..." },
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
