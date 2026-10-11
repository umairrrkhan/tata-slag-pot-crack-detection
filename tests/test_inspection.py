import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import numpy as np
from PIL import Image

from slag_inspect.cli import run
from slag_inspect.detector import Config, inspect


def surface(shape=(256, 256)):
    return np.clip(np.random.default_rng(7).normal(145, 5, shape), 0, 255).astype(np.uint8)


def crack(vertical=False, bright=False):
    image = surface()
    if vertical:
        image[40:205, 126:129] = 230 if bright else 45
    else:
        image[126:129, 40:205] = 230 if bright else 45
    return image


class DetectionTests(unittest.TestCase):
    def test_dark_horizontal_geometry(self):
        result = inspect(crack(), mm_per_pixel=0.5)
        c = result["candidates"][0]
        self.assertEqual(c["class"], "horizontal_crack_candidate")
        self.assertAlmostEqual(c["projected_length_mm"], 82.5, delta=1)
        self.assertAlmostEqual(c["average_width_mm"], 1.5, delta=0.3)

    def test_vertical_and_bright(self):
        for bright in (False, True):
            with self.subTest(bright=bright):
                self.assertEqual(inspect(crack(True, bright))["candidates"][0]["class"],
                                 "vertical_crack_candidate")

    def test_oblique(self):
        image = surface()
        for x in range(40, 205):
            image[x:x + 3, x] = 45
        self.assertEqual(inspect(image)["candidates"][0]["class"], "oblique_crack_candidate")

    def test_noise_has_no_candidates(self):
        self.assertEqual(inspect(surface())["status"], "no_candidates_review_required")

    def test_round_blob_rejected(self):
        image = surface()
        y, x = np.ogrid[:256, :256]
        image[(x-128)**2 + (y-128)**2 < 100] = 40
        self.assertFalse(inspect(image)["candidates"])

    def test_roi_excludes_crack(self):
        roi = np.zeros((256, 256), bool)
        roi[:80, :] = True
        self.assertFalse(inspect(crack(), roi=roi)["candidates"])

    def test_bad_quality(self):
        for image in (np.full((64, 64), 145, np.uint8), np.full((64, 64), 255, np.uint8)):
            self.assertEqual(inspect(image)["status"], "uninspectable")

    def test_thermal_optional_and_corroborates(self):
        thermal = np.full((256, 256), 600.0)
        thermal[126:129, 40:205] = 645
        cold = inspect(crack())["candidates"][0]
        hot = inspect(crack(), thermal=thermal)["candidates"][0]
        self.assertFalse(cold["thermal_support"])
        self.assertTrue(hot["thermal_support"])
        self.assertGreater(hot["review_score"], cold["review_score"])

    def test_hotspot_prioritizes_without_excluding_other_surface(self):
        baseline = inspect(crack())["candidates"][0]
        result = inspect(crack(), hotspots=[[30, 100, 210, 150]])["candidates"][0]
        self.assertTrue(result["recurring_location"])
        self.assertGreater(result["review_score"], baseline["review_score"])
        self.assertTrue(inspect(crack(), hotspots=[[0, 0, 20, 20]])["candidates"])

    def test_invalid_inputs(self):
        for kwargs in ({"mm_per_pixel": float("nan")}, {"mm_per_pixel": -1},
                       {"thermal": np.ones((10, 10))},
                       {"thermal": np.full((256, 256), float("nan"))},
                       {"roi": np.zeros((256, 256), bool)},
                       {"hotspots": [[-1, 0, 10, 10]]}):
            with self.subTest(kwargs=list(kwargs)), self.assertRaises(ValueError):
                inspect(crack(), **kwargs)
        with self.assertRaises(ValueError):
            inspect(np.zeros((32, 32), float))
        with self.assertRaises(ValueError):
            inspect(crack(), config=Config(max_pixels=100))

    def test_invalid_config(self):
        for kwargs in ({"contrast": 0}, {"min_area": -1}, {"max_saturated_fraction": 2}):
            with self.assertRaises(ValueError):
                Config(**kwargs)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        Image.fromarray(crack()).save(self.root / "view.png")
        self.manifest = {"pot_id": "POT-01", "captured_at": "2026-10-11T12:00:00Z",
                         "required_views": ["front"], "views": [
                             {"view_id": "front", "image": "view.png", "mm_per_pixel": 0.5}]}

    def tearDown(self):
        self.tmp.cleanup()

    def execute(self):
        path = self.root / "manifest.json"
        path.write_text(json.dumps(self.manifest))
        return run(path, self.root / "out")

    def test_reports_annotations_history_and_unique_records(self):
        first, directory = self.execute()
        second, _ = self.execute()
        self.assertNotEqual(first["inspection_id"], second["inspection_id"])
        self.assertEqual(json.loads((directory / "inspection.json").read_text()), first)
        self.assertIn("POT-01", (directory / "inspection.md").read_text())
        with Image.open(directory / "front.png") as annotated:
            self.assertEqual(annotated.size, (256, 256))
            self.assertEqual(annotated.getpixel((40, 126)), (255, 0, 0))
        with sqlite3.connect(self.root / "out/history.sqlite") as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM inspections").fetchone()[0], 2)

    def test_missing_view_marks_incomplete(self):
        self.manifest["required_views"].append("back")
        record, _ = self.execute()
        self.assertEqual(record["status"], "incomplete")
        self.assertEqual(record["missing_views"], ["back"])

    def test_bad_view_marks_incomplete(self):
        Image.fromarray(np.full((256, 256), 145, np.uint8)).save(self.root / "view.png")
        self.assertEqual(self.execute()[0]["status"], "incomplete")

    def test_duplicate_views_rejected(self):
        self.manifest["views"] *= 2
        with self.assertRaises(ValueError):
            self.execute()

    def test_path_identifier_rejected(self):
        self.manifest["views"][0]["view_id"] = "../escape"
        with self.assertRaises(ValueError):
            self.execute()

    def test_naive_timestamp_rejected(self):
        self.manifest["captured_at"] = "2026-10-11T12:00:00"
        with self.assertRaises(ValueError):
            self.execute()


if __name__ == "__main__":
    unittest.main()
