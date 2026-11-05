"""Pydantic v2 request/response contracts.

These are the API's public shape. Validation lives here so routers stay thin.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(default="", max_length=255)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isalpha() for c in v) or not any(c.isdigit() for c in v):
            raise ValueError("password must contain at least one letter and one digit")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: str
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# --------------------------------------------------------------------------
# Studies
# --------------------------------------------------------------------------


class StudyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_ref: str
    view: str
    notes: str
    filename: str
    content_type: str
    size_bytes: int
    width: int
    height: int
    created_at: datetime


class StudyListOut(BaseModel):
    total: int
    items: list[StudyOut]


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    value: float
    unit: str
    ref_low: float
    ref_high: float
    flag: str
    confidence: float
    note: str


class AnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    study_id: int
    engine: str
    engine_version: str
    quality_score: float
    summary: str
    abnormal_count: int
    overall_confidence: float
    created_at: datetime
    findings: list[FindingOut] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    study_id: int
    analysis_id: int
    title: str
    impression: str
    findings_text: str
    technique: str
    disclaimer: str
    abnormal_count: int
    overall_confidence: float
    created_at: datetime


# --------------------------------------------------------------------------
# Misc
# --------------------------------------------------------------------------


class HealthOut(BaseModel):
    status: str
    app: str
    environment: str
    engine: str
    engine_version: str
    database: str
    disclaimer: str


class ErrorOut(BaseModel):
    error: str
    detail: str
    request_id: str = ""
