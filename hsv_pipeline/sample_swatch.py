#!/usr/bin/env python
"""Suggest HSV colour ranges by sampling the legend swatches of a plot.

    python digitizer/sample_swatch.py [plot ...]      # default: all plots

For each plot it scans inside the legend rectangle for saturated colour marks (the
per-species swatch + dashed sample line; black text and white background are filtered
out by an S/V floor), reports each mark's median HSV, and prints a paste-ready
``ranges:`` line built by extract_core.hsv_range_from_swatch. It also writes an
annotated legend crop to ``extracted/swatches_<plot>.png`` so the read can be eyeballed.

This realises the "pick the HSV centre from the legend colour" idea as an *assist*: it
proposes a starting box you drop into configs/plots.yaml (or reference via ``swatch``).
Colours that overlap in hue and split only by value -- HXN CO (bright orange) vs CH2O
(dark olive) -- will read as one cluster here and still need the hand split kept in
plots.yaml; this tool never edits the config.
"""
import sys

import cv2
import numpy as np

from plot_config import load, plot_names, out_dir
from extract_core import hsv_range_from_swatch

S_MIN, V_MIN = 60, 50      # floor that drops black text and white background
MIN_AREA = 100             # ignore antialiasing specks (real swatches are >=~570 px)
H_MERGE, V_MERGE = 6, 45   # merge marks of near-equal hue AND value (swatch + its line)


def _hue_dist(a: int, b: int) -> int:
    d = abs(a - b)
    return min(d, 180 - d)


def find_swatches(name: str):
    cfg = load(name)
    bgr = cv2.imread(cfg.image_path)
    if bgr is None:
        raise FileNotFoundError(cfg.image_path)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    l, r, t, b = cfg.legend
    H, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    mask = np.zeros(hsv.shape[:2], np.uint8)
    mask[t:b, l:r] = (((S >= S_MIN) & (V >= V_MIN))[t:b, l:r].astype(np.uint8) * 255)

    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    blobs = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if a < MIN_AREA:
            continue
        m = lab == i
        blobs.append(dict(x=int(x), y=int(y), w=int(w), h=int(h), area=int(a),
                          H=int(np.median(H[m])), S=int(np.median(S[m])),
                          V=int(np.median(V[m]))))

    # merge the swatch and its dashed sample line (same hue & value) into one entry
    blobs.sort(key=lambda d: (d["y"], d["x"]))
    merged = []
    for bl in blobs:
        for mg in merged:
            if _hue_dist(bl["H"], mg["H"]) <= H_MERGE and abs(bl["V"] - mg["V"]) <= V_MERGE:
                wsum = mg["area"] + bl["area"]
                for k in ("H", "S", "V"):
                    mg[k] = int(round((mg[k] * mg["area"] + bl[k] * bl["area"]) / wsum))
                mg["x"], mg["y"] = min(mg["x"], bl["x"]), min(mg["y"], bl["y"])
                mg["w"] = max(mg["x"] + mg["w"], bl["x"] + bl["w"]) - mg["x"]
                mg["h"] = max(mg["y"] + mg["h"], bl["y"] + bl["h"]) - mg["y"]
                mg["area"] = wsum
                break
        else:
            merged.append(dict(bl))
    return cfg, bgr, merged


def run(name: str):
    cfg, bgr, marks = find_swatches(name)
    print(f"\n{name}: {len(marks)} colour mark(s) in legend {cfg.legend}")
    for i, m in enumerate(marks, 1):
        rng = hsv_range_from_swatch(m["H"], m["S"], m["V"])
        rng_yaml = "[" + ", ".join("[" + ", ".join(map(str, box)) + "]" for box in rng) + "]"
        print(f"  {i}: HSV=({m['H']:3d},{m['S']:3d},{m['V']:3d})  "
              f"swatch=[{m['x'] + m['w'] // 2}, {m['y'] + m['h'] // 2}]  "
              f"area={m['area']:4d}")
        print(f"       ranges: {rng_yaml}")
        cv2.rectangle(bgr, (m["x"], m["y"]), (m["x"] + m["w"], m["y"] + m["h"]),
                      (0, 0, 0), 1)
        cv2.putText(bgr, f"{m['H']},{m['S']},{m['V']}", (m["x"], m["y"] - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1, cv2.LINE_AA)
    l, r, t, b = cfg.legend
    pad = 12
    crop = bgr[max(0, t - pad):b + pad, max(0, l - pad):r + pad]
    path = f"{out_dir()}/swatches_{name}.png"
    cv2.imwrite(path, crop)
    print(f"  -> {path}")


if __name__ == "__main__":
    for nm in (sys.argv[1:] or plot_names()):
        run(nm)
