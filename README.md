# Slag pot non-contact inspection

CPU prototype and engineering proposal for approximately 20 slag pots inspected at surface temperatures up to 500–700°C. No sensor is attached to a pot.

The runnable baseline finds **crack candidates**, labels their orientation, ranks them for review, overlays detections, writes Markdown/JSON reports, and maintains SQLite history by pot ID. It is experimental; plant reliability has not been measured. Read [the engineering report](docs/SOLUTION_REPORT.md) for the proposed production station and validation plan.

## Run

Python 3.11+ is required.

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
PYTHONPATH=. python tools/demo.py work/demo
python -m slag_inspect.cli work/demo/manifest.json --output work/inspections
```

The demo generates synthetic images, a registered Celsius thermal array, a manifest, and an inspection. Each inspection creates `inspection.md`, `inspection.json`, and annotated view PNGs in a UUID directory. `history.sqlite` stores indexed pot records and report hashes.

## Inspect your images

Supply a JSON manifest; file paths are resolved relative to it:

```json
{
  "pot_id": "POT-01",
  "captured_at": "2026-10-11T12:00:00Z",
  "required_views": ["front", "back", "left", "right", "rim", "base"],
  "views": [
    {
      "view_id": "front",
      "image": "front.png",
      "roi": "front-mask.png",
      "thermal": "front-celsius.npy",
      "mm_per_pixel": 0.5,
      "hotspots": [[150, 250, 780, 350]]
    }
  ]
}
```

`roi`, `thermal`, `mm_per_pixel`, and `hotspots` are optional. ROI masks must match the image dimensions; nonzero pixels represent the pot. Thermal input is an aligned, finite NumPy array in Celsius, **not a colorized thermogram**. Hotspots use integer `[x0,y0,x1,y1]` boxes with exclusive upper bounds. Images should be registered and rectified; local metric calibration is required for physical measurements. Omit scale if unavailable. The single supplied view in this example produces an `incomplete` inspection because other required views are absent.

Required views must be derived from the surveyed pot geometry. The demo's one-view requirement is only a software example. Images are converted to grayscale; keep raw camera evidence separately. The default limit is eight million pixels per view and 32 views per inspection. Tile larger captures at acquisition and configure required coverage accordingly; tile reconciliation is not implemented.

Statuses are `incomplete`, `review_required`, or `no_candidates_review_required`. Individual bad-quality views return `uninspectable`. None authorizes return to service. Review scores are heuristics, not probabilities or structural severity classes.

## Files

- `slag_inspect/detector.py`: morphology, connected components, geometry, thermal support, review ranking.
- `slag_inspect/cli.py`: manifest validation, multi-view coverage, input hashes.
- `slag_inspect/reporting.py`: annotations, Markdown/JSON, SQLite records.
- `tests/test_inspection.py`: meaningful detection and reporting regression tests.
- `tools/demo.py`: reproducible synthetic demonstration and timing benchmark.
- `docs/SOLUTION_REPORT.md`: full engineering solution, limitations, costs, and acceptance plan.
- `.github/workflows/tests.yml`: repeatable CI test and demo commands.
