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
    max_pixels: int = 1_048_576
    max_components: int = 16_384
    max_component_pixels: int = 262_144

    def __post_init__(self):
        for key, value in asdict(self).items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{key} must be positive and finite")
        if self.max_saturated_fraction > 1:
            raise ValueError("max_saturated_fraction must be <= 1")
        for key in ("min_area", "max_pixels", "max_components", "max_component_pixels"):
            if type(getattr(self, key)) is not int:
                raise ValueError(f"{key} must be an integer")


def _quality(image, roi):
    # Bounded histogram strips avoid float64 full-frame variance temporaries.
    histogram = np.zeros(256, dtype=np.int64)
    for y in range(0, image.shape[0], 32):
        strip = image[y:y + 32]
        values = strip.ravel() if roi is None else strip[roi[y:y + 32]]
        histogram += np.bincount(values, minlength=256)
    count = int(histogram.sum())
    levels = np.arange(256, dtype=np.float64)
    mean = float(histogram @ levels / count)
    variance = max(0, float(histogram @ (levels * levels) / count - mean * mean))
    return {"std": math.sqrt(variance),
            "saturated_fraction": float((histogram[:3].sum() + histogram[253:].sum()) / count)}


def _uninspectable(quality, reason):
    return {"status": "uninspectable", "quality": quality, "candidates": [], "reason": reason}


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
    if roi is not None:
        roi = np.asarray(roi)
        if roi.dtype != bool or roi.shape != image.shape or not roi.any():
            raise ValueError("ROI must be a nonempty aligned boolean mask")
    if thermal is not None:
        thermal = np.asarray(thermal)
        if thermal.shape != image.shape or thermal.dtype.kind not in "fiu":
            raise ValueError("thermal must be a finite, aligned Celsius array")
        for y in range(0, thermal.shape[0], 32):
            strip = thermal[y:y + 32]
            if not np.isfinite(strip).all():
                raise ValueError("thermal must be a finite, aligned Celsius array")
            if strip.min() < -273.15 or strip.max() > 1500:
                raise ValueError("thermal temperatures outside supported -273.15..1500 C")
    height, width = image.shape
    for hotspot in hotspots:
        if (len(hotspot) != 4 or any(type(v) is not int for v in hotspot)
                or not (0 <= hotspot[0] < hotspot[2] <= width
                        and 0 <= hotspot[1] < hotspot[3] <= height)):
            raise ValueError("hotspots must be integer [x0,y0,x1,y1] boxes in image")
    quality = _quality(image, roi)
    quality["filter_margin_px"] = 8
    if quality["std"] < config.min_std or quality["saturated_fraction"] > config.max_saturated_fraction:
        return _uninspectable(quality, "low contrast or excessive clipping; reacquire and review")

    # Flat grayscale closing suppresses broad lighting changes, preserving dark lines.
    # Both polarities are searched; thermal is corroboration, never a required gate.
    # Closing is >= image and opening <= image, so uint8 subtraction is safe.
    response = ndi.grey_closing(image, size=(9, 9))
    np.subtract(response, image, out=response)
    bright = ndi.grey_opening(image, size=(9, 9))
    np.subtract(image, bright, out=bright)
    np.maximum(response, bright, out=response)
    del bright
    mask = response >= config.contrast
    del response
    if roi is not None:
        # Two radius-four filters compose to radius eight (square support).
        valid = ndi.minimum_filter(roi, size=17, mode="constant", cval=0)
        if not valid.any():
            return _uninspectable(quality, "ROI has no valid filter interior")
        mask &= valid
        del valid
    if min(image.shape) <= 16:
        return _uninspectable(quality, "image has no valid filter interior")
    mask[:8] = False
    mask[-8:] = False
    mask[:, :8] = False
    mask[:, -8:] = False
    labels, count = ndi.label(mask, structure=np.ones((3, 3)))
    del mask
    if count > config.max_components:
        return _uninspectable(quality, "component budget exceeded; reacquire or inspect manually")
    areas = np.zeros(count + 1, dtype=np.int64)
    for y in range(0, height, 32):
        areas += np.bincount(labels[y:y + 32].ravel(), minlength=count + 1)
    objects = ndi.find_objects(labels)
    candidates = []
    for number, box in enumerate(objects, 1):
        if box is None or areas[number] < config.min_area:
            continue
        if (box[0].stop - box[0].start) * (box[1].stop - box[1].start) > config.max_component_pixels:
            return _uninspectable(quality, "component extent budget exceeded; qualified review required")
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
        delta = None
        if thermal is not None:
            # Full 21x21 neighborhood, only around candidates; preserve global
            # reflect boundaries when the expanded patch meets image edges.
            ty0, tx0 = max(0, y0 - 10), max(0, x0 - 10)
            ty1, tx1 = min(height, y1 + 10), min(width, x1 + 10)
            patch = thermal[ty0:ty1, tx0:tx1].astype(np.float32)
            mean = ndi.uniform_filter(patch, size=21)
            np.subtract(patch, mean, out=patch)
            delta = float(np.max(np.abs(patch[y0-ty0:y1-ty0, x0-tx0:x1-tx0][local])))
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
