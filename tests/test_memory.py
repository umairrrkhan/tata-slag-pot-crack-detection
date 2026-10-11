"""Regression for retaining all decoded views; no hardware timing assertions."""
import json
from pathlib import Path
import tempfile
import tracemalloc
import unittest

import numpy as np
from PIL import Image

from slag_inspect.cli import run


class MemoryTests(unittest.TestCase):
    def test_twenty_views_have_bounded_tracked_allocations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = np.random.default_rng(3).integers(138, 153, (768, 1024), dtype=np.uint8)
            image[300:303, 200:750] = 45
            Image.fromarray(image).save(root / "frame.png")
            thermal = np.full(image.shape, 600, dtype=np.float32)
            np.save(root / "thermal.npy", thermal)
            views = [{"view_id": f"v{i}", "image": "frame.png", "thermal": "thermal.npy"}
                     for i in range(20)]
            path = root / "manifest.json"
            path.write_text(json.dumps({"pot_id": "POT-01", "captured_at": "2026-10-11T12:00:00Z",
                                        "required_views": [v["view_id"] for v in views], "views": views}))
            tracemalloc.start()
            try:
                record, _ = run(path, root / "reports")
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            self.assertEqual(len(record["views"]), 20)
            # Measured ~4.7 MiB; ample margin for dependency variation. The old
            # implementation used ~48 MiB on this workload and fails this bound.
            self.assertLess(peak, 12 * 1048576)
