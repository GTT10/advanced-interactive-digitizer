#!/usr/bin/env python
"""Batch extraction CLI: detect -> apply edits.json -> write CSVs + overlays.

    python digitizer/extract_points.py                 # all plots
    python digitizer/extract_points.py amn_1.0 hxn_0.5 # selected plots

Auto-detected markers plus the human corrections recorded in extracted/edits.json
go to one CSV per (plot, series) and one overlay_<plot>.png, all under out_dir
(extracted/). Detection itself is in extract_core; this module is only plumbing.
"""
import sys

from plot_config import load, plot_names
from extract_core import detect_plot_points, apply_edits, export_csv, make_overlay
from edits_io import load_edits, edits_for


def run(name: str) -> dict:
    cfg = load(name)
    auto = detect_plot_points(name, cfg)
    pts = apply_edits(auto, edits_for(load_edits(cfg.out_dir), name))
    summary = export_csv(pts, cfg)
    make_overlay(pts, cfg)
    return summary


if __name__ == "__main__":
    names = sys.argv[1:] or plot_names()
    for nm in names:
        s = run(nm)
        print(nm, "->", ", ".join(f"{k}:{v}" for k, v in s.items()))
