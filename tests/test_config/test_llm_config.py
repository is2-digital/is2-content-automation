"""Tests for ica.config.llm_config."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ica.config.llm_config import (
    _PURPOSE_TO_PROCESS,
    LLMConfig,
    LLMPurpose,
    get_llm_config,
    get_model,
)


def _make_llm_config(**overrides: str) -> LLMConfig:
    """Create an LLMConfig instance, optionally overriding fields via env vars."""
    with patch.dict("os.environ", overrides, clear=False):
        return LLMConfig(_env_file=None)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Default model values
# ---------------------------------------------------------------------------


class TestDefaults:
    """All 21 fields should have the correct default model from the n8n config."""

    _CLAUDE_SONNET = "anthropic/claude-sonnet-4.5"
    _GPT_4_1 = "openai/gpt-4.1"
    _GEMINI_FLASH = "google/gemini-2.5-flash"

    @pytest.mark.parametrize(
        "field,expected",
        [
            ("llm_summary_model", _CLAUDE_SONNET),
            ("llm_summary_regeneration_model", _CLAUDE_SONNET),
            ("llm_summary_learning_data_model", _CLAUDE_SONNET),
            ("llm_markdown_model", _CLAUDE_SONNET),
            ("llm_markdown_validator_model", _GPT_4_1),
            ("llm_markdown_regeneration_model", _CLAUDE_SONNET),
            ("llm_markdown_learning_data_model", _CLAUDE_SONNET),
            ("llm_html_model", _CLAUDE_SONNET),
            ("llm_html_regeneration_model", _CLAUDE_SONNET),
            ("llm_html_learning_data_model", _CLAUDE_SONNET),
            ("llm_theme_model", _CLAUDE_SONNET),
            ("llm_theme_learning_data_model", _CLAUDE_SONNET),
            ("llm_theme_freshness_check_model", _GEMINI_FLASH),
            ("llm_social_media_model", _CLAUDE_SONNET),
            ("llm_social_post_caption_model", _CLAUDE_SONNET),
            ("llm_social_media_regeneration_model", _CLAUDE_SONNET),
            ("llm_linkedin_model", _CLAUDE_SONNET),
            ("llm_linkedin_regeneration_model", _CLAUDE_SONNET),
            ("llm_email_subject_model", _CLAUDE_SONNET),
            ("llm_email_subject_regeneration_model", _CLAUDE_SONNET),
            ("llm_email_preview_model", _CLAUDE_SONNET),
            ("llm_relevance_assessment_model", _GEMINI_FLASH),
        ],
    )
    def test_default_value(self, field: str, expected: str) -> None:
        cfg = _make_llm_config()
        assert getattr(cfg, field) == expected

    def test_total_field_count_is_22(self) -> None:
        """Ensure all 22 model mappings are represented."""
        model_fields = [f for f in LLMConfig.model_fields if f.startswith("llm_")]
        assert len(model_fields) == 22


# ---------------------------------------------------------------------------
# Environment variable overrides
# ---------------------------------------------------------------------------


class TestEnvOverrides:
    """Each field should be overridable via its env var."""

    @pytest.mark.parametrize(
        "env_var,field",
        [
            ("LLM_SUMMARY_MODEL", "llm_summary_model"),
            ("LLM_MARKDOWN_VALIDATOR_MODEL", "llm_markdown_validator_model"),
            ("LLM_THEME_FRESHNESS_CHECK_MODEL", "llm_theme_freshness_check_model"),
            ("LLM_EMAIL_PREVIEW_MODEL", "llm_email_preview_model"),
            ("LLM_LINKEDIN_MODEL", "llm_linkedin_model"),
        ],
    )
    def test_override_via_env(self, env_var: str, field: str) -> None:
        cfg = _make_llm_config(**{env_var: "custom/model-v2"})
        assert getattr(cfg, field) == "custom/model-v2"

    def test_override_does_not_affect_other_fields(self) -> None:
        cfg = _make_llm_config(LLM_SUMMARY_MODEL="custom/override")
        assert cfg.llm_summary_model == "custom/override"
        assert cfg.llm_summary_regeneration_model == "anthropic/claude-sonnet-4.5"

    def test_extra_env_vars_ignored(self) -> None:
        cfg = _make_llm_config(SOME_UNRELATED_VAR="value")
        assert not hasattr(cfg, "some_unrelated_var")


# ---------------------------------------------------------------------------
# LLMPurpose enum
# ---------------------------------------------------------------------------


class TestLLMPurpose:
    """LLMPurpose enum should map to LLMConfig field names."""

    def test_all_purposes_have_22_members(self) -> None:
        assert len(LLMPurpose) == 22

    @pytest.mark.parametrize("purpose", list(LLMPurpose))
    def test_purpose_value_is_valid_field(self, purpose: LLMPurpose) -> None:
        cfg = _make_llm_config()
        assert hasattr(cfg, purpose.value), (
            f"LLMPurpose.{purpose.name} maps to '{purpose.value}' "
            f"which is not a field on LLMConfig"
        )

    def test_purpose_values_are_unique(self) -> None:
        values = [p.value for p in LLMPurpose]
        assert len(values) == len(set(values))

    def test_specific_purpose_names(self) -> None:
        assert LLMPurpose.SUMMARY.value == "llm_summary_model"
        assert LLMPurpose.MARKDOWN_VALIDATOR.value == "llm_markdown_validator_model"
        assert LLMPurpose.THEME_FRESHNESS_CHECK.value == "llm_theme_freshness_check_model"


# ---------------------------------------------------------------------------
# get_model() function
# ---------------------------------------------------------------------------


class TestGetModel:
    """get_model() should return the correct model for each purpose."""

    def test_returns_default_model(self) -> None:
        get_llm_config.cache_clear()
        with patch.dict("os.environ", {}, clear=False):
            model = get_model(LLMPurpose.SUMMARY)
        assert model == "google/gemini-2.5-flash"

    def test_returns_overridden_model(self) -> None:
        get_llm_config.cache_clear()
        with patch.dict("os.environ", {"LLM_SUMMARY_MODEL": "meta/llama-3"}, clear=False):
            model = get_model(LLMPurpose.SUMMARY)
        assert model == "meta/llama-3"

    def test_validator_uses_gpt(self) -> None:
        get_llm_config.cache_clear()
        with patch.dict("os.environ", {}, clear=False):
            model = get_model(LLMPurpose.MARKDOWN_VALIDATOR)
        assert model == "openai/gpt-4.1"

    def test_freshness_uses_gemini(self) -> None:
        get_llm_config.cache_clear()
        with patch.dict("os.environ", {}, clear=False):
            model = get_model(LLMPurpose.THEME_FRESHNESS_CHECK)
        assert model == "google/gemini-2.5-flash"

    @pytest.mark.parametrize("purpose", list(LLMPurpose))
    def test_every_purpose_returns_string(self, purpose: LLMPurpose) -> None:
        get_llm_config.cache_clear()
        with patch.dict("os.environ", {}, clear=False):
            result = get_model(purpose)
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# get_model() 3-tier resolution: env var > JSON config > hardcoded default
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
        "prompts": {"system": "Test system.", "instruction": "Test instruction."},
        "metadata": {"googleDocId": None, "lastSyncedAt": None, "version": 1},
    }
    path = tmp_path / f"{process_name}-llm.json"
    path.write_text(json.dumps(data))


class TestGetModelThreeTier:
    """get_model() should resolve models with env var > JSON config > default."""

    def test_json_config_overrides_hardcoded_default(self, tmp_path: Path) -> None:
        """Tier 2 (JSON) wins over tier 3 (hardcoded default)."""
        from ica.llm_configs import loader

        _write_json_config(tmp_path, "summarization", model="custom/json-model")
        loader._cache.clear()

        get_llm_config.cache_clear()
        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            patch.dict("os.environ", {}, clear=False),
        ):
            model = get_model(LLMPurpose.SUMMARY)

        assert model == "custom/json-model"

    def test_env_var_overrides_json_config(self, tmp_path: Path) -> None:
        """Tier 1 (env var) wins over tier 2 (JSON config)."""
        from ica.llm_configs import loader

        _write_json_config(tmp_path, "summarization", model="custom/json-model")
        loader._cache.clear()

        get_llm_config.cache_clear()
        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            patch.dict(
                "os.environ",
                {"LLM_SUMMARY_MODEL": "env/override-model"},
                clear=False,
            ),
        ):
            model = get_model(LLMPurpose.SUMMARY)

        assert model == "env/override-model"

    def test_missing_json_falls_back_to_default(self, tmp_path: Path) -> None:
        """When JSON file is missing, fall back to hardcoded default."""
        from ica.llm_configs import loader

        loader._cache.clear()

        get_llm_config.cache_clear()
        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            patch.dict("os.environ", {}, clear=False),
        ):
            model = get_model(LLMPurpose.SUMMARY)

        assert model == "anthropic/claude-sonnet-4.5"

    def test_learning_data_purposes_resolve_via_json(self) -> None:
        """Learning-data purposes resolve to JSON config model (gemini-flash)."""
        get_llm_config.cache_clear()
        with patch.dict("os.environ", {}, clear=False):
            model = get_model(LLMPurpose.MARKDOWN_LEARNING_DATA)

        assert model == "google/gemini-2.5-flash"

    def test_json_config_for_non_default_model(self, tmp_path: Path) -> None:
        """Verify JSON works for purposes with non-sonnet defaults (e.g. GPT)."""
        from ica.llm_configs import loader

        _write_json_config(
            tmp_path,
            "markdown-structural-validation",
            model="custom/better-validator",
        )
        loader._cache.clear()

        get_llm_config.cache_clear()
        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            patch.dict("os.environ", {}, clear=False),
        ):
            model = get_model(LLMPurpose.MARKDOWN_VALIDATOR)

        assert model == "custom/better-validator"

    def test_json_config_for_freshness_check(self, tmp_path: Path) -> None:
        """Verify JSON works for freshness check (default is Gemini Flash)."""
        from ica.llm_configs import loader

        _write_json_config(tmp_path, "freshness-check", model="custom/fast-checker")
        loader._cache.clear()

        get_llm_config.cache_clear()
        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            patch.dict("os.environ", {}, clear=False),
        ):
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

    def test_all_mapped_keys_are_valid_llm_config_fields(self) -> None:
        """Every key in the mapping should be a valid LLMConfig field."""
        for field_name in _PURPOSE_TO_PROCESS:
            assert field_name in LLMConfig.model_fields, (
                f"_PURPOSE_TO_PROCESS key {field_name!r} is not an LLMConfig field"
            )

    def test_mapping_covers_22_purposes(self) -> None:
        """All 22 purposes have JSON config mappings."""
        assert len(_PURPOSE_TO_PROCESS) == 22


# ---------------------------------------------------------------------------
# get_llm_config() cache
# ---------------------------------------------------------------------------


class TestGetLLMConfig:
    """get_llm_config() should return a cached singleton."""

    def test_returns_llm_config_instance(self) -> None:
        get_llm_config.cache_clear()
        with patch.dict("os.environ", {}, clear=False):
            cfg = get_llm_config()
        assert isinstance(cfg, LLMConfig)

    def test_returns_same_instance(self) -> None:
        get_llm_config.cache_clear()
        with patch.dict("os.environ", {}, clear=False):
            cfg1 = get_llm_config()
            cfg2 = get_llm_config()
        assert cfg1 is cfg2


# ---------------------------------------------------------------------------
# Model identifier format
# ---------------------------------------------------------------------------


class TestModelFormat:
    """Default model IDs should follow the provider/model format."""

    @pytest.mark.parametrize("purpose", list(LLMPurpose))
    def test_default_contains_slash(self, purpose: LLMPurpose) -> None:
        cfg = _make_llm_config()
        model_id = getattr(cfg, purpose.value)
        assert "/" in model_id

    @pytest.mark.parametrize("purpose", list(LLMPurpose))
    def test_default_non_empty(self, purpose: LLMPurpose) -> None:
        cfg = _make_llm_config()
        model_id = getattr(cfg, purpose.value)
        assert model_id.strip() != ""


# ---------------------------------------------------------------------------
# Package re-exports
# ---------------------------------------------------------------------------


class TestPackageExport:
    """ica.config should re-export LLM config items."""

    def test_import_llm_config(self) -> None:
        from ica.config import LLMConfig as C

        assert C is LLMConfig

    def test_import_llm_purpose(self) -> None:
        from ica.config import LLMPurpose as P

        assert P is LLMPurpose

    def test_import_get_llm_config(self) -> None:
        from ica.config import get_llm_config as f

        assert f is get_llm_config

    def test_import_get_model(self) -> None:
        from ica.config import get_model as f

        assert f is get_model
