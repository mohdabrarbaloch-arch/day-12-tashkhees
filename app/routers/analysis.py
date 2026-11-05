"""Analysis routes: run the engine over a study, fetch results."""

from __future__ import annotations

import io
import json
import os

from fastapi import APIRouter, Depends, HTTPException, status
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.engine import analyze as engine
from app.models import Analysis, Finding, Study, User
from app.schemas import AnalysisOut, FindingOut

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def _owned_study(study_id: int, db: Session, user: User) -> Study:
    study = db.get(Study, study_id)
    if study is None or study.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Study not found")
    return study


def _to_out(analysis: Analysis) -> AnalysisOut:
    return AnalysisOut(
        id=analysis.id,
        study_id=analysis.study_id,
        engine=analysis.engine,
        engine_version=analysis.engine_version,
        quality_score=analysis.quality_score,
        summary=analysis.summary,
        abnormal_count=analysis.abnormal_count,
        overall_confidence=analysis.overall_confidence,
        created_at=analysis.created_at,
        findings=[FindingOut.model_validate(f) for f in analysis.findings],
    )


@router.post("/{study_id}", response_model=AnalysisOut, status_code=status.HTTP_201_CREATED)
def run_analysis(
    study_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AnalysisOut:
    """Run the measurement engine over a stored study and persist the findings."""
    study = _owned_study(study_id, db, user)
    if not os.path.exists(study.stored_path):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Stored image is no longer available")

    try:
        with Image.open(study.stored_path) as img:
            img.load()
            result = engine.run_analysis(img)
    except (UnidentifiedImageError, OSError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Stored image could not be decoded for analysis",
        ) from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None

    analysis = Analysis(
        study_id=study.id,
        engine=result.engine,
        engine_version=result.engine_version,
        quality_score=float(result.quality.get("score", 0.0)),
        quality_json=json.dumps(result.quality),
        measurements_json=json.dumps(result.measurements),
        summary=result.summary,
        abnormal_count=result.abnormal_count,
        overall_confidence=result.overall_confidence,
    )
    db.add(analysis)
    db.flush()

    for f in result.findings:
        db.add(
            Finding(
                analysis_id=analysis.id,
                key=f.key,
                label=f.label,
                value=f.value,
                unit=f.unit,
                ref_low=f.ref_low,
                ref_high=f.ref_high,
                flag=f.flag,
                confidence=f.confidence,
                note=f.note,
            )
        )
    db.commit()
    db.refresh(analysis)
    return _to_out(analysis)


@router.get("/{study_id}", response_model=AnalysisOut)
def latest_analysis(
    study_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AnalysisOut:
    """Return the most recent analysis for a study."""
    study = _owned_study(study_id, db, user)
    analysis = db.scalar(
        select(Analysis).where(Analysis.study_id == study.id).order_by(Analysis.id.desc()).limit(1)
    )
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No analysis exists for this study")
    return _to_out(analysis)


@router.get("/{study_id}/all", response_model=list[AnalysisOut])
def all_analyses(
    study_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AnalysisOut]:
    """Return every analysis run for a study, oldest first."""
    study = _owned_study(study_id, db, user)
    rows = db.scalars(select(Analysis).where(Analysis.study_id == study.id).order_by(Analysis.id.asc())).all()
    return [_to_out(a) for a in rows]


@router.get("/{study_id}/overlay")
def analysis_overlay(
    study_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return a PNG showing the segmented lung fields the engine measured."""
    from fastapi.responses import Response

    study = _owned_study(study_id, db, user)
    if not os.path.exists(study.stored_path):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Stored image is no longer available")

    from app.engine import imaging

    with Image.open(study.stored_path) as img:
        arr = imaging.load_grayscale(img)
    arr = imaging.resize_max(arr, max_side=1024)
    arr = imaging.normalize_contrast(arr)
    overlay = imaging.build_overlay(arr)

    buf = io.BytesIO()
    Image.fromarray(overlay, mode="RGB").save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")
