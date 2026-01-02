"""Environment-backed application settings with strict validation."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Mapping

logger = logging.getLogger(__name__)

REQUIRED_ENV_VARS = (
    "DATABASE_URL",
    "AI_API_KEY",
    "SEARCH_API_KEY",
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
    "JWT_SECRET",
    "OTP_ISSUER_NAME",
)


def _read_env_var(name: str, env: Mapping[str, str | None]) -> str:
    value = env.get(name)
    if value is None or str(value).strip() == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return str(value)


@dataclass(frozen=True)
class Settings:
    database_url: str
    ai_api_key: str
    search_api_key: str
    alpaca_api_key: str
    alpaca_secret_key: str
    jwt_secret: str
    otp_issuer_name: str
    app_env: str


def load_settings(env: Mapping[str, str | None] | None = None) -> Settings:
    """Load and validate environment variables into a Settings object."""
    source_env = os.environ if env is None else env

    missing = [key for key in REQUIRED_ENV_VARS if not str(source_env.get(key) or "").strip()]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    app_env = str(source_env.get("APP_ENV", "development")).strip() or "development"

    settings = Settings(
        database_url=_read_env_var("DATABASE_URL", source_env),
        ai_api_key=_read_env_var("AI_API_KEY", source_env),
        search_api_key=_read_env_var("SEARCH_API_KEY", source_env),
        alpaca_api_key=_read_env_var("ALPACA_API_KEY", source_env),
        alpaca_secret_key=_read_env_var("ALPACA_SECRET_KEY", source_env),
        jwt_secret=_read_env_var("JWT_SECRET", source_env),
        otp_issuer_name=_read_env_var("OTP_ISSUER_NAME", source_env),
        app_env=app_env,
    )

    logger.info("Loaded application settings for env=%s", settings.app_env)
    return settings
