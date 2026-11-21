from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from the environment and the backend .env file."""

    database_url: str = "postgresql+psycopg://app:app@localhost:5432/callassist"

    # MEMORIA_APP_ENV. Defaults to production so development shortcuts are off
    # unless someone opts in.
    app_env: Literal["development", "test", "production"] = Field(
        default="production",
        validation_alias=AliasChoices("MEMORIA_APP_ENV", "app_env"),
    )

    knowledge_draft_threshold: int = Field(default=10, ge=1)
    knowledge_conflict_threshold_override: int | None = Field(default=None, ge=1)
    knowledge_recent_call_days: int = Field(default=30, ge=1)
    knowledge_stale_entry_days: int = Field(default=60, ge=1)

    @property
    def knowledge_conflict_threshold(self) -> int:
        if self.knowledge_conflict_threshold_override is not None:
            return self.knowledge_conflict_threshold_override
        return (self.knowledge_draft_threshold + 1) // 2

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def dev_identity_enabled(self) -> bool:
        return self.app_env in ("development", "test")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
