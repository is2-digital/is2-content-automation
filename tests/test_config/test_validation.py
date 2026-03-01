"""Tests for ica.config.validation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ica.config.validation import ValidationResult, validate_config
from ica.llm_configs import loader
from ica.llm_configs.loader import _cache

# Minimal valid env vars required by Settings
_VALID_ENV = {
    "POSTGRES_PASSWORD": "secret",
    "OPENROUTER_API_KEY": "or-key-123",
    "SLACK_BOT_TOKEN": "xoxb-slack-bot",
    "SLACK_APP_TOKEN": "xapp-slack-app",
    "SLACK_CHANNEL": "C01234ABCDE",
}


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    """Clear loader caches between tests."""
    _cache.clear()
    loader._system_prompt_cache = None


def _validate_with_env(**overrides: str) -> ValidationResult:
    """Run validate_config with a controlled environment."""
    from ica.config.settings import get_settings

    get_settings.cache_clear()

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
        from ica.config.settings import get_settings

        get_settings.cache_clear()

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
# LLM JSON config validation
# ---------------------------------------------------------------------------


class TestLLMConfigValidation:
    """validate_config should catch malformed LLM JSON configs."""

    def test_missing_json_config_fails(self, tmp_path: Path) -> None:
        """Missing JSON config file is reported as error."""
        from ica.config.settings import get_settings

        get_settings.cache_clear()

        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            patch.dict("os.environ", _VALID_ENV, clear=True),
        ):
            result = validate_config()

        assert result.ok is False
        assert any("not found" in e for e in result.errors)

    def test_model_without_slash_fails(self, tmp_path: Path) -> None:
        """Model without provider/model separator is caught."""
        # Write all configs with valid models except one
        from ica.config.llm_config import _PURPOSE_TO_PROCESS

        seen: set[str] = set()
        for process_name in _PURPOSE_TO_PROCESS.values():
            if process_name in seen:
                continue
            seen.add(process_name)
            model = "bad-model-no-slash" if process_name == "summarization" else "ok/model"
            data = {
                "$schema": "ica-llm-config/v1",
                "processName": process_name,
                "model": model,
                "prompts": {"instruction": "test"},
            }
            (tmp_path / f"{process_name}-llm.json").write_text(json.dumps(data))

        # Also need system-prompt.json
        sp = {
            "$schema": "ica-system-prompt/v1",
            "description": "test",
            "prompt": "test system prompt",
            "metadata": {"version": 1},
        }
        (tmp_path / "system-prompt.json").write_text(json.dumps(sp))

        from ica.config.settings import get_settings

        get_settings.cache_clear()

        with (
            patch.object(loader, "_CONFIGS_DIR", tmp_path),
            patch.dict("os.environ", _VALID_ENV, clear=True),
        ):
            result = validate_config()

        assert result.ok is False
        assert any("summarization" in e and "/" in e for e in result.errors)

    def test_all_valid_json_configs_pass(self) -> None:
        """Real JSON configs all pass validation."""
        result = _validate_with_env()
        assert result.ok is True


# ---------------------------------------------------------------------------
# Package re-exports
# ---------------------------------------------------------------------------


class TestPackageExport:
    """ica.config should re-export validation items."""

    def test_import_validation_result(self) -> None:
        from ica.config import ValidationResult as ValidationResultAlias

        assert ValidationResultAlias is ValidationResult

    def test_import_validate_config(self) -> None:
        from ica.config import validate_config as vc

        assert vc is validate_config


# ---------------------------------------------------------------------------
# Email notification config validation
# ---------------------------------------------------------------------------


class TestEmailValidation:
    """validate_config should enforce email field dependencies."""

    def test_email_user_without_password_fails(self) -> None:
        result = _validate_with_env(
            EMAIL_SMTP_USER="user@gmail.com",
            EMAIL_FROM="user@gmail.com",
            EMAIL_TO="ops@example.com",
        )
        assert result.ok is False
        assert any("EMAIL_SMTP_PASSWORD" in e for e in result.errors)

    def test_email_user_without_from_fails(self) -> None:
        result = _validate_with_env(
            EMAIL_SMTP_USER="user@gmail.com",
            EMAIL_SMTP_PASSWORD="app-pass",
            EMAIL_TO="ops@example.com",
        )
        assert result.ok is False
        assert any("EMAIL_FROM" in e for e in result.errors)

    def test_email_user_without_to_fails(self) -> None:
        result = _validate_with_env(
            EMAIL_SMTP_USER="user@gmail.com",
            EMAIL_SMTP_PASSWORD="app-pass",
            EMAIL_FROM="user@gmail.com",
        )
        assert result.ok is False
        assert any("EMAIL_TO" in e for e in result.errors)

    def test_email_fully_configured_passes(self) -> None:
        result = _validate_with_env(
            EMAIL_SMTP_USER="user@gmail.com",
            EMAIL_SMTP_PASSWORD="app-pass",
            EMAIL_FROM="user@gmail.com",
            EMAIL_TO="ops@example.com",
        )
        assert result.ok is True

    def test_email_not_configured_passes(self) -> None:
        """No email env vars at all — should pass (opt-in)."""
        result = _validate_with_env()
        assert result.ok is True

    def test_email_user_without_all_required_collects_all_errors(self) -> None:
        result = _validate_with_env(EMAIL_SMTP_USER="user@gmail.com")
        assert result.ok is False
        assert len([e for e in result.errors if "EMAIL_" in e]) == 3
