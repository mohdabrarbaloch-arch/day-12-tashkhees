"""Health and metadata routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.engine.analyze import ENGINE_NAME, ENGINE_VERSION, REFERENCE_RANGES
from app.engine.report import DISCLAIMER
from app.schemas import HealthOut

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthOut)
def health(db: Session = Depends(get_db)) -> HealthOut:
    """Liveness probe. Reports database reachability and the active engine."""
    db_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - health must never raise
        db_status = "unavailable"

    return HealthOut(
        status="ok" if db_status == "ok" else "degraded",
        app=settings.app_name,
        environment=settings.environment,
        engine=ENGINE_NAME,
        engine_version=ENGINE_VERSION,
        database=db_status,
        disclaimer=DISCLAIMER,
    )


@router.get("/engine/reference-ranges")
def reference_ranges() -> dict:
    """Expose the reference ranges so the UI can render them without hardcoding."""
    return {
        "engine": ENGINE_NAME,
        "version": ENGINE_VERSION,
        "ranges": [
            {
                "key": r.key,
                "label": r.label,
                "low": r.low,
                "high": r.high,
                "unit": r.unit,
                "breach_label": r.breach_label,
            }
            for r in REFERENCE_RANGES
        ],
    }
