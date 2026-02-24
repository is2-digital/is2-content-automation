"""Tests for ica.llm_configs.schema."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from ica.llm_configs.schema import MetadataConfig, ProcessConfig, PromptsConfig

# ---------------------------------------------------------------------------
# Sample data helpers
# ---------------------------------------------------------------------------

_MINIMAL_JSON: dict = {
    "$schema": "ica-llm-config/v1",
    "processName": "summarization",
    "description": "Article summarization",
    "model": "anthropic/claude-sonnet-4.5",
    "prompts": {
        "system": "You are an editor.",
        "instruction": "Follow these rules.",
    },
}

_FULL_JSON: dict = {
    **_MINIMAL_JSON,
    "metadata": {
        "googleDocId": "abc123",
        "lastSyncedAt": "2026-01-15T10:30:00Z",
        "version": 3,
    },
}


# ---------------------------------------------------------------------------
# PromptsConfig
# ---------------------------------------------------------------------------


class TestPromptsConfig:
    def test_valid_prompts(self) -> None:
        p = PromptsConfig(system="role", instruction="rules")
        assert p.system == "role"
        assert p.instruction == "rules"

    def test_missing_system_raises(self) -> None:
        with pytest.raises(ValidationError):
            PromptsConfig(instruction="rules")  # type: ignore[call-arg]

    def test_missing_instruction_raises(self) -> None:
        with pytest.raises(ValidationError):
            PromptsConfig(system="role")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# MetadataConfig
# ---------------------------------------------------------------------------


class TestMetadataConfig:
    def test_defaults(self) -> None:
        m = MetadataConfig()
        assert m.google_doc_id is None
        assert m.last_synced_at is None
        assert m.version == 1

    def test_from_camel_case_aliases(self) -> None:
        m = MetadataConfig.model_validate(
            {"googleDocId": "doc-1", "lastSyncedAt": "2026-01-01T00:00:00Z", "version": 5}
        )
        assert m.google_doc_id == "doc-1"
        assert m.version == 5
        assert isinstance(m.last_synced_at, datetime)

    def test_populate_by_name(self) -> None:
        m = MetadataConfig(google_doc_id="doc-2", version=2)
        assert m.google_doc_id == "doc-2"
        assert m.version == 2


# ---------------------------------------------------------------------------
# ProcessConfig — valid data
# ---------------------------------------------------------------------------


class TestProcessConfigValid:
    def test_minimal_json(self) -> None:
        cfg = ProcessConfig.model_validate(_MINIMAL_JSON)
        assert cfg.schema_version == "ica-llm-config/v1"
        assert cfg.process_name == "summarization"
        assert cfg.description == "Article summarization"
        assert cfg.model == "anthropic/claude-sonnet-4.5"
        assert cfg.prompts.system == "You are an editor."
        assert cfg.prompts.instruction == "Follow these rules."

    def test_minimal_json_default_metadata(self) -> None:
        cfg = ProcessConfig.model_validate(_MINIMAL_JSON)
        assert cfg.metadata.google_doc_id is None
        assert cfg.metadata.last_synced_at is None
        assert cfg.metadata.version == 1

    def test_full_json(self) -> None:
        cfg = ProcessConfig.model_validate(_FULL_JSON)
        assert cfg.metadata.google_doc_id == "abc123"
        assert cfg.metadata.version == 3
        assert isinstance(cfg.metadata.last_synced_at, datetime)

    def test_schema_version_default(self) -> None:
        data = {k: v for k, v in _MINIMAL_JSON.items() if k != "$schema"}
        cfg = ProcessConfig.model_validate(data)
        assert cfg.schema_version == "ica-llm-config/v1"

    def test_populate_by_field_name(self) -> None:
        cfg = ProcessConfig(
            process_name="test",
            description="desc",
            model="openai/gpt-4.1",
            prompts=PromptsConfig(system="s", instruction="i"),
        )
        assert cfg.process_name == "test"


# ---------------------------------------------------------------------------
# ProcessConfig — validation errors
# ---------------------------------------------------------------------------


class TestProcessConfigValidation:
    def test_missing_process_name_raises(self) -> None:
        data = {k: v for k, v in _MINIMAL_JSON.items() if k != "processName"}
        with pytest.raises(ValidationError):
            ProcessConfig.model_validate(data)

    def test_missing_model_raises(self) -> None:
        data = {k: v for k, v in _MINIMAL_JSON.items() if k != "model"}
        with pytest.raises(ValidationError):
            ProcessConfig.model_validate(data)

    def test_missing_prompts_raises(self) -> None:
        data = {k: v for k, v in _MINIMAL_JSON.items() if k != "prompts"}
        with pytest.raises(ValidationError):
            ProcessConfig.model_validate(data)

    def test_missing_description_raises(self) -> None:
        data = {k: v for k, v in _MINIMAL_JSON.items() if k != "description"}
        with pytest.raises(ValidationError):
            ProcessConfig.model_validate(data)

    def test_invalid_prompts_type_raises(self) -> None:
        data = {**_MINIMAL_JSON, "prompts": "not a dict"}
        with pytest.raises(ValidationError):
            ProcessConfig.model_validate(data)


# ---------------------------------------------------------------------------
# Round-trip serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_round_trip_with_aliases(self) -> None:
        cfg = ProcessConfig.model_validate(_FULL_JSON)
        dumped = cfg.model_dump(by_alias=True)
        assert dumped["$schema"] == "ica-llm-config/v1"
        assert dumped["processName"] == "summarization"
        assert dumped["metadata"]["googleDocId"] == "abc123"
        assert dumped["metadata"]["version"] == 3

    def test_json_round_trip(self) -> None:
        cfg = ProcessConfig.model_validate(_MINIMAL_JSON)
        json_str = cfg.model_dump_json(by_alias=True)
        restored = ProcessConfig.model_validate_json(json_str)
        assert restored.process_name == cfg.process_name
        assert restored.model == cfg.model
