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
REPO_ROOT = BACKEND_DIR.parent


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
    data_dir: Path = REPO_ROOT / "data"
    """Holds ``seed/`` (committed real-data snapshots) and ``cache/`` (raw responses, ignored)."""
    scheduler_enabled: bool = True
    """Run the background refresh jobs (ignored when offline)."""
    fail_sources: list[str] = []
    """Sources to treat as down, for demonstrating the STALE badge (e.g. ``["fred"]``)."""
    http_timeout_s: float = 30.0
    sim_enabled: bool = True
    """Run the live tick loop (the markets are still built when disabled, for commands)."""
    sim_seed: int | None = None
    """Fix the random seed to make a session reproducible."""
    static_dir: Path | None = None
    """Serve the built terminal from here, on the API's own origin (the one-service image)."""

    @property
    def seed_dir(self) -> Path:
        return self.data_dir / "seed"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def replay_dir(self) -> Path:
        return self.data_dir / "replays"


@lru_cache
def get_settings() -> Settings:
    return Settings()
