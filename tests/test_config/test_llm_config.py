"""Tests for ica.config.llm_config."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ica.config.llm_config import (
    _PURPOSE_TO_PROCESS,
    LLMPurpose,
    get_model,
)
from ica.llm_configs import loader
from ica.llm_configs.loader import _cache, load_process_config


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    """Clear loader caches between tests."""
    _cache.clear()
    loader._system_prompt_cache = None


# ---------------------------------------------------------------------------
# LLMPurpose enum
# ---------------------------------------------------------------------------


class TestLLMPurpose:
    """LLMPurpose enum should map to _PURPOSE_TO_PROCESS keys."""

    def test_all_purposes_have_23_members(self) -> None:
        assert len(LLMPurpose) == 23

    @pytest.mark.parametrize("purpose", list(LLMPurpose))
    def test_purpose_value_is_in_mapping(self, purpose: LLMPurpose) -> None:
        assert purpose.value in _PURPOSE_TO_PROCESS, (
            f"LLMPurpose.{purpose.name} = '{purpose.value}' "
            f"is not a key in _PURPOSE_TO_PROCESS"
        )

    def test_purpose_values_are_unique(self) -> None:
        values = [p.value for p in LLMPurpose]
        assert len(values) == len(set(values))

    def test_specific_purpose_names(self) -> None:
        assert LLMPurpose.SUMMARY.value == "llm_summary_model"
        assert LLMPurpose.MARKDOWN_VALIDATOR.value == "llm_markdown_validator_model"
        assert LLMPurpose.THEME_FRESHNESS_CHECK.value == "llm_theme_freshness_check_model"


# ---------------------------------------------------------------------------
# get_model() — resolves from JSON config
# ---------------------------------------------------------------------------


class TestGetModel:
    """get_model() should return the model from the JSON config file."""

    def test_returns_model_from_json(self) -> None:
        model = get_model(LLMPurpose.SUMMARY)
        expected = load_process_config("summarization").model
        assert model == expected

    def test_validator_model_from_json(self) -> None:
        model = get_model(LLMPurpose.MARKDOWN_VALIDATOR)
        expected = load_process_config("markdown-structural-validation").model
        assert model == expected

    def test_freshness_model_from_json(self) -> None:
        model = get_model(LLMPurpose.THEME_FRESHNESS_CHECK)
        expected = load_process_config("freshness-check").model
        assert model == expected

    @pytest.mark.parametrize("purpose", list(LLMPurpose))
    def test_every_purpose_returns_string(self, purpose: LLMPurpose) -> None:
        result = get_model(purpose)
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.parametrize("purpose", list(LLMPurpose))
    def test_every_purpose_returns_provider_model_format(
        self, purpose: LLMPurpose
    ) -> None:
        model = get_model(purpose)
        assert "/" in model, f"LLMPurpose.{purpose.name}: '{model}' missing '/'"


# ---------------------------------------------------------------------------
# get_model() with custom JSON configs
# ---------------------------------------------------------------------------


def _write_json_config(
    tmp_path: Path, process_name: str, model: str = "custom/json-model"
) -> None:
    """Write a minimal valid JSON config file for testing."""
    data = {
        "$schema": "ica-llm-config/v1",
        "processName": process_name,
        "description": "Test config",
        "model": model,
        "prompts": {"instruction": "Test instruction."},
        "metadata": {"googleDocId": None, "lastSyncedAt": None, "version": 1},
    }
    path = tmp_path / f"{process_name}-llm.json"
    path.write_text(json.dumps(data))


class TestGetModelFromJson:
    """get_model() reads from JSON config files."""

    def test_reads_custom_json_config(self, tmp_path: Path) -> None:
        _write_json_config(tmp_path, "summarization", model="custom/json-model")

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            model = get_model(LLMPurpose.SUMMARY)

        assert model == "custom/json-model"

    def test_missing_json_raises_file_not_found(self, tmp_path: Path) -> None:
        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            pytest.raises(FileNotFoundError),
        ):
            get_model(LLMPurpose.SUMMARY)

    def test_learning_data_purposes_resolve_via_json(self) -> None:
        """Learning-data purposes all resolve to the same JSON config."""
        model = get_model(LLMPurpose.MARKDOWN_LEARNING_DATA)
        expected = load_process_config("learning-data-extraction").model
        assert model == expected

    def test_json_config_for_freshness_check(self, tmp_path: Path) -> None:
        _write_json_config(tmp_path, "freshness-check", model="custom/fast-checker")

        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            model = get_model(LLMPurpose.THEME_FRESHNESS_CHECK)

        assert model == "custom/fast-checker"


# ---------------------------------------------------------------------------
# _PURPOSE_TO_PROCESS mapping
# ---------------------------------------------------------------------------


class TestPurposeToProcess:
    """Validate the _PURPOSE_TO_PROCESS mapping dict."""

    def test_all_mapped_values_are_valid_process_names(self) -> None:
        """Every mapped process name should have a corresponding JSON file."""
        configs_dir = Path(__file__).parent.parent.parent / "ica" / "llm_configs"
        for field_name, process_name in _PURPOSE_TO_PROCESS.items():
            expected_file = configs_dir / f"{process_name}-llm.json"
            assert expected_file.exists(), (
                f"_PURPOSE_TO_PROCESS[{field_name!r}] = {process_name!r} "
                f"but {expected_file} does not exist"
            )

    def test_all_mapped_keys_are_purpose_values(self) -> None:
        """Every key in the mapping should be a valid LLMPurpose value."""
        purpose_values = {p.value for p in LLMPurpose}
        for field_name in _PURPOSE_TO_PROCESS:
            assert field_name in purpose_values, (
                f"_PURPOSE_TO_PROCESS key {field_name!r} is not an LLMPurpose value"
            )

    def test_mapping_covers_23_purposes(self) -> None:
        """All 23 purposes have JSON config mappings."""
        assert len(_PURPOSE_TO_PROCESS) == 23


# ---------------------------------------------------------------------------
# Package re-exports
# ---------------------------------------------------------------------------


class TestPackageExport:
    """ica.config should re-export LLM config items."""

    def test_import_llm_purpose(self) -> None:
        from ica.config import LLMPurpose as P

        assert P is LLMPurpose

    def test_import_get_model(self) -> None:
        from ica.config import get_model as f

        assert f is get_model
