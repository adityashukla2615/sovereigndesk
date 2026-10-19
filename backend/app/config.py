"""Runtime settings, read from the environment and ``backend/.env``.

Every variable takes an ``SD_`` prefix except ``FRED_API_KEY``, which keeps the name FRED
documents. Secrets are ``SecretStr`` so they never show up in reprs, logs or API responses.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SD_",
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    fred_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("FRED_API_KEY", "SD_FRED_API_KEY")
    )
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'var' / 'sovereigndesk.db').as_posix()}"
    redis_url: str | None = None
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    offline: bool = False
    """Boot from the seed snapshot only; never touch the network."""


@lru_cache
def get_settings() -> Settings:
    return Settings()
