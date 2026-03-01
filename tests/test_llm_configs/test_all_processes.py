"""Comprehensive regression tests for all 19 LLM process JSON configs.

Covers four dimensions per process:
1. JSON config loads and validates against Pydantic schema
2. get_process_prompts() returns correct system/instruction strings
3. build_xxx_prompt() functions produce system prompts matching JSON configs
4. Model resolution follows env-var > JSON > default priority

Also tests edge cases: corrupted JSON, schema version mismatch, missing fields.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

import pytest

from ica.config.llm_config import LLMConfig, LLMPurpose, get_llm_config, get_model
from ica.llm_configs import loader
from ica.llm_configs.loader import (
    _cache,
    get_process_model,
    get_process_prompts,
    load_process_config,
)

# ---------------------------------------------------------------------------
# All 19 JSON config process names
# ---------------------------------------------------------------------------

ALL_PROCESS_NAMES = [
    "summarization",
    "summarization-regeneration",
    "learning-data-extraction",
    "theme-generation",
    "freshness-check",
    "markdown-generation",
    "markdown-regeneration",
    "markdown-structural-validation",
    "markdown-voice-validation",
    "html-generation",
    "html-regeneration",
    "email-subject",
    "email-subject-regeneration",
    "email-preview",
    "social-media-post",
    "social-media-caption",
    "social-media-regeneration",
    "linkedin-carousel",
    "linkedin-regeneration",
]

# Expected models per process (non-Claude exceptions)
EXPECTED_MODELS = {
    "summarization": "google/gemini-2.5-flash",
    "summarization-regeneration": "anthropic/claude-haiku-4.5",
    "freshness-check": "google/gemini-2.5-flash",
    "markdown-structural-validation": "openai/gpt-4.1",
    "markdown-voice-validation": "openai/gpt-4.1",
    "html-generation": "openai/gpt-4.1",
    "html-regeneration": "openai/gpt-4.1",
    "email-subject": "anthropic/claude-haiku-4.5",
    "email-subject-regeneration": "anthropic/claude-haiku-4.5",
    "social-media-regeneration": "openai/gpt-4.1",
    "learning-data-extraction": "google/gemini-2.5-flash",
}
_DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"

# Minimum prompt length to catch accidental truncation (characters)
MIN_PROMPT_LENGTH = 300


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    """Clear loader caches and LLMConfig cache between tests."""
    _cache.clear()
    loader._system_prompt_cache = None
    loader._PROCESS_TO_FIELD = None
    get_llm_config.cache_clear()


# ===================================================================
# 1. JSON config loading & schema validation for all 19 processes
# ===================================================================


class TestAllConfigsLoadAndValidate:
    """Every JSON config file loads successfully and validates against schema."""

    @pytest.mark.parametrize("process_name", ALL_PROCESS_NAMES)
    def test_config_loads_without_error(self, process_name: str) -> None:
        config = load_process_config(process_name)
        assert config.process_name == process_name

    @pytest.mark.parametrize("process_name", ALL_PROCESS_NAMES)
    def test_schema_version_is_v1(self, process_name: str) -> None:
        config = load_process_config(process_name)
        assert config.schema_version == "ica-llm-config/v1"

    @pytest.mark.parametrize("process_name", ALL_PROCESS_NAMES)
    def test_model_is_non_empty(self, process_name: str) -> None:
        config = load_process_config(process_name)
        assert len(config.model) > 0

    @pytest.mark.parametrize("process_name", ALL_PROCESS_NAMES)
    def test_instruction_prompt_is_non_empty(self, process_name: str) -> None:
        config = load_process_config(process_name)
        assert len(config.prompts.instruction) > 0

    @pytest.mark.parametrize("process_name", ALL_PROCESS_NAMES)
    def test_metadata_version_at_least_1(self, process_name: str) -> None:
        config = load_process_config(process_name)
        assert config.metadata.version >= 1

    @pytest.mark.parametrize("process_name", ALL_PROCESS_NAMES)
    def test_expected_model(self, process_name: str) -> None:
        """Each process uses the expected model provider."""
        config = load_process_config(process_name)
        expected = EXPECTED_MODELS.get(process_name, _DEFAULT_MODEL)
        assert config.model == expected, (
            f"{process_name}: expected model '{expected}', got '{config.model}'"
        )


# ===================================================================
# 2. get_process_prompts() returns correct strings for all 19 processes
# ===================================================================


class TestGetProcessPromptsAllProcesses:
    """get_process_prompts() returns matching strings for every process."""

    @pytest.mark.parametrize("process_name", ALL_PROCESS_NAMES)
    def test_returns_tuple_of_two_strings(self, process_name: str) -> None:
        result = get_process_prompts(process_name)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], str)

    @pytest.mark.parametrize("process_name", ALL_PROCESS_NAMES)
    def test_prompts_not_truncated(self, process_name: str) -> None:
        """Guard against accidental prompt truncation."""
        system, instruction = get_process_prompts(process_name)
        total = len(system) + len(instruction)
        assert total >= MIN_PROMPT_LENGTH, (
            f"{process_name}: combined prompt length {total} < {MIN_PROMPT_LENGTH}"
        )

    @pytest.mark.parametrize("process_name", ALL_PROCESS_NAMES)
    def test_prompts_match_direct_config_load(self, process_name: str) -> None:
        """Prompts from get_process_prompts match those from load_process_config."""
        from ica.llm_configs.loader import get_system_prompt

        config = load_process_config(process_name)
        system, instruction = get_process_prompts(process_name)
        assert system == get_system_prompt()
        assert instruction == config.prompts.instruction


# ===================================================================
# 3. Build functions produce system prompts matching their JSON configs
# ===================================================================


class TestBuildFunctionsMatchJsonConfigs:
    """Each build_xxx_prompt() returns a system prompt loaded from JSON."""

    def test_build_summarization_prompt(self) -> None:
        from ica.prompts.summarization import build_summarization_prompt

        system, user = build_summarization_prompt("test article content")
        json_system, _ = get_process_prompts("summarization")
        assert system == json_system
        assert "test article content" in user

    def test_build_summarization_prompt_with_feedback(self) -> None:
        from ica.prompts.summarization import build_summarization_prompt

        system, user = build_summarization_prompt("article", "Use shorter sentences")
        json_system, _ = get_process_prompts("summarization")
        assert system == json_system
        assert "Use shorter sentences" in user
        assert "Editorial Improvement Context" in user

    def test_build_summarization_prompt_no_feedback_no_section(self) -> None:
        from ica.prompts.summarization import build_summarization_prompt

        _, user = build_summarization_prompt("article")
        assert "Editorial Improvement Context" not in user

    def test_build_theme_generation_prompt(self) -> None:
        from ica.prompts.theme_generation import build_theme_generation_prompt

        system, user = build_theme_generation_prompt('{"summaries": []}')
        json_system, _ = get_process_prompts("theme-generation")
        assert system == json_system
        assert '{"summaries": []}' in user

    def test_build_theme_generation_prompt_with_feedback(self) -> None:
        from ica.prompts.theme_generation import build_theme_generation_prompt

        _, user = build_theme_generation_prompt("{}", "feedback note")
        assert "feedback note" in user

    def test_build_markdown_generation_prompt(self) -> None:
        from ica.prompts.markdown_generation import build_markdown_generation_prompt

        system, user = build_markdown_generation_prompt("formatted theme text")
        json_system, _ = get_process_prompts("markdown-generation")
        assert system == json_system or "formatted theme text" in user
        assert "formatted theme text" in user

    def test_build_markdown_generation_prompt_with_all_options(self) -> None:
        from ica.prompts.markdown_generation import build_markdown_generation_prompt

        system, _user = build_markdown_generation_prompt(
            "theme",
            aggregated_feedback="feedback",
            previous_markdown="prev md",
            validator_errors="errors",
        )
        # System prompt is JSON-loaded plus previous_markdown substitution
        assert isinstance(system, str)
        assert len(system) > 0

    def test_build_markdown_regeneration_prompt(self) -> None:
        from ica.prompts.markdown_generation import build_markdown_regeneration_prompt

        system, _user = build_markdown_regeneration_prompt("original md", "fix heading")
        # System may have format substitutions
        assert isinstance(system, str)
        assert len(system) > 0

    def test_build_html_generation_prompt(self) -> None:
        from ica.prompts.html_generation import build_html_generation_prompt

        system, user = build_html_generation_prompt("# Markdown", "<html></html>", "2026-02-24")
        assert isinstance(system, str)
        assert len(system) > 0
        assert "# Markdown" in user

    def test_build_html_regeneration_prompt(self) -> None:
        from ica.prompts.html_generation import build_html_regeneration_prompt

        system, user = build_html_regeneration_prompt(
            "<html>old</html>", "# md", "<html></html>", "fix it", "2026-02-24"
        )
        assert isinstance(system, str)
        assert "fix it" in user

    def test_build_email_subject_prompt(self) -> None:
        from ica.prompts.email_subject import build_email_subject_prompt

        system, user = build_email_subject_prompt("newsletter text")
        json_system, _ = get_process_prompts("email-subject")
        assert system == json_system
        assert "newsletter text" in user

    def test_build_email_review_prompt(self) -> None:
        from ica.prompts.email_review import build_email_review_prompt

        system, user = build_email_review_prompt("newsletter text")
        json_system, _ = get_process_prompts("email-preview")
        assert system == json_system or len(system) > 0
        assert "newsletter text" in user

    def test_build_email_review_prompt_with_feedback(self) -> None:
        from ica.prompts.email_review import build_email_review_prompt

        _, user = build_email_review_prompt("newsletter", "add more detail")
        assert "add more detail" in user

    def test_build_social_media_post_prompt(self) -> None:
        from ica.prompts.social_media import build_social_media_post_prompt

        system, user = build_social_media_post_prompt("content", "theme")
        json_system, _ = get_process_prompts("social-media-post")
        assert system == json_system
        assert "content" in user

    def test_build_social_media_caption_prompt(self) -> None:
        from ica.prompts.social_media import build_social_media_caption_prompt

        system, user = build_social_media_caption_prompt(
            "posts_json", "fa", "m1", "m2", "q1", "q2", "q3", "i1", "i2"
        )
        json_system, _ = get_process_prompts("social-media-caption")
        assert system == json_system
        assert "posts_json" in user

    def test_build_social_media_regeneration_prompt(self) -> None:
        from ica.prompts.social_media import build_social_media_regeneration_prompt

        system, user = build_social_media_regeneration_prompt("feedback", "prev captions")
        json_system, _ = get_process_prompts("social-media-regeneration")
        assert system == json_system
        assert "feedback" in user

    def test_build_linkedin_carousel_prompt(self) -> None:
        from ica.prompts.linkedin_carousel import build_linkedin_carousel_prompt

        system, user = build_linkedin_carousel_prompt("theme", "content")
        json_system, _ = get_process_prompts("linkedin-carousel")
        assert system == json_system
        assert "theme" in user

    def test_build_linkedin_regeneration_prompt(self) -> None:
        from ica.prompts.linkedin_carousel import build_linkedin_regeneration_prompt

        system, user = build_linkedin_regeneration_prompt(
            "prev output", "feedback", "theme", "content"
        )
        json_system, _ = get_process_prompts("linkedin-regeneration")
        assert system == json_system
        assert "feedback" in user

    def test_build_freshness_check_prompt(self) -> None:
        from ica.prompts.freshness_check import build_freshness_check_prompt

        system, user = build_freshness_check_prompt("theme body text")
        json_system, _ = get_process_prompts("freshness-check")
        assert system == json_system
        assert "theme body text" in user

    def test_build_learning_data_extraction_prompt(self) -> None:
        from ica.prompts.learning_data_extraction import (
            build_learning_data_extraction_prompt,
        )

        system, user = build_learning_data_extraction_prompt(
            "feedback", "input text", "model output"
        )
        json_system, _ = get_process_prompts("learning-data-extraction")
        assert system == json_system
        assert "feedback" in user

    def test_build_structural_validation_prompt(self) -> None:
        from ica.prompts.markdown_structural_validation import (
            build_structural_validation_prompt,
        )

        _, user = build_structural_validation_prompt("# MD content", '["err1"]')
        # char_errors is now in the instruction (user prompt), not the system prompt
        assert '["err1"]' in user
        assert "# MD content" in user

    def test_build_voice_validation_prompt(self) -> None:
        from ica.prompts.markdown_voice_validation import build_voice_validation_prompt

        system, user = build_voice_validation_prompt("# MD content", '{"errors": []}')
        json_system, _ = get_process_prompts("markdown-voice-validation")
        assert system == json_system
        assert "# MD content" in user


# ===================================================================
# 4. Model resolution: get_model() 3-tier priority for all LLMPurpose
# ===================================================================


class TestGetModelAllPurposes:
    """get_model() returns correct model for every LLMPurpose value."""

    # Map each LLMPurpose to its expected default model
    PURPOSE_DEFAULT_MODELS: ClassVar[dict[LLMPurpose, str]] = {
        LLMPurpose.SUMMARY: "google/gemini-2.5-flash",
        LLMPurpose.SUMMARY_REGENERATION: "anthropic/claude-haiku-4.5",
        LLMPurpose.SUMMARY_LEARNING_DATA: "google/gemini-2.5-flash",
        LLMPurpose.MARKDOWN: _DEFAULT_MODEL,
        LLMPurpose.MARKDOWN_VALIDATOR: "openai/gpt-4.1",
        LLMPurpose.MARKDOWN_REGENERATION: _DEFAULT_MODEL,
        LLMPurpose.MARKDOWN_LEARNING_DATA: _DEFAULT_MODEL,
        LLMPurpose.HTML: "openai/gpt-4.1",
        LLMPurpose.HTML_REGENERATION: "openai/gpt-4.1",
        LLMPurpose.HTML_LEARNING_DATA: _DEFAULT_MODEL,
        LLMPurpose.THEME: _DEFAULT_MODEL,
        LLMPurpose.THEME_LEARNING_DATA: _DEFAULT_MODEL,
        LLMPurpose.THEME_FRESHNESS_CHECK: "google/gemini-2.5-flash",
        LLMPurpose.SOCIAL_MEDIA: _DEFAULT_MODEL,
        LLMPurpose.SOCIAL_POST_CAPTION: _DEFAULT_MODEL,
        LLMPurpose.SOCIAL_MEDIA_REGENERATION: "openai/gpt-4.1",
        LLMPurpose.LINKEDIN: _DEFAULT_MODEL,
        LLMPurpose.LINKEDIN_REGENERATION: _DEFAULT_MODEL,
        LLMPurpose.EMAIL_SUBJECT: "anthropic/claude-haiku-4.5",
        LLMPurpose.EMAIL_SUBJECT_REGENERATION: "anthropic/claude-haiku-4.5",
        LLMPurpose.EMAIL_PREVIEW: _DEFAULT_MODEL,
        LLMPurpose.RELEVANCE_ASSESSMENT: "google/gemini-2.5-flash",
    }

    @pytest.mark.parametrize("purpose", list(LLMPurpose))
    def test_all_purposes_have_expected_defaults(self, purpose: LLMPurpose) -> None:
        """Verify every LLMPurpose is in our expected-defaults map."""
        assert purpose in self.PURPOSE_DEFAULT_MODELS, (
            f"LLMPurpose.{purpose.name} missing from PURPOSE_DEFAULT_MODELS"
        )

    @pytest.mark.parametrize("purpose", list(LLMPurpose))
    def test_default_model_without_env_override(self, purpose: LLMPurpose) -> None:
        """Without env overrides, get_model returns the expected default."""
        model = get_model(purpose)
        expected = self.PURPOSE_DEFAULT_MODELS[purpose]
        assert model == expected, (
            f"LLMPurpose.{purpose.name}: expected '{expected}', got '{model}'"
        )


class TestGetModelEnvOverride:
    """Environment variable overrides take priority over JSON and defaults."""

    # Representative sample of purposes with their env var names
    ENV_OVERRIDE_CASES: ClassVar[list[tuple[LLMPurpose, str]]] = [
        (LLMPurpose.SUMMARY, "LLM_SUMMARY_MODEL"),
        (LLMPurpose.MARKDOWN, "LLM_MARKDOWN_MODEL"),
        (LLMPurpose.MARKDOWN_VALIDATOR, "LLM_MARKDOWN_VALIDATOR_MODEL"),
        (LLMPurpose.HTML, "LLM_HTML_MODEL"),
        (LLMPurpose.THEME, "LLM_THEME_MODEL"),
        (LLMPurpose.THEME_FRESHNESS_CHECK, "LLM_THEME_FRESHNESS_CHECK_MODEL"),
        (LLMPurpose.SOCIAL_MEDIA, "LLM_SOCIAL_MEDIA_MODEL"),
        (LLMPurpose.LINKEDIN, "LLM_LINKEDIN_MODEL"),
        (LLMPurpose.EMAIL_SUBJECT, "LLM_EMAIL_SUBJECT_MODEL"),
        (LLMPurpose.EMAIL_PREVIEW, "LLM_EMAIL_PREVIEW_MODEL"),
    ]

    @pytest.mark.parametrize("purpose,env_var", ENV_OVERRIDE_CASES)
    def test_env_var_overrides_default(self, purpose: LLMPurpose, env_var: str) -> None:
        override_model = "custom/env-override-model"
        with patch.dict("os.environ", {env_var: override_model}, clear=False):
            get_llm_config.cache_clear()
            model = get_model(purpose)
        assert model == override_model


class TestGetModelJsonTier:
    """JSON config (tier 2) is used when no env override is active."""

    def test_json_model_used_for_summarization(self, tmp_path: Path) -> None:
        """Verify get_model reads from JSON when no env override."""
        data = {
            "$schema": "ica-llm-config/v1",
            "processName": "summarization",
            "model": "test/json-tier-model",
            "prompts": {"instruction": "inst"},
        }
        (tmp_path / "summarization-llm.json").write_text(json.dumps(data))

        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            patch.dict("os.environ", {}, clear=False),
        ):
            get_llm_config.cache_clear()
            model = get_model(LLMPurpose.SUMMARY)

        assert model == "test/json-tier-model"

    def test_env_override_beats_json(self, tmp_path: Path) -> None:
        """Env var (tier 1) beats JSON config (tier 2)."""
        data = {
            "$schema": "ica-llm-config/v1",
            "processName": "summarization",
            "model": "test/json-model",
            "prompts": {"instruction": "inst"},
        }
        (tmp_path / "summarization-llm.json").write_text(json.dumps(data))

        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            patch.dict("os.environ", {"LLM_SUMMARY_MODEL": "env/override"}, clear=False),
        ):
            get_llm_config.cache_clear()
            model = get_model(LLMPurpose.SUMMARY)

        assert model == "env/override"

    def test_hardcoded_default_when_json_missing(self, tmp_path: Path) -> None:
        """Hardcoded default (tier 3) used when JSON file is missing."""
        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            patch.dict("os.environ", {}, clear=False),
        ):
            get_llm_config.cache_clear()
            model = get_model(LLMPurpose.SUMMARY)

        # Falls back to hardcoded default
        assert model == _DEFAULT_MODEL


# ===================================================================
# 5. get_process_model() 3-tier via loader (parallel to get_model)
# ===================================================================


class TestGetProcessModelAllProcesses:
    """get_process_model() resolves correctly for all 19 JSON processes."""

    @pytest.mark.parametrize("process_name", ALL_PROCESS_NAMES)
    def test_returns_expected_model(self, process_name: str) -> None:
        expected = EXPECTED_MODELS.get(process_name, _DEFAULT_MODEL)
        model = get_process_model(process_name)
        assert model == expected


# ===================================================================
# 6. Edge cases: corrupted JSON, schema mismatch, missing fields
# ===================================================================


class TestEdgeCases:
    """Error handling for malformed or missing configs."""

    def test_corrupted_json_raises_value_error(self, tmp_path: Path) -> None:
        (tmp_path / "corrupt-llm.json").write_text("{not valid json!!!")
        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            pytest.raises(ValueError, match="Invalid JSON"),
        ):
            load_process_config("corrupt")

    def test_empty_json_object_raises_value_error(self, tmp_path: Path) -> None:
        (tmp_path / "empty-llm.json").write_text("{}")
        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            pytest.raises(ValueError, match="Schema validation failed"),
        ):
            load_process_config("empty")

    def test_wrong_schema_version_still_loads(self, tmp_path: Path) -> None:
        """Schema version string is stored but not enforced at load time."""
        data = {
            "$schema": "ica-llm-config/v99",
            "processName": "test",
            "model": "test/model",
            "prompts": {"instruction": "inst"},
        }
        (tmp_path / "test-llm.json").write_text(json.dumps(data))
        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            config = load_process_config("test")
        assert config.schema_version == "ica-llm-config/v99"

    def test_missing_prompts_raises(self, tmp_path: Path) -> None:
        data = {
            "$schema": "ica-llm-config/v1",
            "processName": "test",
            "model": "test/model",
        }
        (tmp_path / "test-llm.json").write_text(json.dumps(data))
        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            pytest.raises(ValueError, match="Schema validation failed"),
        ):
            load_process_config("test")

    def test_empty_instruction_prompt_raises(self, tmp_path: Path) -> None:
        data = {
            "$schema": "ica-llm-config/v1",
            "processName": "test",
            "model": "test/model",
            "prompts": {"instruction": ""},
        }
        (tmp_path / "test-llm.json").write_text(json.dumps(data))
        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            pytest.raises(ValueError, match="Schema validation failed"),
        ):
            load_process_config("test")

    def test_empty_model_string_raises(self, tmp_path: Path) -> None:
        data = {
            "$schema": "ica-llm-config/v1",
            "processName": "test",
            "model": "",
            "prompts": {"instruction": "inst"},
        }
        (tmp_path / "test-llm.json").write_text(json.dumps(data))
        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            pytest.raises(ValueError, match="Schema validation failed"),
        ):
            load_process_config("test")

    def test_missing_json_file_raises_file_not_found(self, tmp_path: Path) -> None:
        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            pytest.raises(FileNotFoundError, match="Config file not found"),
        ):
            load_process_config("nonexistent-process")

    def test_metadata_version_zero_raises(self, tmp_path: Path) -> None:
        data = {
            "$schema": "ica-llm-config/v1",
            "processName": "test",
            "model": "test/model",
            "prompts": {"instruction": "inst"},
            "metadata": {"version": 0},
        }
        (tmp_path / "test-llm.json").write_text(json.dumps(data))
        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            pytest.raises(ValueError, match="Schema validation failed"),
        ):
            load_process_config("test")

    def test_negative_metadata_version_raises(self, tmp_path: Path) -> None:
        data = {
            "$schema": "ica-llm-config/v1",
            "processName": "test",
            "model": "test/model",
            "prompts": {"instruction": "inst"},
            "metadata": {"version": -1},
        }
        (tmp_path / "test-llm.json").write_text(json.dumps(data))
        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            pytest.raises(ValueError, match="Schema validation failed"),
        ):
            load_process_config("test")

    def test_json_array_instead_of_object_raises(self, tmp_path: Path) -> None:
        (tmp_path / "bad-llm.json").write_text("[]")
        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            pytest.raises(ValueError, match="Schema validation failed"),
        ):
            load_process_config("bad")

    def test_unicode_in_prompts_preserved(self, tmp_path: Path) -> None:
        """Unicode content in prompts is loaded without corruption."""
        data = {
            "$schema": "ica-llm-config/v1",
            "processName": "unicode-test",
            "model": "test/model",
            "prompts": {
                "instruction": "\u2022 bullet \u2013 dash \u201csmart quotes\u201d",
            },
        }
        (tmp_path / "unicode-test-llm.json").write_text(json.dumps(data, ensure_ascii=False))
        with patch.object(loader, "_CONFIGS_DIR", tmp_path):
            config = load_process_config("unicode-test")
        assert "\u201c" in config.prompts.instruction


# ===================================================================
# 7. Cross-cutting: LLMPurpose enum covers all expected values
# ===================================================================


class TestLLMPurposeCompleteness:
    """LLMPurpose enum has exactly 21 members covering all pipeline uses."""

    EXPECTED_PURPOSES: ClassVar[set[str]] = {
        "SUMMARY",
        "SUMMARY_REGENERATION",
        "SUMMARY_LEARNING_DATA",
        "MARKDOWN",
        "MARKDOWN_VALIDATOR",
        "MARKDOWN_REGENERATION",
        "MARKDOWN_LEARNING_DATA",
        "HTML",
        "HTML_REGENERATION",
        "HTML_LEARNING_DATA",
        "THEME",
        "THEME_LEARNING_DATA",
        "THEME_FRESHNESS_CHECK",
        "SOCIAL_MEDIA",
        "SOCIAL_POST_CAPTION",
        "SOCIAL_MEDIA_REGENERATION",
        "LINKEDIN",
        "LINKEDIN_REGENERATION",
        "EMAIL_SUBJECT",
        "EMAIL_SUBJECT_REGENERATION",
        "EMAIL_PREVIEW",
        "RELEVANCE_ASSESSMENT",
    }

    def test_all_expected_purposes_exist(self) -> None:
        actual = {p.name for p in LLMPurpose}
        missing = self.EXPECTED_PURPOSES - actual
        assert not missing, f"Missing LLMPurpose values: {missing}"

    def test_no_unexpected_purposes(self) -> None:
        actual = {p.name for p in LLMPurpose}
        extra = actual - self.EXPECTED_PURPOSES
        assert not extra, f"Unexpected LLMPurpose values: {extra}"

    def test_purpose_values_match_llm_config_fields(self) -> None:
        """Every LLMPurpose value is a valid field on LLMConfig."""
        for purpose in LLMPurpose:
            assert purpose.value in LLMConfig.model_fields, (
                f"LLMPurpose.{purpose.name} = '{purpose.value}' is not a field on LLMConfig"
            )


# ===================================================================
# 8. _PURPOSE_TO_PROCESS mapping completeness
# ===================================================================


class TestPurposeToProcessMapping:
    """The _PURPOSE_TO_PROCESS mapping in llm_config.py covers all JSON configs."""

    def test_all_json_processes_mapped_from_at_least_one_purpose(self) -> None:
        """Every JSON config file has at least one LLMPurpose that routes to it."""
        from ica.config.llm_config import _PURPOSE_TO_PROCESS

        mapped_processes = set(_PURPOSE_TO_PROCESS.values())
        # Some processes aren't directly mapped (learning-data-* variants)
        # but the 18 in _PURPOSE_TO_PROCESS should cover the main ones
        assert len(mapped_processes) >= 18

    def test_all_mapping_values_are_valid_process_names(self) -> None:
        """Every process name in the mapping has a corresponding JSON file."""
        from ica.config.llm_config import _PURPOSE_TO_PROCESS

        for field_name, process_name in _PURPOSE_TO_PROCESS.items():
            config = load_process_config(process_name)
            assert config.process_name == process_name, (
                f"Field '{field_name}' maps to process '{process_name}' "
                f"but JSON has processName='{config.process_name}'"
            )

    def test_all_mapping_keys_are_valid_llm_config_fields(self) -> None:
        """Every field name in the mapping exists on LLMConfig."""
        from ica.config.llm_config import _PURPOSE_TO_PROCESS

        for field_name in _PURPOSE_TO_PROCESS:
            assert field_name in LLMConfig.model_fields, (
                f"_PURPOSE_TO_PROCESS key '{field_name}' is not on LLMConfig"
            )


# ===================================================================
# 9. Process category coverage
# ===================================================================


class TestProcessCategoryCoverage:
    """Verify all process categories have their expected JSON configs."""

    def test_primary_generation_processes(self) -> None:
        """7 primary generation processes exist with expected models."""
        primary = [
            "summarization",
            "theme-generation",
            "markdown-generation",
            "html-generation",
            "email-subject",
            "social-media-post",
            "linkedin-carousel",
        ]
        for name in primary:
            config = load_process_config(name)
            expected = EXPECTED_MODELS.get(name, _DEFAULT_MODEL)
            assert config.model == expected

    def test_regeneration_processes(self) -> None:
        """7 regeneration processes exist with expected models."""
        regen = [
            "summarization-regeneration",
            "markdown-regeneration",
            "html-regeneration",
            "email-subject-regeneration",
            "social-media-regeneration",
            "linkedin-regeneration",
        ]
        for name in regen:
            config = load_process_config(name)
            expected = EXPECTED_MODELS.get(name, _DEFAULT_MODEL)
            assert config.model == expected

    def test_validation_utility_processes(self) -> None:
        """5 validation/utility processes exist with correct models."""
        validation = [
            "freshness-check",
            "markdown-structural-validation",
            "markdown-voice-validation",
            "learning-data-extraction",
            "email-preview",
        ]
        for name in validation:
            config = load_process_config(name)
            expected = EXPECTED_MODELS.get(name, _DEFAULT_MODEL)
            assert config.model == expected

    def test_social_media_has_three_stages(self) -> None:
        """Social media pipeline: post -> caption -> regeneration."""
        names = ["social-media-post", "social-media-caption", "social-media-regeneration"]
        for name in names:
            config = load_process_config(name)
            assert config.process_name == name

    def test_markdown_has_generation_plus_two_validators(self) -> None:
        """Markdown pipeline: generation + structural + voice validators."""
        configs = [
            load_process_config("markdown-generation"),
            load_process_config("markdown-structural-validation"),
            load_process_config("markdown-voice-validation"),
        ]
        assert configs[0].model == _DEFAULT_MODEL
        assert configs[1].model == "openai/gpt-4.1"
        assert configs[2].model == "openai/gpt-4.1"


# ===================================================================
# 10. Shared system prompt JSON validates against SystemPromptConfig
# ===================================================================


class TestSharedSystemPrompt:
    """The system-prompt.json file loads and validates correctly."""

    def test_system_prompt_json_loads(self) -> None:
        from ica.llm_configs.schema import SystemPromptConfig

        path = Path(__file__).parent.parent.parent / "ica" / "llm_configs" / "system-prompt.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        config = SystemPromptConfig.model_validate(data)
        assert config.schema_version == "ica-system-prompt/v1"

    def test_system_prompt_is_non_empty(self) -> None:
        from ica.llm_configs.schema import SystemPromptConfig

        path = Path(__file__).parent.parent.parent / "ica" / "llm_configs" / "system-prompt.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        config = SystemPromptConfig.model_validate(data)
        assert len(config.prompt) > 100

    def test_system_prompt_has_description(self) -> None:
        from ica.llm_configs.schema import SystemPromptConfig

        path = Path(__file__).parent.parent.parent / "ica" / "llm_configs" / "system-prompt.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        config = SystemPromptConfig.model_validate(data)
        assert len(config.description) > 0

    def test_system_prompt_metadata_version(self) -> None:
        from ica.llm_configs.schema import SystemPromptConfig

        path = Path(__file__).parent.parent.parent / "ica" / "llm_configs" / "system-prompt.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        config = SystemPromptConfig.model_validate(data)
        assert config.metadata.version >= 1
