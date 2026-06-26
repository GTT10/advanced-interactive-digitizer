"""Read/write the human-correction store, ``extracted/edits.json``.

Corrections are kept as data, never as edits to Python source, so re-extraction is
reproducible and the history of hand fixes is reviewable in one file. Schema::

    {
      "<plot>": {
        "<series>": {
          "overrides": [{"target_auto_id": "auto_CO_003", "px": .., "py": .., "note": ""}],
          "manual":    [{"px": .., "py": .., "note": ""}],
          "deleted":   ["auto_CO_005"]
        }
      }
    }

``target_auto_id`` is optional: when absent (e.g. migrated fixes) apply_edits matches
the override to the nearest auto point. ``review_points`` writes it once it knows the id.
"""
from __future__ import annotations

import json
import os

from extract_core import Point


def edits_path(out_dir: str) -> str:
    return os.path.join(out_dir, "edits.json")


def load_edits(out_dir: str) -> dict:
    path = edits_path(out_dir)
    if not os.path.exists(path):
        return {}
    with open(path) as fh:
        return json.load(fh)


def save_edits(out_dir: str, data: dict) -> str:
    path = edits_path(out_dir)
    # drop empty plots/series so the file stays minimal and diffs stay meaningful
    clean = {pl: {s: e for s, e in series.items() if any(e.values())}
             for pl, series in data.items()}
    clean = {pl: series for pl, series in clean.items() if series}
    with open(path, "w") as fh:
        json.dump(clean, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path


def edits_for(data: dict, plot: str) -> dict:
    return data.get(plot, {})


def points_to_edits(points: dict[str, list[Point]]) -> dict:
    """Serialise a reviewed working set ``{series: [Point]}`` back to the edits schema
    for one plot. Untouched auto points contribute nothing; the file holds only the
    human delta."""
    out: dict[str, dict] = {}
    for series, pts in points.items():
        ov, man, dele = [], [], []
        for p in pts:
            if p.deleted:
                if p.id.startswith("auto_"):
                    dele.append(p.id)
                continue                               # deleted manual/standalone -> gone
            if p.source == "manual":
                man.append(_xy(p))
            elif p.source == "override":
                entry = _xy(p)
                if p.id.startswith("auto_"):
                    entry = {"target_auto_id": p.id, **entry}
                ov.append(entry)
            # untouched auto -> no entry
        block = {}
        if ov:
            block["overrides"] = ov
        if man:
            block["manual"] = man
        if dele:
            block["deleted"] = sorted(dele)
        if block:
            out[series] = block
    return out


def _xy(p: Point) -> dict:
    d = {"px": round(p.px, 2), "py": round(p.py, 2)}
    if p.note:
        d["note"] = p.note
    return d
