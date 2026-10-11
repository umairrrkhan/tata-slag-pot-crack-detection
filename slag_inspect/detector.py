"""Vectorized morphology with bounded inputs and component-local geometry."""
from dataclasses import asdict, dataclass
import math

import numpy as np
from scipy import ndimage as ndi


@dataclass(frozen=True)
class Config:
    contrast: float = 22.0
    min_area: int = 16
    min_length_px: float = 16.0
    min_elongation: float = 2.5
    max_width_px: float = 12.0
    thermal_delta_c: float = 15.0
    min_std: float = 3.0
    max_saturated_fraction: float = 0.15
    max_pixels: int = 8_000_000

    def __post_init__(self):
        for key, value in asdict(self).items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{key} must be positive and finite")
        if self.max_saturated_fraction > 1:
            raise ValueError("max_saturated_fraction must be <= 1")


def inspect(image, *, config=Config(), roi=None, mm_per_pixel=None,
            thermal=None, hotspots=()):
    """Inspect a registered, rectified view. Thermal must be aligned Celsius data.

    Returns candidates, never a confirmed crack or automatic release decision.
    Physical dimensions require supplied planar calibration at this view's pose.
    """
    image = np.asarray(image)
    if image.dtype != np.uint8 or image.ndim != 2 or min(image.shape) < 16:
        raise ValueError("image must be a uint8 grayscale array at least 16x16")
    if image.size > config.max_pixels:
        raise ValueError("image exceeds processing pixel budget; tile at acquisition")
    if mm_per_pixel is not None and (not math.isfinite(mm_per_pixel) or mm_per_pixel <= 0):
        raise ValueError("mm_per_pixel must be positive and finite")
    if roi is None:
        roi = np.ones(image.shape, dtype=bool)
    else:
        roi = np.asarray(roi)
        if roi.dtype != bool or roi.shape != image.shape or not roi.any():
            raise ValueError("ROI must be a nonempty aligned boolean mask")
    if thermal is not None:
        thermal = np.asarray(thermal, dtype=float)
        if thermal.shape != image.shape or not np.isfinite(thermal).all():
            raise ValueError("thermal must be a finite, aligned Celsius array")
        if thermal.min() < -273.15 or thermal.max() > 1500:
            raise ValueError("thermal temperatures outside supported -273.15..1500 C")
    height, width = image.shape
    for hotspot in hotspots:
        if (len(hotspot) != 4 or any(type(v) is not int for v in hotspot)
                or not (0 <= hotspot[0] < hotspot[2] <= width
                        and 0 <= hotspot[1] < hotspot[3] <= height)):
            raise ValueError("hotspots must be integer [x0,y0,x1,y1] boxes in image")
    values = image[roi]
    saturated = float(np.mean((values <= 2) | (values >= 253)))
    quality = {"std": float(values.std()), "saturated_fraction": saturated}
    if quality["std"] < config.min_std or saturated > config.max_saturated_fraction:
        return {"status": "uninspectable", "quality": quality, "candidates": [],
                "reason": "low contrast or excessive clipping; reacquire and review"}

    # Flat grayscale closing suppresses broad lighting changes, preserving dark lines.
    # Both polarities are searched; thermal is corroboration, never a required gate.
    gray = image.astype(np.float32)
    response = np.maximum(ndi.grey_closing(gray, size=(9, 9)) - gray,
                          gray - ndi.grey_opening(gray, size=(9, 9)))
    valid = ndi.binary_erosion(roi, iterations=4, border_value=0)
    mask = (response >= config.contrast) & valid
    labels, _ = ndi.label(mask, structure=np.ones((3, 3)))
    objects = ndi.find_objects(labels)
    thermal_residual = None
    if thermal is not None:
        thermal_residual = thermal - ndi.uniform_filter(thermal, size=21)
    candidates = []
    for number, box in enumerate(objects, 1):
        if box is None:
            continue
        local = labels[box] == number
        ys, xs = np.nonzero(local)
        area = len(xs)
        if area < config.min_area:
            continue
        points = np.column_stack((xs, ys)).astype(float)
        centered = points - points.mean(axis=0)
        eigenvalues, vectors = np.linalg.eigh(centered.T @ centered / area)
        major = vectors[:, -1]
        length = float(np.ptp(centered @ major) + 1)
        width_estimate = area / length
        elongation = float(np.sqrt((eigenvalues[-1] + 1e-6) / (eigenvalues[0] + 1e-6)))
        if (length < config.min_length_px or elongation < config.min_elongation
                or width_estimate > config.max_width_px):
            continue
        x0, y0 = box[1].start, box[0].start
        x1, y1 = box[1].stop, box[0].stop
        recurring = any(x0 < h[2] and x1 > h[0] and y0 < h[3] and y1 > h[1]
                        for h in hotspots)
        delta = (float(np.max(np.abs(thermal_residual[box][local])))
                 if thermal_residual is not None else None)
        supported = delta is not None and delta >= config.thermal_delta_c
        angle = math.degrees(math.atan2(major[1], major[0])) % 180
        orientation = "horizontal" if angle < 30 or angle > 150 else (
            "vertical" if 60 < angle < 120 else "oblique")
        # Heuristic review ranking, not calibrated failure probability or severity.
        score = min(100, round(30 + min(length / 4, 40) + 15 * recurring + 15 * supported))
        candidates.append({
            "bbox_xyxy": [x0, y0, x1, y1], "class": f"{orientation}_crack_candidate",
            "projected_length_px": round(length, 2),
            "average_width_px": round(width_estimate, 2),
            "projected_length_mm": round(length * mm_per_pixel, 2) if mm_per_pixel else None,
            "average_width_mm": round(width_estimate * mm_per_pixel, 2) if mm_per_pixel else None,
            "recurring_location": recurring, "thermal_delta_c": delta,
            "thermal_support": supported, "review_score": score,
            "priority": "urgent_review" if score >= 70 else "review",
        })
    candidates.sort(key=lambda c: (-c["review_score"], c["bbox_xyxy"]))
    return {"status": "review_required" if candidates else "no_candidates_review_required",
            "quality": quality, "candidates": candidates,
            "reason": "Prototype output requires qualified review; no automatic release"}
