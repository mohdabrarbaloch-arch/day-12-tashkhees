"""Report routes: compose a report from an analysis, fetch reports."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.engine import report as report_engine
from app.engine.analyze import AnalysisResult, Finding
from app.models import Analysis, Report, Study, User
from app.schemas import ReportOut

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _owned_study(study_id: int, db: Session, user: User) -> Study:
    study = db.get(Study, study_id)
    if study is None or study.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Study not found")
    return study


def _result_from_analysis(analysis: Analysis) -> AnalysisResult:
    """Rebuild an AnalysisResult from persisted rows so the report builder is pure."""
    import json

    findings = [
        Finding(
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
        for f in analysis.findings
    ]
    return AnalysisResult(
        engine=analysis.engine,
        engine_version=analysis.engine_version,
        quality=json.loads(analysis.quality_json or "{}"),
        findings=findings,
        measurements=json.loads(analysis.measurements_json or "{}"),
        summary=analysis.summary,
        abnormal_count=analysis.abnormal_count,
        overall_confidence=analysis.overall_confidence,
    )


@router.post("/{study_id}", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
def generate_report(
    study_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReportOut:
    """Compose a report from the study's latest analysis."""
    study = _owned_study(study_id, db, user)
    analysis = db.scalar(
        select(Analysis).where(Analysis.study_id == study.id).order_by(Analysis.id.desc()).limit(1)
    )
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run an analysis before generating a report",
        )

    draft = report_engine.build_report(_result_from_analysis(analysis))
    report = Report(
        study_id=study.id,
        analysis_id=analysis.id,
        title=draft.title,
        impression=draft.impression,
        findings_text=draft.findings_text,
        technique=draft.technique,
        disclaimer=draft.disclaimer,
        abnormal_count=draft.abnormal_count,
        overall_confidence=draft.overall_confidence,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return ReportOut.model_validate(report)


@router.get("/{study_id}", response_model=ReportOut)
def latest_report(
    study_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReportOut:
    """Return the most recent report for a study."""
    study = _owned_study(study_id, db, user)
    report = db.scalar(select(Report).where(Report.study_id == study.id).order_by(Report.id.desc()).limit(1))
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No report exists for this study")
    return ReportOut.model_validate(report)


@router.get("/{study_id}/all", response_model=list[ReportOut])
def all_reports(
    study_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ReportOut]:
    """Return every report for a study, oldest first."""
    study = _owned_study(study_id, db, user)
    rows = db.scalars(select(Report).where(Report.study_id == study.id).order_by(Report.id.asc())).all()
    return [ReportOut.model_validate(r) for r in rows]
