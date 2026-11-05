"""Analysis orchestration: measurements → findings → confidence.

This module is the seam where a real trained model would be plugged in. The
public entry point `run_analysis` takes pixels and returns a fully-populated
result object; nothing above it knows or cares how the numbers were produced.

The default provider is `DeterministicEngine`, which computes the radiographic
measurements in `imaging.py` and compares them to published reference ranges.
It is honest about what it is: a measurement engine, not a diagnostic model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
from PIL import Image

from app.engine import imaging

ENGINE_NAME = "deterministic-radiographic-measurement"
ENGINE_VERSION = "1.0.0"


# --------------------------------------------------------------------------
# Reference ranges
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ReferenceRange:
    """A measurement's expected interval and what a breach means."""

    key: str
    label: str
    low: float
    high: float
    unit: str
    breach_label: str
    breach_note: str

    def flag(self, value: float) -> str:
        """Return 'normal', 'low', or 'high'."""
        if value < self.low:
            return "low"
        if value > self.high:
            return "high"
        return "normal"

    def distance_outside(self, value: float) -> float:
        """How far outside the range, normalised by the range width.

        0.0 when inside. Used for confidence — a value barely over the line is
        a weaker signal than one far past it.
        """
        width = max(self.high - self.low, 1e-6)
        if value < self.low:
            return (self.low - value) / width
        if value > self.high:
            return (value - self.high) / width
        return 0.0


REFERENCE_RANGES: tuple[ReferenceRange, ...] = (
    ReferenceRange(
        key="cardiothoracic_ratio",
        label="Cardiothoracic ratio",
        low=0.0,
        high=0.50,
        unit="ratio",
        breach_label="Possible cardiomegaly",
        breach_note=(
            "The cardiac silhouette occupies more than half the thoracic width. "
            "A CTR at or above 0.50 is the conventional threshold for an enlarged "
            "cardiac shadow on a PA film."
        ),
    ),
    ReferenceRange(
        key="lung_density_left",
        label="Left lung field density",
        low=0.15,
        high=0.55,
        unit="intensity",
        breach_label="Abnormal left lung density",
        breach_note=(
            "Mean attenuation across the left lung field falls outside the expected "
            "band. Raised density suggests consolidation or effusion; reduced density "
            "suggests hyperinflation."
        ),
    ),
    ReferenceRange(
        key="lung_density_right",
        label="Right lung field density",
        low=0.15,
        high=0.55,
        unit="intensity",
        breach_label="Abnormal right lung density",
        breach_note=(
            "Mean attenuation across the right lung field falls outside the expected "
            "band. Raised density suggests consolidation or effusion; reduced density "
            "suggests hyperinflation."
        ),
    ),
    ReferenceRange(
        key="density_asymmetry",
        label="Inter-lung density asymmetry",
        low=0.0,
        high=0.25,
        unit="ratio",
        breach_label="Asymmetric lung opacity",
        breach_note=(
            "The two lung fields differ in mean density by more than 25%. Unilateral "
            "opacity is a pattern worth a closer look."
        ),
    ),
    ReferenceRange(
        key="costophrenic_density",
        label="Costophrenic angle density",
        low=0.0,
        high=0.45,
        unit="intensity",
        breach_label="Possible pleural effusion",
        breach_note=(
            "Density in the lower lateral bands is elevated, which is where pleural "
            "fluid collects. Blunting of the costophrenic angle is the classic sign."
        ),
    ),
    ReferenceRange(
        key="exposure_quality",
        label="Exposure quality",
        low=0.25,
        high=0.75,
        unit="intensity",
        breach_label="Suboptimal exposure",
        breach_note=(
            "Mean film intensity sits outside the diagnostic band. Measurements on "
            "this film carry reduced confidence."
        ),
    ),
)

RANGE_BY_KEY = {r.key: r for r in REFERENCE_RANGES}


# --------------------------------------------------------------------------
# Result objects
# --------------------------------------------------------------------------


@dataclass
class Finding:
    key: str
    label: str
    value: float
    unit: str
    ref_low: float
    ref_high: float
    flag: str
    confidence: float
    note: str

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "value": round(self.value, 4),
            "unit": self.unit,
            "ref_low": self.ref_low,
            "ref_high": self.ref_high,
            "flag": self.flag,
            "confidence": round(self.confidence, 4),
            "note": self.note,
        }


@dataclass
class AnalysisResult:
    engine: str
    engine_version: str
    quality: dict
    findings: list[Finding] = field(default_factory=list)
    measurements: dict = field(default_factory=dict)
    summary: str = ""
    abnormal_count: int = 0
    overall_confidence: float = 0.0

    def as_dict(self) -> dict:
        return {
            "engine": self.engine,
            "engine_version": self.engine_version,
            "quality": self.quality,
            "findings": [f.as_dict() for f in self.findings],
            "measurements": {k: round(v, 4) for k, v in self.measurements.items()},
            "summary": self.summary,
            "abnormal_count": self.abnormal_count,
            "overall_confidence": round(self.overall_confidence, 4),
        }


class AnalysisEngine(Protocol):
    """The contract a real model would implement."""

    name: str
    version: str

    def analyze(self, arr: np.ndarray) -> AnalysisResult:  # pragma: no cover - protocol
        ...


# --------------------------------------------------------------------------
# Confidence
# --------------------------------------------------------------------------


def compute_confidence(
    flag: str,
    distance_outside: float,
    quality_score: float,
) -> float:
    """Confidence in a single finding, from two observable quantities.

    Deliberately NOT a model output. It combines:
      * how far the measurement sits past its reference boundary
        (normalised by the range width), and
      * how usable the film is (the quality score).

    A normal finding is reported with the quality score as its confidence — we
    are confident the measurement is in range, to the extent the film is good.
    """
    quality_score = float(np.clip(quality_score, 0.0, 1.0))
    if flag == "normal":
        return float(np.clip(0.55 + 0.40 * quality_score, 0.0, 1.0))

    # Abnormal: strength grows with distance, capped, then scaled by quality.
    strength = float(np.clip(distance_outside / 0.5, 0.0, 1.0))
    base = 0.45 + 0.50 * strength
    return float(np.clip(base * (0.55 + 0.45 * quality_score), 0.0, 1.0))


# --------------------------------------------------------------------------
# The default engine
# --------------------------------------------------------------------------


class DeterministicEngine:
    """Computes radiographic measurements and compares them to reference ranges."""

    name = ENGINE_NAME
    version = ENGINE_VERSION

    def analyze(self, arr: np.ndarray) -> AnalysisResult:
        arr = imaging.resize_max(arr, max_side=1024)
        arr = imaging.normalize_contrast(arr)

        quality = imaging.estimate_quality(arr)
        mask = imaging.body_mask(arr)
        left_lung, right_lung = imaging.lung_fields(arr, mask)

        ctr = imaging.measure_cardiothoracic_ratio(arr, mask)
        left_density = imaging.measure_lung_density(arr, left_lung)
        right_density = imaging.measure_lung_density(arr, right_lung)
        asymmetry = imaging.measure_density_asymmetry(left_density, right_density)
        cp_density = imaging.measure_costophrenic_density(arr, mask)

        measurements = {
            "cardiothoracic_ratio": ctr,
            "lung_density_left": left_density,
            "lung_density_right": right_density,
            "density_asymmetry": asymmetry,
            "costophrenic_density": cp_density,
            "exposure_quality": quality.mean_intensity,
        }

        findings: list[Finding] = []
        for ref in REFERENCE_RANGES:
            value = measurements[ref.key]
            flag = ref.flag(value)
            distance = ref.distance_outside(value)
            confidence = compute_confidence(flag, distance, quality.score)
            note = ref.breach_note if flag != "normal" else "Within the expected range."
            findings.append(
                Finding(
                    key=ref.key,
                    label=ref.label,
                    value=value,
                    unit=ref.unit,
                    ref_low=ref.low,
                    ref_high=ref.high,
                    flag=flag,
                    confidence=confidence,
                    note=note,
                )
            )

        abnormal = [f for f in findings if f.flag != "normal"]
        overall = float(np.mean([f.confidence for f in findings])) if findings else 0.0

        return AnalysisResult(
            engine=self.name,
            engine_version=self.version,
            quality=quality.as_dict(),
            findings=findings,
            measurements=measurements,
            summary=_summarize(abnormal, quality),
            abnormal_count=len(abnormal),
            overall_confidence=overall,
        )


def _summarize(abnormal: list[Finding], quality: imaging.QualityMetrics) -> str:
    if not abnormal:
        base = "All measured parameters fall within their reference ranges."
    else:
        labels = ", ".join(f.label.lower() for f in abnormal)
        base = f"{len(abnormal)} parameter(s) outside reference range: {labels}."
    if quality.issues:
        base += f" Film quality note: {', '.join(quality.issues)}."
    return base


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

_DEFAULT_ENGINE = DeterministicEngine()


def get_engine() -> DeterministicEngine:
    """Return the active engine.

    Swap this for a trained model implementing `AnalysisEngine` and nothing
    else in the codebase changes.
    """
    return _DEFAULT_ENGINE


def run_analysis(image: Image.Image) -> AnalysisResult:
    """Analyse a chest radiograph and return measurements + findings."""
    arr = imaging.load_grayscale(image)
    if arr.size == 0:
        raise ValueError("image has no pixels")
    return get_engine().analyze(arr)
