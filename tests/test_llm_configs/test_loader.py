"""Tests for ica.llm_configs.loader."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from ica.llm_configs.loader import (
    _config_path,
    clear_cache,
    get_process_model,
    get_process_prompts,
    load_process_config,
)
from ica.llm_configs.schema import ProcessConfig

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_CONFIG: dict = {
    "$schema": "ica-llm-config/v1",
    "processName": "summarization",
    "description": "Article summarization",
    "model": "anthropic/claude-sonnet-4.5",
    "prompts": {
        "system": "You are a professional editor.",
        "instruction": "Follow these protocols EXACTLY.",
    },
    "metadata": {
        "googleDocId": None,
        "lastSyncedAt": None,
        "version": 1,
    },
}


@pytest.fixture()
def config_dir(tmp_path: Path) -> Path:
    """Provide a temp directory and patch _CONFIG_DIR to point to it."""
    return tmp_path


@pytest.fixture(autouse=True)
def _patch_config_dir(config_dir: Path) -> None:
    """Redirect loader to use temp dir and clear cache between tests."""
    with patch("ica.llm_configs.loader._CONFIG_DIR", config_dir):
        clear_cache()
        yield
    clear_cache()


def _write_config(config_dir: Path, process_name: str, data: dict) -> Path:
    """Write a JSON config file into the temp config directory."""
    path = config_dir / f"{process_name}-llm.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# _config_path
# ---------------------------------------------------------------------------


class TestConfigPath:
    def test_returns_expected_filename(self, config_dir: Path) -> None:
        path = _config_path("summarization")
        assert path.name == "summarization-llm.json"
        assert path.parent == config_dir

    def test_hyphenated_name(self, config_dir: Path) -> None:
        path = _config_path("email-subject")
        assert path.name == "email-subject-llm.json"


# ---------------------------------------------------------------------------
# load_process_config
# ---------------------------------------------------------------------------


class TestLoadProcessConfig:
    def test_loads_valid_config(self, config_dir: Path) -> None:
        _write_config(config_dir, "summarization", _SAMPLE_CONFIG)
        cfg = load_process_config("summarization")
        assert isinstance(cfg, ProcessConfig)
        assert cfg.process_name == "summarization"
        assert cfg.model == "anthropic/claude-sonnet-4.5"
        assert cfg.prompts.system == "You are a professional editor."
        assert cfg.prompts.instruction == "Follow these protocols EXACTLY."

    def test_file_not_found_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_process_config("nonexistent")

    def test_invalid_json_raises(self, config_dir: Path) -> None:
        path = config_dir / "bad-llm.json"
        path.write_text("{invalid json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            load_process_config("bad")

    def test_schema_validation_error(self, config_dir: Path) -> None:
        _write_config(config_dir, "incomplete", {"processName": "incomplete"})
        with pytest.raises(ValidationError):
            load_process_config("incomplete")

    def test_caches_result(self, config_dir: Path) -> None:
        _write_config(config_dir, "summarization", _SAMPLE_CONFIG)
        cfg1 = load_process_config("summarization")
        cfg2 = load_process_config("summarization")
        assert cfg1 is cfg2

    def test_cache_invalidation_on_mtime_change(self, config_dir: Path) -> None:
        path = _write_config(config_dir, "summarization", _SAMPLE_CONFIG)
        cfg1 = load_process_config("summarization")

        # Sleep briefly to ensure different mtime
        time.sleep(0.05)
        updated = {**_SAMPLE_CONFIG, "model": "openai/gpt-4.1"}
        path.write_text(json.dumps(updated), encoding="utf-8")

        cfg2 = load_process_config("summarization")
        assert cfg2.model == "openai/gpt-4.1"
        assert cfg1 is not cfg2


# ---------------------------------------------------------------------------
# get_process_model
# ---------------------------------------------------------------------------


class TestGetProcessModel:
    def test_returns_model_from_json(self, config_dir: Path) -> None:
        _write_config(config_dir, "summarization", _SAMPLE_CONFIG)
        model = get_process_model("summarization")
        assert model == "anthropic/claude-sonnet-4.5"

    def test_env_var_takes_priority_over_json(self, config_dir: Path) -> None:
        _write_config(config_dir, "summarization", _SAMPLE_CONFIG)
        with patch.dict("os.environ", {"LLM_SUMMARIZATION_MODEL": "custom/model"}):
            model = get_process_model("summarization")
        assert model == "custom/model"

    def test_env_var_hyphenated_name(self, config_dir: Path) -> None:
        data = {**_SAMPLE_CONFIG, "processName": "email-subject"}
        _write_config(config_dir, "email-subject", data)
        with patch.dict("os.environ", {"LLM_EMAIL_SUBJECT_MODEL": "custom/email"}):
            model = get_process_model("email-subject")
        assert model == "custom/email"

    def test_json_used_when_no_env_var(self, config_dir: Path) -> None:
        data = {**_SAMPLE_CONFIG, "model": "google/gemini-2.5-flash"}
        _write_config(config_dir, "summarization", data)
        with patch.dict("os.environ", {}, clear=False):
            # Ensure the env var is not set
            import os

            os.environ.pop("LLM_SUMMARIZATION_MODEL", None)
            model = get_process_model("summarization")
        assert model == "google/gemini-2.5-flash"

    def test_falls_back_to_llm_config(self, config_dir: Path) -> None:
        """When no JSON exists and no env var, falls back to LLMConfig."""
        from ica.config.llm_config import get_llm_config

        get_llm_config.cache_clear()
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("LLM_SUMMARIZATION_MODEL", None)
            # No JSON file written — should fall through to LLMConfig
            # LLMConfig field: llm_summarization_model doesn't exist,
            # so this will raise FileNotFoundError
            with pytest.raises(FileNotFoundError, match="No model configuration"):
                get_process_model("summarization")

    def test_empty_env_var_not_used(self, config_dir: Path) -> None:
        _write_config(config_dir, "summarization", _SAMPLE_CONFIG)
        with patch.dict("os.environ", {"LLM_SUMMARIZATION_MODEL": ""}):
            model = get_process_model("summarization")
        assert model == "anthropic/claude-sonnet-4.5"


# ---------------------------------------------------------------------------
# get_process_prompts
# ---------------------------------------------------------------------------


class TestGetProcessPrompts:
    def test_returns_system_and_instruction(self, config_dir: Path) -> None:
        _write_config(config_dir, "summarization", _SAMPLE_CONFIG)
        system, instruction = get_process_prompts("summarization")
        assert system == "You are a professional editor."
        assert instruction == "Follow these protocols EXACTLY."

    def test_file_not_found_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            get_process_prompts("nonexistent")

    def test_returns_tuple(self, config_dir: Path) -> None:
        _write_config(config_dir, "summarization", _SAMPLE_CONFIG)
        result = get_process_prompts("summarization")
        assert isinstance(result, tuple)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# clear_cache
# ---------------------------------------------------------------------------


class TestClearCache:
    def test_clears_cache(self, config_dir: Path) -> None:
        _write_config(config_dir, "summarization", _SAMPLE_CONFIG)
        cfg1 = load_process_config("summarization")
        clear_cache()
        cfg2 = load_process_config("summarization")
        assert cfg1 is not cfg2
