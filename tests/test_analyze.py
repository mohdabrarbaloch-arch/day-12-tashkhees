"""Tests for the analysis engine: reference ranges, flags, confidence."""

from __future__ import annotations

import pytest
from PIL import Image

from app.engine import analyze, imaging
from app.engine.analyze import (
    RANGE_BY_KEY,
    REFERENCE_RANGES,
    DeterministicEngine,
    ReferenceRange,
    compute_confidence,
)
from tests.conftest import make_radiograph


def _prepared(width: int = 400, height: int = 400, **kwargs):
    """A normalised grayscale array from a synthetic radiograph."""
    return imaging.normalize_contrast(imaging.load_grayscale(make_radiograph(width, height, **kwargs)))


def test_reference_ranges_are_well_formed():
    for r in REFERENCE_RANGES:
        assert r.low < r.high, r.key
        assert r.label and r.breach_label and r.breach_note


def test_reference_range_flag_normal():
    r = ReferenceRange("x", "X", 0.0, 1.0, "u", "b", "n")
    assert r.flag(0.5) == "normal"


def test_reference_range_flag_low_and_high():
    r = ReferenceRange("x", "X", 0.2, 0.8, "u", "b", "n")
    assert r.flag(0.1) == "low"
    assert r.flag(0.9) == "high"


def test_distance_outside_is_zero_inside():
    r = ReferenceRange("x", "X", 0.2, 0.8, "u", "b", "n")
    assert r.distance_outside(0.5) == 0.0


def test_distance_outside_grows_with_breach():
    r = ReferenceRange("x", "X", 0.2, 0.8, "u", "b", "n")
    near = r.distance_outside(0.85)
    far = r.distance_outside(1.2)
    assert far > near > 0.0


def test_confidence_normal_scales_with_quality():
    low_q = compute_confidence("normal", 0.0, 0.2)
    high_q = compute_confidence("normal", 0.0, 1.0)
    assert high_q > low_q
    assert 0.0 <= low_q <= 1.0 and 0.0 <= high_q <= 1.0


def test_confidence_abnormal_grows_with_distance():
    near = compute_confidence("high", 0.05, 0.9)
    far = compute_confidence("high", 0.45, 0.9)
    assert far > near


def test_confidence_abnormal_penalised_by_poor_quality():
    good = compute_confidence("high", 0.3, 1.0)
    bad = compute_confidence("high", 0.3, 0.1)
    assert good > bad


def test_engine_produces_one_finding_per_reference_range():
    result = DeterministicEngine().analyze(_prepared())
    assert len(result.findings) == len(REFERENCE_RANGES)
    assert {f.key for f in result.findings} == set(RANGE_BY_KEY)


def test_engine_findings_carry_reference_bounds():
    result = DeterministicEngine().analyze(_prepared())
    for f in result.findings:
        assert f.ref_low < f.ref_high
        assert 0.0 <= f.confidence <= 1.0
        assert f.flag in ("normal", "low", "high")


def test_engine_measures_a_larger_heart_as_larger():
    small = DeterministicEngine().analyze(_prepared(500, 500, heart_scale=0.7))
    large = DeterministicEngine().analyze(_prepared(500, 500, heart_scale=1.5))
    ctr_small = next(f for f in small.findings if f.key == "cardiothoracic_ratio").value
    ctr_large = next(f for f in large.findings if f.key == "cardiothoracic_ratio").value
    assert ctr_large > ctr_small


def test_engine_flags_asymmetric_lungs():
    result = DeterministicEngine().analyze(_prepared(500, 500, left_density=0.15, right_density=0.55))
    asym = next(f for f in result.findings if f.key == "density_asymmetry")
    assert asym.value > 0.0


def test_engine_summary_mentions_abnormal_count():
    result = DeterministicEngine().analyze(_prepared())
    if result.abnormal_count == 0:
        assert "within their reference ranges" in result.summary
    else:
        assert str(result.abnormal_count) in result.summary


def test_engine_result_serialises_to_dict():
    d = DeterministicEngine().analyze(_prepared(300, 300)).as_dict()
    assert set(d) >= {"engine", "quality", "findings", "measurements", "summary"}
    assert isinstance(d["findings"], list)
    assert all("confidence" in f for f in d["findings"])


def test_run_analysis_rejects_empty_image():
    with pytest.raises(ValueError):
        analyze.run_analysis(Image.new("L", (0, 0)))


def test_run_analysis_end_to_end():
    result = analyze.run_analysis(make_radiograph(320, 320))
    assert result.engine == analyze.ENGINE_NAME
    assert result.engine_version == analyze.ENGINE_VERSION
    assert len(result.findings) == len(REFERENCE_RANGES)
    assert 0.0 <= result.overall_confidence <= 1.0
