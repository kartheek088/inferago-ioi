"""Application configuration, read from environment variables (and an optional .env file).

Secrets (API token, OpenRouter key, Reddit credentials) are only ever read from the
environment; nothing secret is stored in the database or committed.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IOI_",
        env_file=(str(REPO_DIR / ".env"), str(BACKEND_DIR / ".env")),
        extra="ignore",
    )

    database_url: str = f"sqlite:///{BACKEND_DIR / 'data' / 'ioi.db'}"
    host: str = "127.0.0.1"
    port: int = 8000
    # Shared-secret bearer token. Required whenever host is not loopback.
    api_token: str | None = None
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Scheduler is opt-in.
    scheduler_enabled: bool = False

    # Outbound HTTP safety limits
    http_timeout_seconds: float = 15.0
    http_max_bytes: int = 5 * 1024 * 1024
    http_user_agent: str = "InferagoIOI/0.1 (internal research tool; respects robots.txt)"
    # Only for tests / local development: allow fetching private network addresses.
    allow_private_network: bool = False

    upload_max_bytes: int = 20 * 1024 * 1024
    upload_dir: str = str(BACKEND_DIR / "data" / "uploads")

    # Optional AI (OpenRouter). The app runs fully without these.
    openrouter_api_key: str | None = None
    openrouter_model: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_seconds: float = 60.0
    openrouter_max_retries: int = 2

    # Reddit is credential-gated. Without these the adapter stays disabled.
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str | None = None

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openrouter_api_key and self.openrouter_model)

    @property
    def reddit_configured(self) -> bool:
        return bool(self.reddit_client_id and self.reddit_client_secret and self.reddit_user_agent)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
