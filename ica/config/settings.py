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
    postgres_host: str = "localhost"
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
    google_sheets_credentials_path: Path
    google_docs_credentials_path: Path

    # --- SearchApi ---
    searchapi_api_key: str

    # --- General ---
    timezone: str = "America/Los_Angeles"

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
    return Settings()  # type: ignore[call-arg]
