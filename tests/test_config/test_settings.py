"""Tests for ica.config.settings."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from ica.config.settings import Settings, get_settings

# Minimal valid env vars required to construct Settings
REQUIRED_ENV = {
    "POSTGRES_PASSWORD": "secret",
    "OPENROUTER_API_KEY": "or-key-123",
    "SLACK_BOT_TOKEN": "xoxb-slack-bot",
    "SLACK_APP_TOKEN": "xapp-slack-app",
    "SLACK_CHANNEL": "C01234ABCDE",
    "GOOGLE_SHEETS_CREDENTIALS_PATH": "/creds/sheets.json",
    "GOOGLE_DOCS_CREDENTIALS_PATH": "/creds/docs.json",
    "SEARCHAPI_API_KEY": "sa-key-456",
}


def _make_settings(**overrides: str) -> Settings:
    """Create a Settings instance with required env vars + overrides.

    Sets values via environment variables and bypasses .env file loading.
    """
    env = {**REQUIRED_ENV, **overrides}
    with patch.dict("os.environ", env, clear=False):
        return Settings(_env_file=None)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Construction with defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    """Settings should populate defaults for optional fields."""

    def test_postgres_host_default(self) -> None:
        s = _make_settings()
        assert s.postgres_host == "postgres"

    def test_postgres_port_default(self) -> None:
        s = _make_settings()
        assert s.postgres_port == 5432

    def test_postgres_db_default(self) -> None:
        s = _make_settings()
        assert s.postgres_db == "n8n_custom_data"

    def test_postgres_user_default(self) -> None:
        s = _make_settings()
        assert s.postgres_user == "ica"

    def test_timezone_default(self) -> None:
        s = _make_settings()
        assert s.timezone == "America/Los_Angeles"


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------


class TestRequiredFields:
    """Settings must raise if a required field is missing."""

    @pytest.mark.parametrize("field", list(REQUIRED_ENV.keys()))
    def test_missing_required_field_raises(self, field: str) -> None:
        env = {k: v for k, v in REQUIRED_ENV.items() if k != field}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(ValidationError):
                Settings(_env_file=None)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Override defaults
# ---------------------------------------------------------------------------


class TestOverrides:
    """Settings should accept overrides for every field."""

    def test_postgres_host_override(self) -> None:
        s = _make_settings(POSTGRES_HOST="db.prod.internal")
        assert s.postgres_host == "db.prod.internal"

    def test_postgres_port_override(self) -> None:
        s = _make_settings(POSTGRES_PORT="5433")
        assert s.postgres_port == 5433

    def test_postgres_db_override(self) -> None:
        s = _make_settings(POSTGRES_DB="custom_db")
        assert s.postgres_db == "custom_db"

    def test_postgres_user_override(self) -> None:
        s = _make_settings(POSTGRES_USER="admin")
        assert s.postgres_user == "admin"

    def test_timezone_override(self) -> None:
        s = _make_settings(TIMEZONE="UTC")
        assert s.timezone == "UTC"


# ---------------------------------------------------------------------------
# Required field values
# ---------------------------------------------------------------------------


class TestRequiredFieldValues:
    """Settings should store the provided values for required fields."""

    def test_postgres_password(self) -> None:
        s = _make_settings(POSTGRES_PASSWORD="p@$$w0rd!")
        assert s.postgres_password == "p@$$w0rd!"

    def test_openrouter_api_key(self) -> None:
        s = _make_settings(OPENROUTER_API_KEY="sk-or-v1-abc123")
        assert s.openrouter_api_key == "sk-or-v1-abc123"

    def test_slack_bot_token(self) -> None:
        s = _make_settings(SLACK_BOT_TOKEN="xoxb-my-bot")
        assert s.slack_bot_token == "xoxb-my-bot"

    def test_slack_app_token(self) -> None:
        s = _make_settings(SLACK_APP_TOKEN="xapp-my-app")
        assert s.slack_app_token == "xapp-my-app"

    def test_slack_channel(self) -> None:
        s = _make_settings(SLACK_CHANNEL="C999")
        assert s.slack_channel == "C999"

    def test_google_sheets_credentials_path(self) -> None:
        s = _make_settings(GOOGLE_SHEETS_CREDENTIALS_PATH="/opt/sheets.json")
        assert s.google_sheets_credentials_path == Path("/opt/sheets.json")

    def test_google_docs_credentials_path(self) -> None:
        s = _make_settings(GOOGLE_DOCS_CREDENTIALS_PATH="/opt/docs.json")
        assert s.google_docs_credentials_path == Path("/opt/docs.json")

    def test_searchapi_api_key(self) -> None:
        s = _make_settings(SEARCHAPI_API_KEY="sa-xyz")
        assert s.searchapi_api_key == "sa-xyz"


# ---------------------------------------------------------------------------
# Computed database URLs
# ---------------------------------------------------------------------------


class TestDatabaseUrl:
    """database_url and database_url_sync should be computed from parts."""

    def test_async_url_with_defaults(self) -> None:
        s = _make_settings()
        assert s.database_url == ("postgresql+asyncpg://ica:secret@postgres:5432/n8n_custom_data")

    def test_async_url_with_overrides(self) -> None:
        s = _make_settings(
            POSTGRES_USER="admin",
            POSTGRES_PASSWORD="hunter2",
            POSTGRES_HOST="db.example.com",
            POSTGRES_PORT="5433",
            POSTGRES_DB="mydb",
        )
        assert s.database_url == ("postgresql+asyncpg://admin:hunter2@db.example.com:5433/mydb")

    def test_sync_url_with_defaults(self) -> None:
        s = _make_settings()
        assert s.database_url_sync == ("postgresql://ica:secret@postgres:5432/n8n_custom_data")

    def test_sync_url_with_overrides(self) -> None:
        s = _make_settings(
            POSTGRES_USER="admin",
            POSTGRES_PASSWORD="hunter2",
            POSTGRES_HOST="db.example.com",
            POSTGRES_PORT="5433",
            POSTGRES_DB="mydb",
        )
        assert s.database_url_sync == ("postgresql://admin:hunter2@db.example.com:5433/mydb")

    def test_password_with_special_chars_in_url(self) -> None:
        s = _make_settings(POSTGRES_PASSWORD="p@ss/word#1")
        assert "p@ss/word#1" in s.database_url


# ---------------------------------------------------------------------------
# Type coercion
# ---------------------------------------------------------------------------


class TestTypeCoercion:
    """Pydantic should coerce string env values to proper types."""

    def test_port_string_to_int(self) -> None:
        s = _make_settings(POSTGRES_PORT="5433")
        assert isinstance(s.postgres_port, int)

    def test_credentials_path_string_to_path(self) -> None:
        s = _make_settings(GOOGLE_SHEETS_CREDENTIALS_PATH="/some/path.json")
        assert isinstance(s.google_sheets_credentials_path, Path)

    def test_invalid_port_raises(self) -> None:
        with pytest.raises(ValidationError):
            _make_settings(POSTGRES_PORT="not-a-number")


# ---------------------------------------------------------------------------
# Extra env vars are ignored
# ---------------------------------------------------------------------------


class TestExtraFields:
    """Settings with extra='ignore' should silently drop unknown env vars."""

    def test_unknown_env_var_ignored(self) -> None:
        s = _make_settings(SOME_RANDOM_VAR="value")
        assert not hasattr(s, "some_random_var")


# ---------------------------------------------------------------------------
# Environment variable loading
# ---------------------------------------------------------------------------


class TestEnvLoading:
    """Settings should read from environment variables."""

    def test_loads_from_env(self) -> None:
        env = {**REQUIRED_ENV, "TIMEZONE": "Europe/London"}
        with patch.dict("os.environ", env, clear=False):
            s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.timezone == "Europe/London"
        assert s.postgres_password == "secret"


# ---------------------------------------------------------------------------
# get_settings cache
# ---------------------------------------------------------------------------


class TestGetSettings:
    """get_settings() returns a cached singleton."""

    def test_returns_settings_instance(self) -> None:
        with patch.dict("os.environ", REQUIRED_ENV, clear=False):
            get_settings.cache_clear()
            s = get_settings()
        assert isinstance(s, Settings)

    def test_returns_same_instance(self) -> None:
        with patch.dict("os.environ", REQUIRED_ENV, clear=False):
            get_settings.cache_clear()
            s1 = get_settings()
            s2 = get_settings()
        assert s1 is s2


# ---------------------------------------------------------------------------
# Package re-export
# ---------------------------------------------------------------------------


class TestPackageExport:
    """ica.config should re-export Settings and get_settings."""

    def test_import_settings_from_config(self) -> None:
        from ica.config import Settings as S

        assert S is Settings

    def test_import_get_settings_from_config(self) -> None:
        from ica.config import get_settings as gs

        assert gs is get_settings
