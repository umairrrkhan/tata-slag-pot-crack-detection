"""Fresh-process runtime and memory evidence, including a 20-view inspection.

Linux ru_maxrss includes interpreter, dependencies and input arrays. tracemalloc
captures tracked allocations during the measured call, not all native memory.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import tempfile
import time
import tracemalloc


def worker(mode):
    import numpy as np
    import scipy
    from PIL import Image
    from slag_inspect.cli import run
    from slag_inspect.detector import inspect

    image = np.random.default_rng(42).integers(138, 153, (768, 1024), dtype=np.uint8)
    image[300:303, 200:750] = 45
    thermal = np.full(image.shape, 600, dtype=np.float32)
    thermal[300:303, 200:750] = 640
    timings = []
    if mode == "detector":
        inspect(image, thermal=thermal)
        for _ in range(10):
            start = time.perf_counter()
            result = inspect(image, thermal=thermal)
            timings.append((time.perf_counter() - start) * 1000)
        tracemalloc.start()
        inspect(image, thermal=thermal)
        candidates = len(result["candidates"])
    else:
        count = int(mode)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.fromarray(image).save(root / "frame.png")
            np.save(root / "thermal.npy", thermal)
            views = [{"view_id": f"v{i}", "image": "frame.png", "thermal": "thermal.npy"}
                     for i in range(count)]
            manifest = {"pot_id": "POT-01", "captured_at": "2026-10-11T12:00:00Z",
                        "required_views": [v["view_id"] for v in views], "views": views}
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest))
            tracemalloc.start()
            start = time.perf_counter()
            result, _ = run(path, root / "reports")
            timings.append((time.perf_counter() - start) * 1000)
            candidates = sum(len(v["candidates"]) for v in result["views"])
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {"mode": mode, "dimensions": [1024, 768], "thermal": True,
            "runs": len(timings), "median_ms": float(np.median(timings)),
            "p95_ms": float(np.percentile(timings, 95)),
            "peak_traced_mib": peak / 1048576,
            "process_peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            "candidates": candidates, "python": platform.python_version(),
            "numpy": np.__version__, "scipy": scipy.__version__, "platform": platform.platform()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=("detector", "1", "20"))
    parser.add_argument("--baseline-root", type=Path)
    parser.add_argument("--output", type=Path, default=Path("work/edge-benchmark.json"))
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.worker)))
        return
    results = {}
    roots = {"optimized": Path(__file__).resolve().parents[1]}
    if args.baseline_root:
        roots["baseline"] = args.baseline_root.resolve()
    for name, root in roots.items():
        results[name] = []
        for mode in ("detector", "1", "20"):
            environment = {**os.environ, "PYTHONPATH": str(root), "OPENBLAS_NUM_THREADS": "1"}
            call = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", mode],
                                  env=environment, text=True, capture_output=True, check=True)
            results[name].append(json.loads(call.stdout))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
