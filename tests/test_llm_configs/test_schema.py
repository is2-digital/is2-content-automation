"""Tests for ica.llm_configs.schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ica.llm_configs.schema import (
    Metadata,
    ProcessConfig,
    Prompts,
    SystemPromptConfig,
    SystemPromptMetadata,
)


def _valid_config_data() -> dict:
    """Return a minimal valid config dict."""
    return {
        "$schema": "ica-llm-config/v1",
        "processName": "summarization",
        "description": "Article summarization",
        "model": "anthropic/claude-sonnet-4.5",
        "prompts": {
            "instruction": "Follow these rules.",
        },
        "metadata": {
            "googleDocId": None,
            "lastSyncedAt": None,
            "version": 1,
        },
    }


# ---------------------------------------------------------------------------
# Prompts model
# ---------------------------------------------------------------------------


class TestPrompts:
    def test_valid_prompts(self) -> None:
        p = Prompts(instruction="instruction text")
        assert p.instruction == "instruction text"

    def test_empty_instruction_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Prompts(instruction="")


# ---------------------------------------------------------------------------
# SystemPromptMetadata model
# ---------------------------------------------------------------------------


class TestSystemPromptMetadata:
    def test_defaults(self) -> None:
        m = SystemPromptMetadata()
        assert m.last_synced_at is None
        assert m.version == 1

    def test_custom_values(self) -> None:
        m = SystemPromptMetadata(
            last_synced_at="2026-02-28T12:00:00Z",
            version=2,
        )
        assert m.last_synced_at == "2026-02-28T12:00:00Z"
        assert m.version == 2

    def test_custom_values_via_alias(self) -> None:
        m = SystemPromptMetadata(lastSyncedAt="2026-02-28T12:00:00Z", version=3)
        assert m.last_synced_at == "2026-02-28T12:00:00Z"
        assert m.version == 3

    def test_version_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            SystemPromptMetadata(version=0)


# ---------------------------------------------------------------------------
# SystemPromptConfig model
# ---------------------------------------------------------------------------


def _valid_system_prompt_data() -> dict:
    """Return a minimal valid system prompt config dict."""
    return {
        "$schema": "ica-system-prompt/v1",
        "description": "Shared system prompt",
        "prompt": "You are an AI system supporting the IS2 Digital newsletter.",
        "metadata": {
            "lastSyncedAt": None,
            "version": 1,
        },
    }


class TestSystemPromptConfig:
    def test_valid_config(self) -> None:
        data = _valid_system_prompt_data()
        config = SystemPromptConfig.model_validate(data)
        assert config.schema_version == "ica-system-prompt/v1"
        assert config.description == "Shared system prompt"
        assert "IS2 Digital" in config.prompt
        assert config.metadata.version == 1

    def test_schema_alias(self) -> None:
        data = _valid_system_prompt_data()
        config = SystemPromptConfig.model_validate(data)
        assert config.schema_version == "ica-system-prompt/v1"

    def test_missing_schema_rejected(self) -> None:
        data = _valid_system_prompt_data()
        del data["$schema"]
        with pytest.raises(ValidationError):
            SystemPromptConfig.model_validate(data)

    def test_missing_prompt_rejected(self) -> None:
        data = _valid_system_prompt_data()
        del data["prompt"]
        with pytest.raises(ValidationError):
            SystemPromptConfig.model_validate(data)

    def test_empty_prompt_rejected(self) -> None:
        data = _valid_system_prompt_data()
        data["prompt"] = ""
        with pytest.raises(ValidationError):
            SystemPromptConfig.model_validate(data)

    def test_metadata_defaults_when_omitted(self) -> None:
        data = _valid_system_prompt_data()
        del data["metadata"]
        config = SystemPromptConfig.model_validate(data)
        assert config.metadata.version == 1
        assert config.metadata.last_synced_at is None

    def test_description_defaults_to_empty(self) -> None:
        data = _valid_system_prompt_data()
        del data["description"]
        config = SystemPromptConfig.model_validate(data)
        assert config.description == ""


# ---------------------------------------------------------------------------
# Metadata model
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_defaults(self) -> None:
        m = Metadata()
        assert m.google_doc_id is None
        assert m.last_synced_at is None
        assert m.version == 1

    def test_custom_values(self) -> None:
        m = Metadata(
            google_doc_id="abc123",
            last_synced_at="2026-01-01T00:00:00Z",
            version=3,
        )
        assert m.google_doc_id == "abc123"
        assert m.last_synced_at == "2026-01-01T00:00:00Z"
        assert m.version == 3

    def test_custom_values_via_alias(self) -> None:
        m = Metadata(googleDocId="abc123", lastSyncedAt="2026-01-01T00:00:00Z", version=3)
        assert m.google_doc_id == "abc123"
        assert m.last_synced_at == "2026-01-01T00:00:00Z"

    def test_version_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            Metadata(version=0)


# ---------------------------------------------------------------------------
# ProcessConfig model
# ---------------------------------------------------------------------------


class TestProcessConfig:
    def test_valid_config(self) -> None:
        data = _valid_config_data()
        config = ProcessConfig.model_validate(data)
        assert config.schema_version == "ica-llm-config/v1"
        assert config.process_name == "summarization"
        assert config.model == "anthropic/claude-sonnet-4.5"
        assert config.prompts.instruction == "Follow these rules."
        assert config.metadata.version == 1

    def test_schema_alias(self) -> None:
        """$schema JSON key maps to schema_version field."""
        data = _valid_config_data()
        config = ProcessConfig.model_validate(data)
        assert config.schema_version == "ica-llm-config/v1"

    def test_missing_schema_rejected(self) -> None:
        data = _valid_config_data()
        del data["$schema"]
        with pytest.raises(ValidationError):
            ProcessConfig.model_validate(data)

    def test_missing_process_name_rejected(self) -> None:
        data = _valid_config_data()
        del data["processName"]
        with pytest.raises(ValidationError):
            ProcessConfig.model_validate(data)

    def test_empty_process_name_rejected(self) -> None:
        data = _valid_config_data()
        data["processName"] = ""
        with pytest.raises(ValidationError):
            ProcessConfig.model_validate(data)

    def test_missing_model_rejected(self) -> None:
        data = _valid_config_data()
        del data["model"]
        with pytest.raises(ValidationError):
            ProcessConfig.model_validate(data)

    def test_empty_model_rejected(self) -> None:
        data = _valid_config_data()
        data["model"] = ""
        with pytest.raises(ValidationError):
            ProcessConfig.model_validate(data)

    def test_missing_prompts_rejected(self) -> None:
        data = _valid_config_data()
        del data["prompts"]
        with pytest.raises(ValidationError):
            ProcessConfig.model_validate(data)

    def test_metadata_defaults_when_omitted(self) -> None:
        data = _valid_config_data()
        del data["metadata"]
        config = ProcessConfig.model_validate(data)
        assert config.metadata.version == 1
        assert config.metadata.google_doc_id is None

    def test_description_defaults_to_empty(self) -> None:
        data = _valid_config_data()
        del data["description"]
        config = ProcessConfig.model_validate(data)
        assert config.description == ""


# ---------------------------------------------------------------------------
# Package exports
# ---------------------------------------------------------------------------


class TestPackageExports:
    def test_import_process_config(self) -> None:
        from ica.llm_configs import ProcessConfig as Imported

        assert Imported is ProcessConfig

    def test_import_prompts(self) -> None:
        from ica.llm_configs import Prompts as Imported

        assert Imported is Prompts

    def test_import_metadata(self) -> None:
        from ica.llm_configs import Metadata as Imported

        assert Imported is Metadata

    def test_import_system_prompt_config(self) -> None:
        from ica.llm_configs import SystemPromptConfig as Imported

        assert Imported is SystemPromptConfig

    def test_import_system_prompt_metadata(self) -> None:
        from ica.llm_configs import SystemPromptMetadata as Imported

        assert Imported is SystemPromptMetadata
