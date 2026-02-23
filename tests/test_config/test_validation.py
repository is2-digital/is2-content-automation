"""Tests for ica.config.validation."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ica.config.validation import ValidationResult, validate_config

# Minimal valid env vars required by Settings
_VALID_ENV = {
    "POSTGRES_PASSWORD": "secret",
    "OPENROUTER_API_KEY": "or-key-123",
    "SLACK_BOT_TOKEN": "xoxb-slack-bot",
    "SLACK_APP_TOKEN": "xapp-slack-app",
    "SLACK_CHANNEL": "C01234ABCDE",
    "GOOGLE_SHEETS_CREDENTIALS_PATH": "/creds/sheets.json",
    "GOOGLE_DOCS_CREDENTIALS_PATH": "/creds/docs.json",
    "SEARCHAPI_API_KEY": "sa-key-456",
}


def _validate_with_env(**overrides: str) -> ValidationResult:
    """Run validate_config with a controlled environment."""
    from ica.config.llm_config import get_llm_config
    from ica.config.settings import get_settings

    get_settings.cache_clear()
    get_llm_config.cache_clear()

    env = {**_VALID_ENV, **overrides}
    with patch.dict("os.environ", env, clear=True):
        return validate_config()


# ---------------------------------------------------------------------------
# ValidationResult dataclass
# ---------------------------------------------------------------------------


class TestValidationResult:
    """ValidationResult should be a frozen dataclass."""

    def test_ok_result(self) -> None:
        r = ValidationResult(ok=True)
        assert r.ok is True
        assert r.errors == ()

    def test_error_result(self) -> None:
        r = ValidationResult(ok=False, errors=("bad thing",))
        assert r.ok is False
        assert r.errors == ("bad thing",)

    def test_frozen(self) -> None:
        r = ValidationResult(ok=True)
        with pytest.raises(AttributeError):
            r.ok = False  # type: ignore[misc]

    def test_errors_is_tuple(self) -> None:
        r = ValidationResult(ok=False, errors=("a", "b"))
        assert isinstance(r.errors, tuple)


# ---------------------------------------------------------------------------
# Happy path — all valid
# ---------------------------------------------------------------------------


class TestHappyPath:
    """validate_config should pass with all valid settings."""

    def test_all_valid_returns_ok(self) -> None:
        result = _validate_with_env()
        assert result.ok is True
        assert result.errors == ()

    def test_with_valid_timezone_override(self) -> None:
        result = _validate_with_env(TIMEZONE="UTC")
        assert result.ok is True

    def test_with_valid_timezone_europe(self) -> None:
        result = _validate_with_env(TIMEZONE="Europe/London")
        assert result.ok is True


# ---------------------------------------------------------------------------
# Missing required settings
# ---------------------------------------------------------------------------


class TestMissingSettings:
    """validate_config should report missing required env vars."""

    @pytest.mark.parametrize("field", list(_VALID_ENV.keys()))
    def test_missing_required_field(self, field: str) -> None:
        from ica.config.llm_config import get_llm_config
        from ica.config.settings import get_settings

        get_settings.cache_clear()
        get_llm_config.cache_clear()

        env = {k: v for k, v in _VALID_ENV.items() if k != field}
        with patch.dict("os.environ", env, clear=True):
            result = validate_config()
        assert result.ok is False
        assert len(result.errors) >= 1
        # Error should mention the field
        assert any("Settings" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Invalid timezone
# ---------------------------------------------------------------------------


class TestTimezoneValidation:
    """validate_config should catch invalid IANA timezones."""

    def test_invalid_timezone(self) -> None:
        result = _validate_with_env(TIMEZONE="Not/A/Timezone")
        assert result.ok is False
        assert any("TIMEZONE" in e for e in result.errors)

    def test_empty_timezone(self) -> None:
        result = _validate_with_env(TIMEZONE="")
        assert result.ok is False
        assert any("TIMEZONE" in e for e in result.errors)

    def test_numeric_timezone(self) -> None:
        result = _validate_with_env(TIMEZONE="12345")
        assert result.ok is False


# ---------------------------------------------------------------------------
# LLM model format validation
# ---------------------------------------------------------------------------


class TestLLMModelValidation:
    """validate_config should catch malformed LLM model identifiers."""

    def test_model_without_slash_fails(self) -> None:
        result = _validate_with_env(LLM_SUMMARY_MODEL="just-a-model-name")
        assert result.ok is False
        assert any("/" in e and "llm_summary_model" in e for e in result.errors)

    def test_empty_model_fails(self) -> None:
        result = _validate_with_env(LLM_THEME_MODEL="")
        assert result.ok is False
        assert any("llm_theme_model" in e for e in result.errors)

    def test_whitespace_only_model_fails(self) -> None:
        result = _validate_with_env(LLM_EMAIL_PREVIEW_MODEL="   ")
        assert result.ok is False
        assert any("llm_email_preview_model" in e for e in result.errors)

    def test_valid_override_passes(self) -> None:
        result = _validate_with_env(LLM_SUMMARY_MODEL="meta/llama-3.1-70b")
        assert result.ok is True

    def test_multiple_model_errors_collected(self) -> None:
        result = _validate_with_env(
            LLM_SUMMARY_MODEL="bad",
            LLM_HTML_MODEL="also-bad",
        )
        assert result.ok is False
        assert len(result.errors) >= 2


# ---------------------------------------------------------------------------
# Package re-exports
# ---------------------------------------------------------------------------


class TestPackageExport:
    """ica.config should re-export validation items."""

    def test_import_validation_result(self) -> None:
        from ica.config import ValidationResult as VR
        assert VR is ValidationResult

    def test_import_validate_config(self) -> None:
        from ica.config import validate_config as vc
        assert vc is validate_config
