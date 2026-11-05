"""Application settings, loaded from the environment.

Every value has a safe development default. Production safety checks live in
`validate()` and are enforced at startup so a misconfigured deploy fails loudly
instead of silently running with a default secret.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_SECRET = "dev-insecure-secret-change-me"


def _env(key: str, default: str) -> str:
    value = os.environ.get(key)
    return value if value not in (None, "") else default


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_list(key: str, default: list[str]) -> list[str]:
    raw = os.environ.get(key)
    if raw in (None, ""):
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class Settings:
    app_name: str = "Tashkhees"
    environment: str = field(default_factory=lambda: _env("ENVIRONMENT", "development"))
    debug: bool = field(default_factory=lambda: _env_bool("DEBUG", False))

    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY", DEFAULT_SECRET))
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = field(
        default_factory=lambda: _env_int("ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24)
    )

    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "sqlite:///./tashkhees.db"))

    upload_dir: str = field(default_factory=lambda: _env("UPLOAD_DIR", "./uploads"))
    max_upload_bytes: int = field(default_factory=lambda: _env_int("MAX_UPLOAD_BYTES", 12 * 1024 * 1024))
    min_image_side: int = field(default_factory=lambda: _env_int("MIN_IMAGE_SIDE", 256))

    cors_origins: list[str] = field(
        default_factory=lambda: _env_list("CORS_ORIGINS", ["http://localhost:8012", "http://127.0.0.1:8012"])
    )

    rate_limit_auth: str = field(default_factory=lambda: _env("RATE_LIMIT_AUTH", "10/minute"))
    rate_limit_analysis: str = field(default_factory=lambda: _env("RATE_LIMIT_ANALYSIS", "20/minute"))
    rate_limit_default: str = field(default_factory=lambda: _env("RATE_LIMIT_DEFAULT", "120/minute"))

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in ("production", "prod")

    @property
    def is_serverless(self) -> bool:
        return bool(os.environ.get("VERCEL")) or bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))

    def validate(self) -> list[str]:
        """Return a list of fatal configuration problems (empty = OK)."""
        problems: list[str] = []
        if self.is_production:
            if self.secret_key == DEFAULT_SECRET:
                problems.append("SECRET_KEY must be set to a strong value in production")
            if len(self.secret_key) < 32:
                problems.append("SECRET_KEY must be at least 32 characters in production")
            if self.debug:
                problems.append("DEBUG must be false in production")
        if self.max_upload_bytes <= 0:
            problems.append("MAX_UPLOAD_BYTES must be positive")
        return problems


settings = Settings()
