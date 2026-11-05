"""Password hashing and JWT handling.

bcrypt for passwords (12 rounds), PyJWT HS256 for tokens. No password or hash
is ever logged or returned by the API.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import settings

_BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    if not password:
        raise ValueError("password must not be empty")
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time password check. Returns False on any malformed input."""
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str, extra: dict | None = None) -> tuple[str, int]:
    """Create a signed JWT. Returns (token, expires_in_seconds)."""
    expires_in = settings.access_token_expire_minutes * 60
    now = datetime.now(UTC)
    payload: dict = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "iss": settings.app_name,
    }
    if extra:
        payload.update(extra)
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT. Raises jwt.PyJWTError on any problem."""
    return jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.jwt_algorithm],
        issuer=settings.app_name,
    )
