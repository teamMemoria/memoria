from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from MEMORIA_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="MEMORIA_")

    # Defaults to production so development shortcuts are off unless someone opts in.
    app_env: Literal["development", "test", "production"] = "production"

    @property
    def dev_identity_enabled(self) -> bool:
        return self.app_env in ("development", "test")
