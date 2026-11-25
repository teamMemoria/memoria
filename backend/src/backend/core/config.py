from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

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
    cors_origins: str = Field(
        default="",
        validation_alias=AliasChoices("MEMORIA_CORS_ORIGINS", "cors_origins"),
    )
    public_demo: bool = Field(
        default=False,
        validation_alias=AliasChoices("MEMORIA_PUBLIC_DEMO", "public_demo"),
    )
    demo_scorecard_file: Path | None = Field(
        default=None, validation_alias="MEMORIA_SIMULATION_FILE"
    )

    layer2_template_pilot: bool = False
    layer2_luna_review: str | None = None
    layer2_luna_followup: str | None = None
    layer2_policy_assessments: str | None = None
    layer2_policy_questions: str | None = None

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

    @property
    def demo_profile_selection_enabled(self) -> bool:
        return self.dev_identity_enabled or self.public_demo

    @property
    def allowed_cors_origins(self) -> list[str]:
        """Exact browser origins configured for the deployed frontend."""
        origins = [
            origin.strip().rstrip("/") for origin in self.cors_origins.split(",")
        ]
        for origin in filter(None, origins):
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
            ):
                raise ValueError(
                    "MEMORIA_CORS_ORIGINS must contain exact HTTP(S) origins"
                )
        return list(dict.fromkeys(origin for origin in origins if origin))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
