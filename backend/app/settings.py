"""
Environment-driven configuration for the VerdictLens API server.

All values can be overridden with environment variables or an ``.env`` file
placed alongside the process working directory.
"""

from __future__ import annotations

from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Server-wide settings loaded from environment variables.

    Prefix: ``VERDICTLENS_`` for all fields (via ``model_config``).
    """

    model_config = {"env_prefix": "VERDICTLENS_", "env_file": ".env", "extra": "ignore"}

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # --- Auth ---
    api_key: Optional[str] = None
    require_auth: bool = False
    allow_signup: bool = True

    # --- Workspace ---
    default_workspace: str = "default"

    # --- PostgreSQL (transactional data: auth, workspaces, prompts, alerts) ---
    database_url: str = "postgresql://koushik.reddy@localhost:5432/verdictlens"

    # --- ClickHouse (analytical data: traces, spans, metrics) ---
    ch_host: str = "localhost"
    ch_port: int = 8123
    ch_user: str = "default"
    ch_password: str = ""
    ch_database: str = "verdictlens"
    ch_secure: bool = False

    # --- Redis (for live WebSocket pub/sub) ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Playground safety limits ---
    playground_max_tokens: int = 4096
    playground_rate_limit: int = 10
    playground_rate_window: int = 60
    playground_max_cost_usd: float = 1.0

    @property
    def cors_origin_list(self) -> list[str]:
        """
        Parse comma-separated CORS origins into a list.

        :returns: List of allowed origins.
        """
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """
    Return the cached :class:`Settings` singleton (created on first call).

    :returns: Active settings.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
