# Slag pot inspection

- Inspection: `8134bc71-b7de-443e-bda6-0a1d0ab30264`
- Pot: `POT-01`
- Captured (UTC): 2026-10-11T12:00:00+00:00
- Status: **review_required**

- Missing required views: none

Experimental candidates require qualified review. No fitness-for-service decision.
Lengths are projected estimates, not crack depth or structural severity.

| View | Candidate | Priority | Score | Projected length (mm) | Thermal support |
|---|---|---|---:|---:|---|
| front | 1: horizontal_crack_candidate | urgent_review | 100 | 275.0 | True |
| front | 2: vertical_crack_candidate | urgent_review | 70 | 100.5 | False |

## View quality and inspection limits

- front: review_required. Prototype output requires qualified review; no automatic release. Quality: {"filter_margin_px": 8, "saturated_fraction": 0.0, "std": 7.299340831916647}

## Acquisition and provenance

Processing time: 304.98 ms (excluding persistence).

```json
{
  "algorithm": "morphology-edge-v2",
  "config": {
    "contrast": 22.0,
    "min_area": 16,
    "min_length_px": 16.0,
    "min_elongation": 2.5,
    "max_width_px": 12.0,
    "thermal_delta_c": 15.0,
    "min_std": 3.0,
    "max_saturated_fraction": 0.15,
    "max_pixels": 1048576,
    "max_components": 16384,
    "max_component_pixels": 262144
  },
  "manifest_sha256": "902a3992219708a58ccb8b01d2fe0749a5dc98874dfa5d742076d441a7764280",
  "input_sha256": {
    "front:thermal": "312e722172d5f36cdd2bbc269a39ae91dd89838698c929b2a488f64b6233d0f6",
    "front:image": "4b7cc46f4d4b18ec12c11a7ba758fc255f1cce248625db9bd89860af49833e1b"
  },
  "acquisition": {
    "pot_id": "POT-01",
    "captured_at": "2026-10-11T12:00:00Z",
    "required_views": [
      "front"
    ],
    "synthetic": true,
    "views": [
      {
        "view_id": "front",
        "image": "front.png",
        "thermal": "front-thermal.npy",
        "mm_per_pixel": 0.5,
        "hotspots": [
          [
            150,
            250,
            780,
            350
          ]
        ]
      }
    ]
  }
}
```
