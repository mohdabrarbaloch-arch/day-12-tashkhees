"""Seed the database with a demo account and a sample study.

Run once after setup:

    python scripts/seed.py

Idempotent — running it twice will not create duplicates. The sample study is a
synthetic radiograph generated in-process, so no external image is needed.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal, ensure_upload_dir, init_db  # noqa: E402
from app.models import Study, User  # noqa: E402
from app.security import hash_password  # noqa: E402

DEMO_EMAIL = "demo@tashkhees.pk"
DEMO_PASSWORD = "demo12345"


def synthetic_radiograph(width: int = 1024, height: int = 1024) -> Image.Image:
    """A chest-radiograph-like image for the demo study.

    Not a real patient image and not a diagnostic phantom — just enough
    structure for the engine to measure something meaningful.
    """
    arr = np.full((height, width), 0.04, dtype=np.float32)

    top, bottom = int(height * 0.08), int(height * 0.94)
    left, right = int(width * 0.12), int(width * 0.88)
    arr[top:bottom, left:right] = 0.45

    lung_top = top + int((bottom - top) * 0.10)
    lung_bottom = top + int((bottom - top) * 0.66)
    mid = (left + right) // 2
    band = max(3, int((right - left) * 0.06))
    arr[lung_top:lung_bottom, left + 12 : mid - band] = 0.24
    arr[lung_top:lung_bottom, mid + band : right - 12] = 0.27

    cy = top + int((bottom - top) * 0.60)
    rx = int((right - left) * 0.17)
    ry = int((bottom - top) * 0.16)
    yy, xx = np.ogrid[:height, :width]
    heart = ((xx - mid) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1.0
    arr[heart] = 0.85

    cp_top = top + int((bottom - top) * 0.62)
    cp_bottom = top + int((bottom - top) * 0.86)
    cp_w = max(3, int((right - left) * 0.18))
    arr[cp_top:cp_bottom, left : left + cp_w] = 0.22
    arr[cp_top:cp_bottom, right - cp_w : right] = 0.24

    # A little noise so the quality metrics have something real to chew on.
    rng = np.random.default_rng(42)
    arr = np.clip(arr + rng.normal(0, 0.012, arr.shape), 0, 1)
    return Image.fromarray((arr * 255).astype(np.uint8), mode="L")


def main() -> int:
    init_db()
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is None:
            user = User(
                email=DEMO_EMAIL,
                full_name="Demo Clinician",
                role="clinician",
                password_hash=hash_password(DEMO_PASSWORD),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"created demo user: {DEMO_EMAIL}")
        else:
            print(f"demo user already exists: {DEMO_EMAIL}")

        existing = db.scalar(select(Study).where(Study.owner_id == user.id))
        if existing is not None:
            print(f"demo study already exists (id={existing.id}) — nothing to do")
            return 0

        upload_dir = ensure_upload_dir()
        path = os.path.join(upload_dir, "demo-study.png")
        image = synthetic_radiograph()
        image.save(path, format="PNG")

        study = Study(
            owner_id=user.id,
            patient_ref="DEMO-0001",
            view="PA",
            notes="Synthetic sample study created by scripts/seed.py.",
            filename="demo-study.png",
            stored_path=path,
            content_type="image/png",
            size_bytes=os.path.getsize(path),
            width=image.width,
            height=image.height,
        )
        db.add(study)
        db.commit()
        db.refresh(study)
        print(f"created demo study (id={study.id}, {study.width}x{study.height})")
        print()
        print("Sign in with:")
        print(f"  email:    {DEMO_EMAIL}")
        print(f"  password: {DEMO_PASSWORD}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
