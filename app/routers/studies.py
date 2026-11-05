"""Study routes: upload, list, fetch, delete a radiograph."""

from __future__ import annotations

import io
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import ensure_upload_dir, get_db
from app.deps import get_current_user
from app.models import Study, User
from app.schemas import StudyListOut, StudyOut

router = APIRouter(prefix="/api/studies", tags=["studies"])

ALLOWED_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
ALLOWED_EXT = {"png", "jpg", "jpeg", "webp"}


def _ext_for(content_type: str, filename: str) -> str:
    if content_type in ("image/png",):
        return "png"
    if content_type in ("image/jpeg", "image/jpg"):
        return "jpg"
    if content_type == "image/webp":
        return "webp"
    ext = os.path.splitext(filename)[1].lstrip(".").lower()
    return ext if ext in ALLOWED_EXT else "png"


@router.post("", response_model=StudyOut, status_code=status.HTTP_201_CREATED)
async def create_study(
    file: UploadFile = File(...),
    patient_ref: str = Form(default=""),
    view: str = Form(default="PA"),
    notes: str = Form(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StudyOut:
    """Upload a chest radiograph.

    The bytes are decoded with Pillow to prove they are a real image — a renamed
    text file is rejected here rather than failing later inside the engine.
    """
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported content type '{content_type}'. Allowed: png, jpeg, webp.",
        )

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB limit",
        )

    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(raw)) as probe:
            width, height = probe.size
    except (UnidentifiedImageError, OSError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is not a decodable image",
        ) from None

    if min(width, height) < settings.min_image_side:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Image is too small ({width}x{height}); minimum side is {settings.min_image_side}px",
        )

    view_norm = (view or "PA").strip().upper()[:16] or "PA"
    if view_norm not in ("PA", "AP", "LATERAL", "LAT"):
        view_norm = "PA"

    upload_dir = ensure_upload_dir()
    ext = _ext_for(content_type, file.filename or "")
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    stored_path = os.path.join(upload_dir, stored_name)
    with open(stored_path, "wb") as fh:
        fh.write(raw)

    study = Study(
        owner_id=user.id,
        patient_ref=(patient_ref or "").strip()[:64],
        view=view_norm,
        notes=(notes or "").strip()[:2000],
        filename=(file.filename or stored_name)[:255],
        stored_path=stored_path,
        content_type=content_type,
        size_bytes=len(raw),
        width=width,
        height=height,
    )
    db.add(study)
    db.commit()
    db.refresh(study)
    return StudyOut.model_validate(study)


@router.get("", response_model=StudyListOut)
def list_studies(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StudyListOut:
    """List the caller's studies, newest first."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    total = db.scalar(select(func.count(Study.id)).where(Study.owner_id == user.id)) or 0
    rows = db.scalars(
        select(Study).where(Study.owner_id == user.id).order_by(Study.id.desc()).limit(limit).offset(offset)
    ).all()
    return StudyListOut(total=int(total), items=[StudyOut.model_validate(r) for r in rows])


def _owned_study(study_id: int, db: Session, user: User) -> Study:
    study = db.get(Study, study_id)
    if study is None or study.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Study not found")
    return study


@router.get("/{study_id}", response_model=StudyOut)
def get_study(
    study_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StudyOut:
    return StudyOut.model_validate(_owned_study(study_id, db, user))


@router.get("/{study_id}/image")
def get_study_image(
    study_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    """Serve the stored radiograph bytes to its owner."""
    study = _owned_study(study_id, db, user)
    if not os.path.exists(study.stored_path):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Stored image is no longer available")
    return FileResponse(study.stored_path, media_type=study.content_type, filename=study.filename)


@router.delete("/{study_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_study(
    study_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Delete a study, its analyses, reports, and the stored file.

    Returns an explicit empty ``Response``. A 204 must not carry a body, and
    FastAPI infers a response model from the return annotation — annotating
    this ``-> None`` makes it try to serialise ``null`` and the route fails to
    register at import time.
    """
    study = _owned_study(study_id, db, user)
    path = study.stored_path
    db.delete(study)
    db.commit()
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
    return Response(status_code=status.HTTP_204_NO_CONTENT)
