import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

import numpy as np
from PIL import Image

from .detector import Config, inspect
from .reporting import persist


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError("identifiers must contain 1..64 letters, digits, hyphens or underscores")
    return value


def run(manifest_path, output, config=Config()):
    start = time.perf_counter()
    manifest_path = Path(manifest_path)
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    pot = identifier(manifest["pot_id"])
    captured = datetime.fromisoformat(manifest["captured_at"].replace("Z", "+00:00"))
    if captured.tzinfo is None:
        raise ValueError("captured_at must include timezone")
    required = manifest["required_views"]
    if not required or len(set(required)) != len(required):
        raise ValueError("required_views must be nonempty and unique")
    for name in required:
        identifier(name)
    views, images, hashes = [], {}, {}
    if not manifest["views"] or len(manifest["views"]) > 32:
        raise ValueError("supply 1..32 views")
    for entry in manifest["views"]:
        view_id = identifier(entry["view_id"])
        if view_id in images:
            raise ValueError("duplicate view_id")
        image_path = manifest_path.parent / entry["image"]
        with Image.open(image_path) as source:
            if source.width * source.height > config.max_pixels:
                raise ValueError("image exceeds processing pixel budget")
            image = np.array(source.convert("L"))
        kwargs = {"hotspots": entry.get("hotspots", []),
                  "mm_per_pixel": entry.get("mm_per_pixel")}
        if "roi" in entry:
            roi_path = manifest_path.parent / entry["roi"]
            with Image.open(roi_path) as mask:
                kwargs["roi"] = np.array(mask.convert("L")) > 0
            hashes[f"{view_id}:roi"] = hashlib.sha256(roi_path.read_bytes()).hexdigest()
        if "thermal" in entry:
            thermal_path = manifest_path.parent / entry["thermal"]
            kwargs["thermal"] = np.load(thermal_path, allow_pickle=False)
            hashes[f"{view_id}:thermal"] = hashlib.sha256(thermal_path.read_bytes()).hexdigest()
        result = inspect(image, config=config, **kwargs)
        views.append({"view_id": view_id, **result})
        images[view_id] = image
        hashes[f"{view_id}:image"] = hashlib.sha256(image_path.read_bytes()).hexdigest()
    missing = sorted(set(required) - images.keys())
    uninspectable = any(v["status"] == "uninspectable" for v in views)
    status = "incomplete" if missing or uninspectable else (
        "review_required" if any(v["candidates"] for v in views)
        else "no_candidates_review_required")
    record = {"schema_version": 1, "inspection_id": str(uuid.uuid4()), "pot_id": pot,
              "captured_at": captured.astimezone(timezone.utc).isoformat(),
              "status": status, "missing_views": missing, "views": views,
              "processing_ms": (time.perf_counter() - start) * 1000,
              "provenance": {"algorithm": "morphology-baseline-v1", "config": asdict(config),
                             "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                             "input_sha256": hashes,
                             "acquisition": manifest}}
    return record, persist(record, images, output)


def main():
    parser = argparse.ArgumentParser(description="Experimental slag pot crack candidate inspection")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    try:
        record, directory = run(args.manifest, args.output)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f"Inspection failed: {error}\n")
    print(json.dumps({"status": record["status"], "report": str(directory / "inspection.md")}))


if __name__ == "__main__":
    main()
