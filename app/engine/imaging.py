"""Pure image-processing primitives for chest radiograph measurement.

Every function here is deterministic, side-effect free, and operates on a
float32 NumPy array in the range [0, 1] where 0 is black and 1 is white.
No file I/O, no database, no network — which is what makes the whole engine
unit-testable without fixtures.

The measurements are real: `cardiothoracic_ratio` is the same quantity a
radiologist measures with a ruler, computed from the pixels.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image

# --------------------------------------------------------------------------
# Loading and normalisation
# --------------------------------------------------------------------------


def load_grayscale(image: Image.Image) -> np.ndarray:
    """Convert any Pillow image to a normalised float32 grayscale array.

    Returns an array in [0, 1] with shape (H, W).
    """
    if image.mode != "L":
        image = image.convert("L")
    arr = np.asarray(image, dtype=np.float32) / 255.0
    if arr.ndim != 2:
        raise ValueError("expected a 2-D grayscale image")
    return arr


def normalize_contrast(arr: np.ndarray, low_pct: float = 1.0, high_pct: float = 99.0) -> np.ndarray:
    """Percentile contrast stretch.

    Radiographs routinely arrive with a narrow occupied intensity band. Stretching
    the 1st..99th percentile to the full range makes the subsequent thresholds
    behave consistently across films from different machines.
    """
    if arr.size == 0:
        raise ValueError("empty image")
    lo = float(np.percentile(arr, low_pct))
    hi = float(np.percentile(arr, high_pct))
    if hi - lo < 1e-6:
        # Flat image — nothing to stretch. Return as-is rather than dividing by ~0.
        return arr.copy()
    stretched = (arr - lo) / (hi - lo)
    return np.clip(stretched, 0.0, 1.0).astype(np.float32)


def resize_max(arr: np.ndarray, max_side: int = 1024) -> np.ndarray:
    """Downscale so the longest side is at most `max_side`, preserving aspect.

    Keeps analysis time bounded regardless of the uploaded resolution.
    """
    h, w = arr.shape
    longest = max(h, w)
    if longest <= max_side:
        return arr
    scale = max_side / float(longest)
    new_h = max(1, int(round(h * scale)))
    new_w = max(1, int(round(w * scale)))
    img = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8), mode="L")
    img = img.resize((new_w, new_h), Image.BILINEAR)
    return np.asarray(img, dtype=np.float32) / 255.0


# --------------------------------------------------------------------------
# Quality assessment
# --------------------------------------------------------------------------


@dataclass
class QualityMetrics:
    """Observable properties of the film itself, before any measurement."""

    mean_intensity: float
    std_intensity: float
    dynamic_range: float
    saturated_fraction: float
    width: int
    height: int
    score: float = 0.0
    issues: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "mean_intensity": round(self.mean_intensity, 4),
            "std_intensity": round(self.std_intensity, 4),
            "dynamic_range": round(self.dynamic_range, 4),
            "saturated_fraction": round(self.saturated_fraction, 4),
            "width": self.width,
            "height": self.height,
            "score": round(self.score, 4),
            "issues": list(self.issues),
        }


def estimate_quality(arr: np.ndarray) -> QualityMetrics:
    """Measure exposure quality and produce a 0..1 usability score.

    A film is usable when it is neither crushed to black nor blown out, and when
    it actually uses a decent slice of the intensity range. The score feeds the
    confidence calculation, so a poor film produces low-confidence findings
    rather than confident nonsense.
    """
    mean = float(arr.mean())
    std = float(arr.std())
    lo = float(np.percentile(arr, 1))
    hi = float(np.percentile(arr, 99))
    dynamic_range = hi - lo
    saturated = float(np.mean((arr <= 0.02) | (arr >= 0.98)))

    issues: list[str] = []
    score = 1.0

    if mean < 0.20:
        issues.append("underexposed")
        score -= 0.35
    elif mean > 0.80:
        issues.append("overexposed")
        score -= 0.35

    if dynamic_range < 0.35:
        issues.append("low_contrast")
        score -= 0.30

    if std < 0.08:
        issues.append("low_detail")
        score -= 0.20

    if saturated > 0.25:
        issues.append("clipping")
        score -= 0.15

    score = float(np.clip(score, 0.0, 1.0))

    return QualityMetrics(
        mean_intensity=mean,
        std_intensity=std,
        dynamic_range=dynamic_range,
        saturated_fraction=saturated,
        width=int(arr.shape[1]),
        height=int(arr.shape[0]),
        score=score,
        issues=issues,
    )


# --------------------------------------------------------------------------
# Region segmentation
# --------------------------------------------------------------------------


def body_mask(arr: np.ndarray, threshold: float = 0.12) -> np.ndarray:
    """Boolean mask of the patient body (everything brighter than the backdrop).

    Radiograph backdrops are near-black; the body is not. A low threshold plus a
    column/row occupancy filter removes stray bright specks.
    """
    mask = arr > threshold
    # Keep only rows/columns that are meaningfully occupied, to drop noise.
    col_keep = mask.sum(axis=0) > (0.05 * mask.shape[0])
    row_keep = mask.sum(axis=1) > (0.05 * mask.shape[1])
    mask = mask & col_keep[np.newaxis, :] & row_keep[:, np.newaxis]
    return mask


def _body_bounds(mask: np.ndarray) -> tuple[int, int, int, int]:
    """Return (top, bottom, left, right) of the largest occupied region."""
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    if rows.size == 0 or cols.size == 0:
        h, w = mask.shape
        return 0, h - 1, 0, w - 1
    return int(rows[0]), int(rows[-1]), int(cols[0]), int(cols[-1])


def lung_fields(arr: np.ndarray, mask: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Segment left and right lung fields.

    Lungs are the *dark* (air-filled) regions inside the body, in the upper
    two-thirds of the thorax. We take the body bounds, restrict to the upper
    region, and split on the vertical midline. Within each half we keep pixels
    darker than that half's median — the aerated lung — and drop the mediastinum
    (the bright midline column) explicitly.
    """
    if mask is None:
        mask = body_mask(arr)

    top, bottom, left, right = _body_bounds(mask)
    height = bottom - top + 1
    width = right - left + 1
    if height < 8 or width < 8:
        empty = np.zeros_like(arr, dtype=bool)
        return empty, empty

    # Upper 2/3 of the thorax holds the lung fields; the bottom third is
    # diaphragm and abdomen.
    lung_bottom = top + int(height * 0.68)
    mid = left + width // 2
    # Exclude a central band around the midline (spine + mediastinum).
    band = max(2, int(width * 0.06))

    region = np.zeros_like(arr, dtype=bool)
    region[top:lung_bottom, left:right] = True
    region &= mask

    left_half = region.copy()
    left_half[:, mid - band :] = False
    right_half = region.copy()
    right_half[:, : mid + band] = False

    def _darken(half: np.ndarray) -> np.ndarray:
        if not half.any():
            return half
        vals = arr[half]
        cutoff = float(np.median(vals))
        return half & (arr <= cutoff)

    return _darken(left_half), _darken(right_half)


# --------------------------------------------------------------------------
# Measurements
# --------------------------------------------------------------------------


def measure_cardiothoracic_ratio(arr: np.ndarray, mask: np.ndarray | None = None) -> float:
    """Heart width ÷ thorax width, measured at the widest cardiac row.

    The heart is the *densest* structure in the lower thorax — brighter than the
    aerated lung and brighter than the surrounding soft tissue. We derive the
    bright threshold from the lower-thorax pixels themselves, as the midpoint
    between their median and their maximum. That adapts to the film's own
    exposure instead of relying on an absolute cut-off, and it isolates the
    cardiac silhouette rather than the whole body.

    Returns 0.0 when the geometry cannot be resolved or no distinct dense
    structure is present.
    """
    if mask is None:
        mask = body_mask(arr)

    top, bottom, left, right = _body_bounds(mask)
    height = bottom - top + 1
    width = right - left + 1
    if height < 16 or width < 16:
        return 0.0

    mid = left + width // 2
    # Cardiac silhouette lives in the lower-middle thorax.
    scan_top = top + int(height * 0.40)
    scan_bottom = top + int(height * 0.80)

    lower = np.zeros_like(arr, dtype=bool)
    lower[scan_top:scan_bottom, left:right] = True
    lower &= mask
    if not lower.any():
        return 0.0

    vals = arr[lower]
    median = float(np.median(vals))
    # Use a high percentile rather than the raw max so a single hot pixel
    # cannot drag the threshold up and erase the cardiac silhouette.
    peak = float(np.percentile(vals, 99.5))
    # No structure stands out from the soft-tissue baseline — nothing to measure.
    #
    # The guard is on the *spread of the distribution*, not on peak - median.
    # A well-exposed film can legitimately saturate the densest structure to
    # 1.0, which makes peak == median == 1.0 and would otherwise look like
    # "no structure" when in fact the heart is the brightest thing present.
    # The interquartile range is the honest test: if the lower thorax is
    # genuinely flat, there is no silhouette to find.
    q1, q3 = (float(np.percentile(vals, p)) for p in (25.0, 75.0))
    if q3 - q1 < 0.05 and peak - median < 0.05:
        return 0.0
    bright_cut = median + 0.6 * (peak - median)
    # When the distribution is saturated at the top, the midpoint rule collapses
    # onto the ceiling and nothing can exceed it. Fall back to a cut just below
    # the peak so the densest structure is still captured.
    if bright_cut >= peak:
        bright_cut = peak - 0.02

    best = 0.0
    for row in range(scan_top, scan_bottom):
        row_mask = mask[row]
        cols = np.where(row_mask)[0]
        if cols.size < 8:
            continue
        thorax_w = float(cols[-1] - cols[0] + 1)
        if thorax_w < 8:
            continue

        bright = (arr[row] >= bright_cut) & row_mask
        heart_w = _run_through(bright, mid)
        if heart_w <= 0:
            continue
        ratio = heart_w / thorax_w
        if ratio > best:
            best = ratio

    return float(np.clip(best, 0.0, 1.0))


def _run_through(bright_row: np.ndarray, mid: int) -> float:
    """Length of the contiguous True run in `bright_row` that covers `mid`.

    If the midline itself is not bright, take the nearest bright run within a
    small window — the cardiac border can sit a pixel or two off-centre.
    """
    n = bright_row.size
    if n == 0:
        return 0.0

    def run_len_at(idx: int) -> float:
        if idx < 0 or idx >= n or not bright_row[idx]:
            return 0.0
        lo = idx
        while lo - 1 >= 0 and bright_row[lo - 1]:
            lo -= 1
        hi = idx
        while hi + 1 < n and bright_row[hi + 1]:
            hi += 1
        return float(hi - lo + 1)

    if bright_row[mid]:
        return run_len_at(mid)

    for offset in range(1, max(2, n // 20)):
        for idx in (mid - offset, mid + offset):
            if 0 <= idx < n and bright_row[idx]:
                return run_len_at(idx)
    return 0.0


def measure_lung_density(arr: np.ndarray, lung: np.ndarray) -> float:
    """Mean normalised intensity inside a lung mask. 0.0 if the mask is empty."""
    if lung is None or not lung.any():
        return 0.0
    return float(arr[lung].mean())


def measure_density_asymmetry(left_density: float, right_density: float) -> float:
    """Relative difference between the two lungs.

    Returns |L − R| ÷ mean(L, R). Zero when both are zero.
    """
    denom = (left_density + right_density) / 2.0
    if denom <= 1e-6:
        return 0.0
    return float(abs(left_density - right_density) / denom)


def measure_costophrenic_density(arr: np.ndarray, mask: np.ndarray | None = None) -> float:
    """Mean intensity in the bottom-lateral bands where fluid would pool.

    The costophrenic angles sit at the lower outer corners of the lung fields.
    Fluid (effusion) raises density there. We sample the two bottom-lateral
    rectangles and return their mean intensity.
    """
    if mask is None:
        mask = body_mask(arr)

    top, bottom, left, right = _body_bounds(mask)
    height = bottom - top + 1
    width = right - left + 1
    if height < 16 or width < 16:
        return 0.0

    band_top = top + int(height * 0.62)
    band_bottom = top + int(height * 0.86)
    band_w = max(2, int(width * 0.18))

    left_band = np.zeros_like(arr, dtype=bool)
    left_band[band_top:band_bottom, left : left + band_w] = True
    right_band = np.zeros_like(arr, dtype=bool)
    right_band[band_top:band_bottom, right - band_w : right] = True

    band = (left_band | right_band) & mask
    if not band.any():
        return 0.0
    return float(arr[band].mean())


# --------------------------------------------------------------------------
# Overlay for the UI
# --------------------------------------------------------------------------


def build_overlay(arr: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Return an RGB uint8 overlay highlighting the segmented lung fields.

    Used by the frontend to show *what the engine looked at*, so a clinician can
    see the segmentation rather than trusting an opaque number.
    """
    if mask is None:
        mask = body_mask(arr)
    left, right = lung_fields(arr, mask)

    rgb = np.stack([arr, arr, arr], axis=-1)
    rgb[left] = rgb[left] * 0.45 + np.array([0.10, 0.55, 0.95]) * 0.55
    rgb[right] = rgb[right] * 0.45 + np.array([0.95, 0.55, 0.10]) * 0.55
    return (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
