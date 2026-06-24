from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import TextIO

from aidigitizer.models import DigitizerProject


PROJECT_SCHEMA_VERSION = 1


def save_project(project: DigitizerProject, path: str | Path) -> None:
    """Save project state as a stable JSON file."""

    output = {
        "schema_version": PROJECT_SCHEMA_VERSION,
        "project": project.to_dict(),
    }
    Path(path).write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_project(path: str | Path) -> DigitizerProject:
    """Load a project JSON file."""

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    version = int(data.get("schema_version", 1))
    if version != PROJECT_SCHEMA_VERSION:
        raise ValueError(f"Unsupported project schema version: {version}")
    return DigitizerProject.from_dict(data["project"])


def write_csv(project: DigitizerProject, destination: str | Path | TextIO) -> None:
    """Export all digitized points as CSV.

    Both calibrated data coordinates and raw image coordinates are written. Raw pixel
    coordinates are deliberately kept because they make later audits possible.
    Trusting only final numbers is how spreadsheet folklore becomes science.
    """

    close_after = False
    if isinstance(destination, (str, Path)):
        fp = Path(destination).open("w", newline="", encoding="utf-8")
        close_after = True
    else:
        fp = destination

    try:
        writer = csv.writer(fp)
        writer.writerow(["label", "data_x", "data_y", "image_x", "image_y", "note"])
        for series in project.series:
            for point in series.points:
                writer.writerow(
                    [
                        series.label,
                        "" if point.data_x is None else point.data_x,
                        "" if point.data_y is None else point.data_y,
                        point.image_x,
                        point.image_y,
                        point.note,
                    ]
                )
    finally:
        if close_after:
            fp.close()
