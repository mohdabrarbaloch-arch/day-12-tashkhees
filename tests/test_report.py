"""Tests for the report builder."""

from __future__ import annotations

from app.engine import imaging, report
from app.engine.analyze import DeterministicEngine
from tests.conftest import make_radiograph


def _result(**kwargs):
    arr = imaging.normalize_contrast(imaging.load_grayscale(make_radiograph(400, 400, **kwargs)))
    return DeterministicEngine().analyze(arr)


def test_report_always_carries_the_disclaimer():
    draft = report.build_report(_result())
    assert draft.disclaimer == report.DISCLAIMER
    assert "NOT a medical device" in draft.disclaimer


def test_report_has_all_sections():
    draft = report.build_report(_result())
    assert draft.title
    assert draft.impression
    assert draft.findings_text
    assert draft.technique


def test_findings_text_lists_every_measurement():
    result = _result()
    text = report.build_findings_text(result)
    for f in result.findings:
        assert f.label in text


def test_findings_text_marks_normal_and_abnormal():
    result = _result()
    text = report.build_findings_text(result)
    assert "NORMAL" in text or "HIGH" in text or "LOW" in text


def test_impression_mentions_no_abnormality_when_clean():
    result = _result()
    if result.abnormal_count == 0:
        assert "No measured parameter falls outside" in report.build_impression(result)


def test_impression_leads_with_highest_confidence_finding():
    result = _result(left_density=0.10, right_density=0.60, cp_density=0.70)
    impression = report.build_impression(result)
    if result.abnormal_count:
        ranked = sorted(
            [f for f in result.findings if f.flag != "normal"],
            key=lambda f: f.confidence,
            reverse=True,
        )
        assert ranked[0].label in impression


def test_technique_includes_engine_and_dimensions():
    result = _result()
    technique = report.build_technique(result)
    assert result.engine in technique
    assert "px" in technique


def test_technique_reports_quality_flags_when_present():
    import numpy as np
    from PIL import Image

    dark = Image.fromarray((np.full((300, 300), 0.03) * 255).astype("uint8"), mode="L")
    result = DeterministicEngine().analyze(imaging.load_grayscale(dark))
    technique = report.build_technique(result)
    assert "Quality flags" in technique


def test_report_draft_serialises():
    d = report.build_report(_result()).as_dict()
    assert set(d) >= {"title", "impression", "findings_text", "technique", "disclaimer"}
    assert isinstance(d["abnormal_count"], int)
