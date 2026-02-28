"""Tests for ica.llm_configs.loader."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ica.llm_configs import loader
from ica.llm_configs.loader import (
    _cache,
    get_process_model,
    get_process_prompts,
    get_system_prompt,
    load_process_config,
)
from ica.llm_configs.schema import ProcessConfig


def _valid_config_dict(**overrides: object) -> dict:
    """Return a valid config dict with optional overrides."""
    base = {
        "$schema": "ica-llm-config/v1",
        "processName": "test-process",
        "description": "A test process",
        "model": "anthropic/claude-sonnet-4.5",
        "prompts": {
            "instruction": "Follow test instructions.",
        },
        "metadata": {
            "googleDocId": None,
            "lastSyncedAt": None,
            "version": 1,
        },
    }
    base.update(overrides)
    return base


def _valid_system_prompt_dict(**overrides: object) -> dict:
    """Return a valid system prompt config dict with optional overrides."""
    base = {
        "$schema": "ica-system-prompt/v1",
        "description": "Test shared system prompt",
        "prompt": "You are a test system.",
        "metadata": {"lastSyncedAt": None, "version": 1},
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    """Clear loader caches between tests."""
    _cache.clear()
    loader._system_prompt_cache = None
    loader._PROCESS_TO_FIELD = None


# ---------------------------------------------------------------------------
# load_process_config()
# ---------------------------------------------------------------------------


class TestLoadProcessConfig:
    def test_loads_valid_json(self, tmp_path: Path) -> None:
        data = _valid_config_dict(processName="my-process")
        config_file = tmp_path / "my-process-llm.json"
        config_file.write_text(json.dumps(data))

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            config = load_process_config("my-process")

        assert isinstance(config, ProcessConfig)
        assert config.process_name == "my-process"
        assert config.model == "anthropic/claude-sonnet-4.5"

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            pytest.raises(FileNotFoundError, match="Config file not found"),
        ):
            load_process_config("nonexistent")

    def test_invalid_json_raises_value_error(self, tmp_path: Path) -> None:
        config_file = tmp_path / "bad-llm.json"
        config_file.write_text("{not valid json")

        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            pytest.raises(ValueError, match="Invalid JSON"),
        ):
            load_process_config("bad")

    def test_schema_validation_failure_raises_value_error(self, tmp_path: Path) -> None:
        config_file = tmp_path / "invalid-llm.json"
        config_file.write_text(json.dumps({"bad": "schema"}))

        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            pytest.raises(ValueError, match="Schema validation failed"),
        ):
            load_process_config("invalid")

    def test_caches_by_mtime(self, tmp_path: Path) -> None:
        data = _valid_config_dict(processName="cached")
        config_file = tmp_path / "cached-llm.json"
        config_file.write_text(json.dumps(data))

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            first = load_process_config("cached")
            second = load_process_config("cached")

        assert first is second

    def test_cache_invalidated_on_mtime_change(self, tmp_path: Path) -> None:
        data = _valid_config_dict(processName="mtime-test")
        config_file = tmp_path / "mtime-test-llm.json"
        config_file.write_text(json.dumps(data))

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            first = load_process_config("mtime-test")

            # Simulate file modification by writing new content and changing mtime.
            import os
            import time

            time.sleep(0.05)
            updated_data = _valid_config_dict(
                processName="mtime-test",
                description="Updated description",
            )
            config_file.write_text(json.dumps(updated_data))
            # Ensure mtime actually differs.
            current_stat = config_file.stat()
            os.utime(config_file, (current_stat.st_atime, current_stat.st_mtime + 1))

            second = load_process_config("mtime-test")

        assert first is not second
        assert second.description == "Updated description"


# ---------------------------------------------------------------------------
# get_system_prompt()
# ---------------------------------------------------------------------------


class TestGetSystemPrompt:
    def test_loads_shared_system_prompt(self, tmp_path: Path) -> None:
        data = _valid_system_prompt_dict(prompt="Shared system prompt.")
        (tmp_path / "system-prompt.json").write_text(json.dumps(data))

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            result = get_system_prompt()

        assert result == "Shared system prompt."

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            pytest.raises(FileNotFoundError, match="System prompt file not found"),
        ):
            get_system_prompt()

    def test_invalid_json_raises_value_error(self, tmp_path: Path) -> None:
        (tmp_path / "system-prompt.json").write_text("{bad json")

        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            pytest.raises(ValueError, match="Invalid JSON"),
        ):
            get_system_prompt()

    def test_schema_validation_failure_raises_value_error(self, tmp_path: Path) -> None:
        (tmp_path / "system-prompt.json").write_text(json.dumps({"bad": "schema"}))

        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            pytest.raises(ValueError, match="Schema validation failed"),
        ):
            get_system_prompt()

    def test_caches_by_mtime(self, tmp_path: Path) -> None:
        data = _valid_system_prompt_dict()
        (tmp_path / "system-prompt.json").write_text(json.dumps(data))

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            first = get_system_prompt()
            second = get_system_prompt()

        assert first == second
        # Verify cache was populated (not None after load).
        assert loader._system_prompt_cache is not None

    def test_cache_invalidated_on_mtime_change(self, tmp_path: Path) -> None:
        import os

        data = _valid_system_prompt_dict(prompt="Original prompt.")
        sp_file = tmp_path / "system-prompt.json"
        sp_file.write_text(json.dumps(data))

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            first = get_system_prompt()

            updated = _valid_system_prompt_dict(prompt="Updated prompt.")
            sp_file.write_text(json.dumps(updated))
            current_stat = sp_file.stat()
            os.utime(sp_file, (current_stat.st_atime, current_stat.st_mtime + 1))

            second = get_system_prompt()

        assert first == "Original prompt."
        assert second == "Updated prompt."


# ---------------------------------------------------------------------------
# get_process_prompts()
# ---------------------------------------------------------------------------


class TestGetProcessPrompts:
    def test_returns_shared_system_and_process_instruction(self, tmp_path: Path) -> None:
        sp_data = _valid_system_prompt_dict(prompt="Shared system prompt.")
        (tmp_path / "system-prompt.json").write_text(json.dumps(sp_data))

        proc_data = _valid_config_dict(
            processName="prompt-test",
            prompts={"instruction": "Instruction prompt content."},
        )
        (tmp_path / "prompt-test-llm.json").write_text(json.dumps(proc_data))

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            system, instruction = get_process_prompts("prompt-test")

        assert system == "Shared system prompt."
        assert instruction == "Instruction prompt content."

    def test_raises_for_missing_process_config(self, tmp_path: Path) -> None:
        sp_data = _valid_system_prompt_dict()
        (tmp_path / "system-prompt.json").write_text(json.dumps(sp_data))

        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            pytest.raises(FileNotFoundError, match="Config file not found"),
        ):
            get_process_prompts("nonexistent")

    def test_raises_for_missing_system_prompt(self, tmp_path: Path) -> None:
        proc_data = _valid_config_dict(processName="prompt-test")
        (tmp_path / "prompt-test-llm.json").write_text(json.dumps(proc_data))

        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            pytest.raises(FileNotFoundError, match="System prompt file not found"),
        ):
            get_process_prompts("prompt-test")


# ---------------------------------------------------------------------------
# get_process_model()
# ---------------------------------------------------------------------------


class TestGetProcessModel:
    def test_returns_json_model_when_no_env_override(self, tmp_path: Path) -> None:
        data = _valid_config_dict(
            processName="summarization",
            model="anthropic/claude-sonnet-4.5",
        )
        config_file = tmp_path / "summarization-llm.json"
        config_file.write_text(json.dumps(data))

        from ica.config.llm_config import get_llm_config

        get_llm_config.cache_clear()

        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            patch.dict("os.environ", {}, clear=False),
        ):
            model = get_process_model("summarization")

        assert model == "anthropic/claude-sonnet-4.5"

    def test_env_var_overrides_json_model(self, tmp_path: Path) -> None:
        data = _valid_config_dict(
            processName="summarization",
            model="anthropic/claude-sonnet-4.5",
        )
        config_file = tmp_path / "summarization-llm.json"
        config_file.write_text(json.dumps(data))

        from ica.config.llm_config import get_llm_config

        get_llm_config.cache_clear()

        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            patch.dict(
                "os.environ",
                {"LLM_SUMMARY_MODEL": "custom/override-model"},
                clear=False,
            ),
        ):
            model = get_process_model("summarization")

        assert model == "custom/override-model"

    def test_json_model_used_for_unknown_process(self, tmp_path: Path) -> None:
        """Processes not in the mapping still return their JSON model."""
        data = _valid_config_dict(
            processName="custom-process",
            model="custom/my-model",
        )
        config_file = tmp_path / "custom-process-llm.json"
        config_file.write_text(json.dumps(data))

        from ica.config.llm_config import get_llm_config

        get_llm_config.cache_clear()

        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            patch.dict("os.environ", {}, clear=False),
        ):
            model = get_process_model("custom-process")

        assert model == "custom/my-model"


# ---------------------------------------------------------------------------
# _build_process_field_mapping()
# ---------------------------------------------------------------------------


class TestProcessFieldMapping:
    def test_mapping_covers_all_19_processes(self) -> None:
        from ica.llm_configs.loader import _build_process_field_mapping

        mapping = _build_process_field_mapping()
        # The scope doc defines 19 JSON files + learning-data-extraction
        # that maps to an existing field. All should be covered.
        assert len(mapping) >= 19

    def test_all_mapped_fields_exist_on_llm_config(self) -> None:
        from ica.config.llm_config import LLMConfig
        from ica.llm_configs.loader import _build_process_field_mapping

        mapping = _build_process_field_mapping()
        for process_name, field_name in mapping.items():
            assert field_name in LLMConfig.model_fields, (
                f"Process '{process_name}' maps to '{field_name}' "
                f"which is not a field on LLMConfig"
            )


# ---------------------------------------------------------------------------
# Package exports
# ---------------------------------------------------------------------------


class TestPackageExports:
    def test_import_load_process_config(self) -> None:
        from ica.llm_configs import load_process_config as f

        assert f is load_process_config

    def test_import_get_process_model(self) -> None:
        from ica.llm_configs import get_process_model as f

        assert f is get_process_model

    def test_import_get_system_prompt(self) -> None:
        from ica.llm_configs import get_system_prompt as f

        assert f is get_system_prompt

    def test_import_get_process_prompts(self) -> None:
        from ica.llm_configs import get_process_prompts as f

        assert f is get_process_prompts
