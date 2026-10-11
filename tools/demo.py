"""Generate reproducible synthetic inputs, an inspection, and CPU timing evidence."""
import json
from pathlib import Path
import platform
import statistics
import sys
import time

import numpy as np
from PIL import Image
import scipy

from slag_inspect.cli import run
from slag_inspect.detector import inspect


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "work/demo")
    root.mkdir(parents=True, exist_ok=True)
    image = np.clip(np.random.default_rng(42).normal(145, 5, (768, 1024)), 0, 255).astype(np.uint8)
    image[300:303, 200:750] = 45
    image[450:650, 800:803] = 45
    Image.fromarray(image).save(root / "front.png")
    thermal = np.full(image.shape, 600.0)
    thermal[300:303, 200:750] = 640
    np.save(root / "front-thermal.npy", thermal)
    manifest = {"pot_id": "POT-01", "captured_at": "2026-10-11T12:00:00Z",
                "required_views": ["front"], "synthetic": True,
                "views": [{"view_id": "front", "image": "front.png",
                           "thermal": "front-thermal.npy", "mm_per_pixel": 0.5,
                           "hotspots": [[150, 250, 780, 350]]}]}
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    record, directory = run(path, root / "reports")
    inspect(image)  # Warm-up; benchmark detector separately from disk I/O.
    timings = []
    for _ in range(20):
        start = time.perf_counter()
        inspect(image)
        timings.append((time.perf_counter() - start) * 1000)
    evidence = {"synthetic": True, "dimensions": [1024, 768], "runs": 20,
                "median_ms": statistics.median(timings), "p95_ms": float(np.percentile(timings, 95)),
                "scope": "grayscale detection only, no thermal or persistence",
                "python": platform.python_version(), "platform": platform.platform(),
                "numpy": np.__version__, "scipy": scipy.__version__,
                "candidates": len(record["views"][0]["candidates"]),
                "end_to_end_processing_ms": record["processing_ms"],
                "report": str(directory / "inspection.md")}
    (root / "benchmark.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
