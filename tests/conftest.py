"""Shared pytest fixtures.

Each test gets a fresh in-memory SQLite database and a fresh upload directory,
so tests never touch the developer's real data.
"""

from __future__ import annotations

import os
import tempfile

import numpy as np
import pytest
from PIL import Image

os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough-1234567890")
os.environ.setdefault("ENVIRONMENT", "development")


@pytest.fixture()
def tmp_upload_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("UPLOAD_DIR", d)
        yield d


@pytest.fixture()
def client(tmp_upload_dir, monkeypatch):
    """A TestClient bound to a fresh in-memory database."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.database as database

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", TestingSession)

    from app import models  # noqa: F401

    database.Base.metadata.create_all(bind=engine)

    from app.main import create_app

    application = create_app()
    with TestClient(application) as c:
        yield c


@pytest.fixture()
def auth_headers(client):
    """Register a user and return Authorization headers."""
    resp = client.post(
        "/api/auth/register",
        json={"email": "tester@tashkhees.pk", "password": "testpass123", "full_name": "Test User"},
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def make_radiograph(
    width: int = 512,
    height: int = 512,
    *,
    heart_scale: float = 1.0,
    left_density: float = 0.25,
    right_density: float = 0.25,
    cp_density: float = 0.20,
) -> Image.Image:
    """Synthesise a chest-radiograph-like image with controllable properties.

    This is a *test fixture*, not a diagnostic phantom. It produces a dark
    backdrop, a bright body, two darker lung fields whose mean intensity we can
    set, a bright cardiac silhouette whose width we can scale, and bottom-lateral
    bands whose density we can set. That is enough to exercise every measurement
    path deterministically.
    """
    arr = np.full((height, width), 0.04, dtype=np.float32)

    # Body: a bright rounded rectangle occupying most of the frame.
    top, bottom = int(height * 0.08), int(height * 0.94)
    left, right = int(width * 0.12), int(width * 0.88)
    arr[top:bottom, left:right] = 0.62

    # Lung fields: darker regions in the upper 2/3, split by a midline band.
    lung_top = top + int((bottom - top) * 0.10)
    lung_bottom = top + int((bottom - top) * 0.66)
    mid = (left + right) // 2
    band = max(3, int((right - left) * 0.06))

    arr[lung_top:lung_bottom, left + 6 : mid - band] = left_density
    arr[lung_top:lung_bottom, mid + band : right - 6] = right_density

    # Cardiac silhouette: a bright ellipse in the lower-middle thorax.
    cy = top + int((bottom - top) * 0.60)
    cx = mid
    rx = int((right - left) * 0.16 * heart_scale)
    ry = int((bottom - top) * 0.16)
    yy, xx = np.ogrid[:height, :width]
    heart = ((xx - cx) / max(rx, 1)) ** 2 + ((yy - cy) / max(ry, 1)) ** 2 <= 1.0
    arr[heart] = 0.88

    # Costophrenic bands: bottom-lateral rectangles.
    cp_top = top + int((bottom - top) * 0.62)
    cp_bottom = top + int((bottom - top) * 0.86)
    cp_w = max(3, int((right - left) * 0.18))
    arr[cp_top:cp_bottom, left : left + cp_w] = cp_density
    arr[cp_top:cp_bottom, right - cp_w : right] = cp_density

    arr = np.clip(arr, 0, 1)
    return Image.fromarray((arr * 255).astype(np.uint8), mode="L")


def png_bytes(image: Image.Image) -> bytes:
    import io

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
