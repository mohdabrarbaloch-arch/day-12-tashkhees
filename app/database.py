"""Database engine, session factory, and declarative base.

SQLite for development, PostgreSQL for production — the ORM layer is identical.
On serverless platforms the filesystem is read-only except /tmp, so a SQLite URL
is transparently redirected there.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


def _resolve_url() -> str:
    url = settings.database_url
    # Serverless filesystems are read-only outside /tmp.
    if settings.is_serverless and url.startswith("sqlite") and "/tmp/" not in url:
        url = "sqlite:////tmp/tashkhees.db"
    return url


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        return {
            "connect_args": {"check_same_thread": False},
            "pool_pre_ping": True,
        }
    return {"pool_pre_ping": True, "pool_size": 5, "max_overflow": 10}


DATABASE_URL = _resolve_url()

engine = create_engine(DATABASE_URL, **_engine_kwargs(DATABASE_URL))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables. Safe to call repeatedly."""
    from app import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(bind=engine)


def ensure_upload_dir() -> str:
    """Create the upload directory, falling back to /tmp on serverless."""
    path = settings.upload_dir
    if settings.is_serverless and not path.startswith("/tmp"):
        path = "/tmp/tashkhees-uploads"
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        path = "/tmp/tashkhees-uploads"
        os.makedirs(path, exist_ok=True)
    return path
