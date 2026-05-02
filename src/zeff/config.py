"""Runtime configuration loaded from environment."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide settings, loaded once from env / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(..., description="SQLAlchemy async DSN for Postgres.")
    log_level: str = Field(default="INFO", description="Standard Python log level.")


def get_settings() -> Settings:
    """Return a fresh Settings instance.

    Not cached so tests can mutate the environment between calls.
    """
    return Settings()
