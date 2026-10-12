from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings from environment variables (or a local .env file)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "vehicle_assistant"
    app_api_key: SecretStr  # required: the app refuses to start without it
    # "firestore" in the cloud; "memory" for quick local runs and unit tests.
    session_backend: Literal["firestore", "memory"] = "memory"


@lru_cache
def get_settings() -> Settings:
    return Settings()
