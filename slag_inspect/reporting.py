"""Immutable per-inspection records with transactional SQLite history."""
import hashlib
import json
from pathlib import Path
import sqlite3
import shutil

from PIL import Image, ImageDraw


def markdown(record):
    lines = ["# Slag pot inspection", "", f"- Inspection: `{record['inspection_id']}`",
             f"- Pot: `{record['pot_id']}`", f"- Captured (UTC): {record['captured_at']}",
             f"- Status: **{record['status']}**", "",
             f"- Missing required views: {', '.join(record.get('missing_views', [])) or 'none'}", "",
             "Experimental candidates require qualified review. No fitness-for-service decision.",
             "Lengths are projected estimates, not crack depth or structural severity.", "",
             "| View | Candidate | Priority | Score | Projected length (mm) | Thermal support |",
             "|---|---|---|---:|---:|---|"]
    for view in record["views"]:
        for index, c in enumerate(view["candidates"], 1):
            lines.append(f"| {view['view_id']} | {index}: {c['class']} | {c['priority']} | "
                         f"{c['review_score']} | {c['projected_length_mm']} | {c['thermal_support']} |")
        if not view["candidates"]:
            lines.append(f"| {view['view_id']} | {view['status']} | review | — | — | — |")
    lines.extend(["", "## View quality and inspection limits", ""])
    for view in record["views"]:
        lines.append(f"- {view['view_id']}: {view['status']}. {view['reason']}. "
                     f"Quality: {json.dumps(view['quality'], sort_keys=True)}")
    lines.extend(["", "## Acquisition and provenance", "",
                  f"Processing time: {record['processing_ms']:.2f} ms (excluding persistence).",
                  "", "```json", json.dumps(record["provenance"], indent=2), "```", ""])
    return "\n".join(lines)


def annotate(view, image, path):
    image = Image.fromarray(image).convert("RGB")
    draw = ImageDraw.Draw(image)
    for number, candidate in enumerate(view["candidates"], 1):
        x0, y0, x1, y1 = candidate["bbox_xyxy"]
        draw.rectangle((x0, y0, x1 - 1, y1 - 1), outline="red", width=2)
        draw.text((x0, max(0, y0 - 12)), str(number), fill="red")
    image.save(path)


def persist(record, images, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    directory = output / record["inspection_id"]
    # UUID filenames and exclusive creation prevent accidental overwrite.
    directory.mkdir()
    try:
        payload = json.dumps(record, indent=2, allow_nan=False)
        (directory / "inspection.json").write_text(payload + "\n", encoding="utf-8")
        (directory / "inspection.md").write_text(markdown(record), encoding="utf-8")
        for view in record["views"]:
            value = images[view["view_id"]]
            path = directory / f"{view['view_id']}.png"
            if isinstance(value, (str, Path)):
                shutil.copyfile(value, path)
            else:
                annotate(view, value, path)
        with sqlite3.connect(output / "history.sqlite") as db:
            db.execute("CREATE TABLE IF NOT EXISTS inspections (id TEXT PRIMARY KEY, "
                       "pot_id TEXT NOT NULL, captured_at TEXT NOT NULL, status TEXT NOT NULL, "
                       "report_path TEXT NOT NULL, sha256 TEXT NOT NULL, record_json TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS pot_history ON inspections(pot_id, captured_at)")
            db.execute("INSERT INTO inspections VALUES (?, ?, ?, ?, ?, ?, ?)", (
                record["inspection_id"], record["pot_id"], record["captured_at"], record["status"],
                str(directory), hashlib.sha256(payload.encode()).hexdigest(), payload))
    except Exception:
        shutil.rmtree(directory)
        raise
    return directory
