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

    # MEMORIA_DATA_SOURCE. "fixtures" serves the fictional records in
    # backend.providers.fixture_data; "database" reads PostgreSQL. Identities
    # follow the same choice (see docs/api-contracts.md, "Identity and permissions").
    data_source: Literal["fixtures", "database"] = Field(
        default="fixtures",
        validation_alias=AliasChoices("MEMORIA_DATA_SOURCE", "data_source"),
    )

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
