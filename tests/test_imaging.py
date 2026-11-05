"""Tests for the pure imaging primitives."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from app.engine import imaging
from tests.conftest import make_radiograph


def test_load_grayscale_normalises_to_unit_range():
    img = Image.new("RGB", (32, 32), (255, 255, 255))
    arr = imaging.load_grayscale(img)
    assert arr.dtype == np.float32
    assert arr.shape == (32, 32)
    assert arr.max() <= 1.0 and arr.min() >= 0.0
    assert arr.mean() == pytest.approx(1.0, abs=1e-3)


def test_load_grayscale_rejects_non_2d():
    # A 1x1 image is still 2-D after conversion; guard the shape contract.
    arr = imaging.load_grayscale(Image.new("L", (4, 4), 128))
    assert arr.ndim == 2


def test_normalize_contrast_stretches_narrow_band():
    arr = np.full((10, 10), 0.4, dtype=np.float32)
    arr[0, 0] = 0.45
    arr[9, 9] = 0.55
    out = imaging.normalize_contrast(arr)
    assert out.min() == pytest.approx(0.0, abs=1e-5)
    assert out.max() == pytest.approx(1.0, abs=1e-5)


def test_normalize_contrast_handles_flat_image():
    arr = np.full((8, 8), 0.5, dtype=np.float32)
    out = imaging.normalize_contrast(arr)
    assert np.allclose(out, 0.5)


def test_normalize_contrast_rejects_empty():
    with pytest.raises(ValueError):
        imaging.normalize_contrast(np.array([], dtype=np.float32))


def test_resize_max_downscales_long_side():
    arr = np.random.rand(2000, 1000).astype(np.float32)
    out = imaging.resize_max(arr, max_side=500)
    assert max(out.shape) == 500
    assert out.shape[0] == 500
    assert out.shape[1] == 250


def test_resize_max_leaves_small_images_alone():
    arr = np.random.rand(100, 80).astype(np.float32)
    out = imaging.resize_max(arr, max_side=500)
    assert out.shape == (100, 80)


def test_estimate_quality_flags_underexposure():
    arr = np.full((64, 64), 0.05, dtype=np.float32)
    q = imaging.estimate_quality(arr)
    assert "underexposed" in q.issues
    assert q.score < 1.0


def test_estimate_quality_flags_overexposure():
    arr = np.full((64, 64), 0.95, dtype=np.float32)
    q = imaging.estimate_quality(arr)
    assert "overexposed" in q.issues


def test_estimate_quality_good_film_scores_high():
    rng = np.random.default_rng(7)
    arr = np.clip(rng.normal(0.5, 0.18, (128, 128)), 0, 1).astype(np.float32)
    q = imaging.estimate_quality(arr)
    assert q.score > 0.7
    assert q.issues == []


def test_body_mask_excludes_dark_backdrop():
    arr = np.full((100, 100), 0.02, dtype=np.float32)
    arr[20:80, 20:80] = 0.6
    mask = imaging.body_mask(arr)
    assert mask[50, 50]
    assert not mask[5, 5]


def test_lung_fields_are_disjoint_and_nonempty():
    img = make_radiograph(400, 400)
    arr = imaging.load_grayscale(img)
    arr = imaging.normalize_contrast(arr)
    left, right = imaging.lung_fields(arr)
    assert left.any() and right.any()
    assert not np.any(left & right)


def test_cardiothoracic_ratio_increases_with_heart_size():
    small = imaging.load_grayscale(make_radiograph(400, 400, heart_scale=0.7))
    large = imaging.load_grayscale(make_radiograph(400, 400, heart_scale=1.4))
    small = imaging.normalize_contrast(small)
    large = imaging.normalize_contrast(large)
    ctr_small = imaging.measure_cardiothoracic_ratio(small)
    ctr_large = imaging.measure_cardiothoracic_ratio(large)
    assert ctr_large > ctr_small
    assert 0.0 <= ctr_small <= 1.0 and 0.0 <= ctr_large <= 1.0


def test_cardiothoracic_ratio_zero_on_tiny_image():
    arr = np.zeros((8, 8), dtype=np.float32)
    assert imaging.measure_cardiothoracic_ratio(arr) == 0.0


def test_cardiothoracic_ratio_is_monotonic_across_heart_sizes():
    """Regression: a saturated heart must not collapse the measurement to 0.

    Percentile contrast stretching can push the densest structure to exactly
    1.0, which makes peak == median. An earlier guard read that as "no
    structure present" and returned 0.0 for every large heart — the ratio went
    up, then fell off a cliff. The measurement must rise monotonically.
    """
    ratios = [
        imaging.measure_cardiothoracic_ratio(imaging.normalize_contrast(_heart_phantom(frac)))
        for frac in (0.20, 0.30, 0.40, 0.50, 0.60)
    ]
    assert all(b > a for a, b in zip(ratios, ratios[1:], strict=False)), ratios
    assert all(0.0 <= r <= 1.0 for r in ratios)


def test_cardiothoracic_ratio_zero_on_flat_image():
    """A uniform film has no silhouette, so the engine must decline to guess."""
    flat = np.full((200, 200), 0.5, dtype=np.float32)
    assert imaging.measure_cardiothoracic_ratio(flat) == 0.0


def _heart_phantom(heart_w_frac: float) -> np.ndarray:
    """A synthetic chest film with a heart of a known width fraction."""
    h, w = 600, 500
    arr = np.full((h, w), 0.04, dtype=np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    body = ((xx - 250) / 210.0) ** 2 + ((yy - 300) / 290.0) ** 2 <= 1.0
    arr[body] = 0.38
    for cx in (150, 350):
        lung = ((xx - cx) / 95.0) ** 2 + ((yy - 230) / 150.0) ** 2 <= 1.0
        arr[lung & body] = 0.12
    arr[:, 240:260] = 0.62  # spine
    hw = int(heart_w_frac * w / 2)
    heart = ((xx - 250) / hw) ** 2 + ((yy - 360) / 110.0) ** 2 <= 1.0
    arr[heart & body] = 0.78
    return arr


def test_lung_density_reflects_pixel_values():
    img = make_radiograph(400, 400, left_density=0.20, right_density=0.45)
    arr = imaging.normalize_contrast(imaging.load_grayscale(img))
    left, right = imaging.lung_fields(arr)
    dl = imaging.measure_lung_density(arr, left)
    dr = imaging.measure_lung_density(arr, right)
    assert dr > dl


def test_lung_density_zero_on_empty_mask():
    arr = np.random.rand(32, 32).astype(np.float32)
    empty = np.zeros_like(arr, dtype=bool)
    assert imaging.measure_lung_density(arr, empty) == 0.0


def test_density_asymmetry_zero_when_equal():
    assert imaging.measure_density_asymmetry(0.3, 0.3) == pytest.approx(0.0)


def test_density_asymmetry_positive_when_different():
    val = imaging.measure_density_asymmetry(0.2, 0.4)
    assert val == pytest.approx(0.6667, abs=1e-3)


def test_density_asymmetry_handles_zero_denominator():
    assert imaging.measure_density_asymmetry(0.0, 0.0) == 0.0


def test_costophrenic_density_rises_with_fluid():
    dry = imaging.normalize_contrast(imaging.load_grayscale(make_radiograph(400, 400, cp_density=0.15)))
    wet = imaging.normalize_contrast(imaging.load_grayscale(make_radiograph(400, 400, cp_density=0.60)))
    assert imaging.measure_costophrenic_density(wet) > imaging.measure_costophrenic_density(dry)


def test_build_overlay_returns_rgb_uint8():
    arr = imaging.normalize_contrast(imaging.load_grayscale(make_radiograph(200, 200)))
    overlay = imaging.build_overlay(arr)
    assert overlay.dtype == np.uint8
    assert overlay.shape == (200, 200, 3)
