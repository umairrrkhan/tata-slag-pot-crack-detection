import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from slag_inspect.cli import run
from slag_inspect.detector import Config, inspect
from scipy import ndimage as ndi


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

    def test_full_size_noisy_demo_keeps_both_cracks(self):
        image = np.clip(np.random.default_rng(42).normal(145, 5, (768, 1024)), 0, 255).astype(np.uint8)
        image[300:303, 200:750] = 45
        image[450:650, 800:803] = 45
        result = inspect(image)
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(len(result["candidates"]), 2)

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

    def test_integer_budgets(self):
        for key in ("min_area", "max_pixels", "max_components", "max_component_pixels"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                Config(**{key: 2.5})

    def test_clutter_budget_requires_review(self):
        image = surface()
        image[20:230:5, 20:230:5] = 45
        result = inspect(image, config=Config(max_components=5))
        self.assertEqual(result["status"], "uninspectable")
        self.assertIn("component budget", result["reason"])

    def test_large_component_requires_review(self):
        result = inspect(crack(), config=Config(max_component_pixels=100))
        self.assertEqual(result["status"], "uninspectable")

    def test_roi_without_filter_interior_requires_review(self):
        roi = np.zeros((256, 256), bool)
        roi[125:130, :] = True
        self.assertEqual(inspect(crack(), roi=roi)["status"], "uninspectable")

    def test_local_thermal_equals_full_frame_mean(self):
        thermal = np.random.default_rng(19).normal(600, 10, (256, 256)).astype(np.float32)
        thermal[126:129, 40:205] += 40
        candidate = inspect(crack(), thermal=thermal)["candidates"][0]
        expected = np.abs(thermal - ndi.uniform_filter(thermal, size=21))[126:129, 40:205].max()
        self.assertAlmostEqual(candidate["thermal_delta_c"], float(expected), places=3)

    def test_uint8_morphology_matches_float(self):
        image = crack()
        gray = image.astype(np.float32)
        expected = np.maximum(ndi.grey_closing(gray, size=9)-gray, gray-ndi.grey_opening(gray, size=9))
        actual = np.maximum(ndi.grey_closing(image, size=9)-image, image-ndi.grey_opening(image, size=9))
        np.testing.assert_array_equal(actual, expected)


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

    def test_nonstring_timestamp_rejected(self):
        self.manifest["captured_at"] = 123
        with self.assertRaises(ValueError):
            self.execute()

    def test_required_views_string_rejected(self):
        self.manifest["required_views"] = "front"
        with self.assertRaises(ValueError):
            self.execute()

    def test_failed_persistence_removes_partial_output(self):
        with patch("slag_inspect.reporting.shutil.copyfile", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.execute()
        self.assertEqual(list((self.root / "out").iterdir()), [])

    def test_bad_roi_dimensions_rejected_before_decode(self):
        Image.fromarray(np.ones((32, 32), np.uint8)).save(self.root / "roi.png")
        self.manifest["views"][0]["roi"] = "roi.png"
        with self.assertRaises(ValueError):
            self.execute()

    def test_twenty_views_stream_to_disk(self):
        self.manifest["views"] = [{"view_id": f"v{i}", "image": "view.png"} for i in range(20)]
        self.manifest["required_views"] = [v["view_id"] for v in self.manifest["views"]]
        record, directory = self.execute()
        self.assertEqual(len(record["views"]), 20)
        self.assertEqual(len(list(directory.glob("*.png"))), 20)
        self.assertFalse(list((self.root / "out").glob(".staging-*")))

    def test_mapped_thermal_report(self):
        thermal = np.full((256, 256), 600, np.float32)
        thermal[126:129, 40:205] += 45
        np.save(self.root / "thermal.npy", thermal)
        self.manifest["views"][0]["thermal"] = "thermal.npy"
        record, _ = self.execute()
        self.assertTrue(record["views"][0]["candidates"][0]["thermal_support"])


if __name__ == "__main__":
    unittest.main()
