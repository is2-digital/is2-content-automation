"""Pydantic Settings class for ica configuration.

All environment variables from PRD Section 8.2 are mapped here.
Values are loaded from environment variables and/or .env files.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Environment variable names match the field names (case-insensitive).
    A .env file in the project root is loaded automatically if present.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- PostgreSQL ---
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "n8n_custom_data"
    postgres_user: str = "ica"
    postgres_password: str

    # --- OpenRouter / LLM ---
    openrouter_api_key: str

    # --- Slack ---
    slack_bot_token: str
    slack_app_token: str
    slack_channel: str

    # --- Google APIs ---
    google_service_account_credentials_path: Path = Path(
        "/app/credentials/google-service-account.json"
    )

    # --- Google Custom Search ---
    google_cse_api_key: str
    google_cse_cx: str

    # --- Google Sheets ---
    google_sheets_spreadsheet_id: str = ""

    # --- Google Shared Drive ---
    # The service account has no Drive storage quota of its own, so all files
    # (Docs, Sheets) must be created inside a Shared Drive.  Set this to the
    # Shared Drive ID (from the URL or Drive API).  If empty, the app will
    # auto-discover the first Shared Drive accessible to the service account.
    google_shared_drive_id: str = ""

    # --- HTML template ---
    html_template_path: str = ""

    # --- General ---
    timezone: str = "America/Los_Angeles"

    # --- Logging ---
    log_level: str = "INFO"
    log_format: str = "text"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """Async PostgreSQL connection URL for SQLAlchemy."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url_sync(self) -> str:
        """Synchronous PostgreSQL connection URL (for Alembic migrations)."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Use this as a FastAPI dependency or call directly. The instance
    is created once and reused for the lifetime of the process.
    """
    return Settings()
