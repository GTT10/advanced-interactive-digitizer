"""Detection, coordinate transforms and I/O for the plot digitiser.

Pure logic, no UI: ``review_points`` and ``extract_points`` both call into here.

Pipeline per plot:
    detect_plot_points(name)  -> {series: [auto Point, ...]}      (cv2, deterministic)
    apply_edits(points, e)    -> {series: [Point, ...]}           (human corrections)
    export_csv / make_overlay -> final artefacts

A Point lives in PIXEL space (px, py); data coords (T, mole_fraction) are derived
on demand via px_to_data. That mirrors how a human edits the figure -- you drag a
marker on the image, not in T/mf -- and keeps the calibration the single source of
truth for the mapping. The detection algorithm (HSV segmentation, dash-stripping
morphology, circle/triangle centre estimators) is unchanged from the original
extract_points.py; only its configuration and the surrounding plumbing moved.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

import cv2
import numpy as np

from plot_config import Calib, PlotConfig, load

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Point:
    """One extracted marker, positioned in image pixels.

    ``id``      stable identity: ``auto_<series>_<NNN>`` (detection) or
                ``manual_<series>_<NNN>`` (hand-added). Auto ids are assigned in a
                deterministic spatial order so an edit keyed on an id survives a
                re-run as long as detection is unchanged.
    ``source``  "auto" | "override" (auto point a human nudged) | "manual".
    ``orig_*``  the detection pixel for auto/override points (None for manual);
                lets the reviewer tell a moved point from an untouched one on save.
    """
    id: str
    plot: str
    series: str
    px: float
    py: float
    source: str = "auto"
    deleted: bool = False
    orig_px: float | None = None
    orig_py: float | None = None
    note: str = ""

    @property
    def moved(self) -> bool:
        """True if an auto point has been dragged off its detected pixel."""
        if self.orig_px is None:
            return False
        return abs(self.px - self.orig_px) > 1e-6 or abs(self.py - self.orig_py) > 1e-6


# ---------------------------------------------------------------------------
# Coordinate transforms
# ---------------------------------------------------------------------------


def px_to_data(col: float, row: float, c: Calib) -> tuple[float, float]:
    T = c.x_k0 + (col - c.x_p0) * c.x_KperPx
    logmf = c.y_log0 - (row - c.y0px) / c.y_pxPerDecade
    return T, 10.0 ** logmf


def data_to_px(T: float, mf: float, c: Calib) -> tuple[float, float]:
    col = c.x_p0 + (T - c.x_k0) / c.x_KperPx
    row = c.y0px + (c.y_log0 - math.log10(mf)) * c.y_pxPerDecade
    return col, row


# ---------------------------------------------------------------------------
# Detection tunables (verbatim from the original extract_points.py)
# ---------------------------------------------------------------------------
FULL_AREA = 230    # area of a fully-visible marker; below this = partly occluded
MERGE_DIST = 12    # blobs whose centroids are closer than this are one marker
OPEN_RMAX = 7      # largest opening radius (strips a dash even collinear w/ marker)
OPEN_RMIN = 3      # smallest opening radius (preserves thin-pointed stars)
CORE_MIN = 110     # a marker body keeps at least this opened-core area

# Circle-fit acceptance window (px), used only for round markers.
FIT_RMIN, FIT_RMAX, FIT_RES_MAX = 9.5, 13.5, 3.0
FIT_MIN_PTS = 8

OVERRIDE_RADIUS = 18   # px; an auto point this close to an override is the one it replaces

PALETTE = {  # BGR for overlay
    "O2": (40, 40, 220), "A2CH3": (220, 60, 40), "CO": (40, 180, 40),
    "CO2": (200, 40, 200), "C2H2": (40, 140, 240),
    "GREEN": (40, 180, 40), "C16H34": (40, 180, 40), "N16H34": (40, 180, 40),
    "H2": (200, 40, 200), "CH2O": (20, 120, 150),
}


# ---------------------------------------------------------------------------
# Low-level cv2 detection (unchanged algorithm)
# ---------------------------------------------------------------------------


def mask_for(hsv, ranges):
    m = np.zeros(hsv.shape[:2], np.uint8)
    for (hl, hh, sl, sh, vl, vh) in ranges:
        m |= cv2.inRange(hsv, (hl, sl, vl), (hh, sh, vh))
    return m


def median_hsv(hsv, x: int, y: int, win: int = 3) -> tuple[int, int, int]:
    """Median (H, S, V) of a small patch around (x, y) -- robust to a stray edge px."""
    y0, y1 = max(0, y - win), y + win + 1
    x0, x1 = max(0, x - win), x + win + 1
    patch = hsv[y0:y1, x0:x1].reshape(-1, 3)
    return tuple(int(np.median(patch[:, i])) for i in range(3))


def hsv_range_from_swatch(h: int, s: int, v: int, h_tol: int = 8,
                          s_floor: int = 50, v_floor: int = 50):
    """Build HSV inRange box(es) around a sampled swatch colour (OpenCV hue 0-179).

    Hue is bracketed by +/- h_tol and wraps near 0/179 into two boxes (red). S and V
    are left-open from a floor below the sample up to 255, so antialiased/darker marker
    pixels of the same hue are still caught. This is a *starting* range -- colours that
    overlap in hue and split only by value (e.g. HXN CO vs CH2O) still need hand tuning."""
    h, s, v = int(round(h)), int(round(s)), int(round(v))
    smin = max(s_floor, s - 90)
    vmin = max(v_floor, v - 90)
    lo, hi = h - h_tol, h + h_tol
    if lo < 0:
        return [(0, hi, smin, 255, vmin, 255), (180 + lo, 179, smin, 255, vmin, 255)]
    if hi > 179:
        return [(lo, 179, smin, 255, vmin, 255), (0, hi - 180, smin, 255, vmin, 255)]
    return [(lo, hi, smin, 255, vmin, 255)]


def resolve_ranges(spec, hsv):
    """HSV boxes for a species: explicit ``ranges`` if given, else sampled from its
    legend ``swatch``. Explicit ranges always win so detection stays reproducible."""
    if spec.ranges:
        return spec.ranges
    if spec.swatch:
        return tuple(hsv_range_from_swatch(*median_hsv(hsv, *spec.swatch)))
    raise ValueError(f"species {spec.name!r} has neither ranges nor swatch")


def in_rect(cx, cy, rect):
    l, r, t, b = rect
    return l <= cx <= r and t <= cy <= b


def fit_circle(comp):
    """Algebraic least-squares circle through the outer contour of blob ``comp``.

    For a round marker partly overwritten by another series, the colour mask loses
    a chunk and both its bbox centre and centroid drift toward the surviving side.
    A circle fit recovers the centre from whatever arc remains. Returns
    ``(cx, cy, r, rms_residual, n_pts)`` in the crop frame, or None if too short."""
    cnts, _ = cv2.findContours((comp > 0).astype(np.uint8),
                               cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None
    pts = max(cnts, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)
    if len(pts) < FIT_MIN_PTS:
        return None
    x, y = pts[:, 0], pts[:, 1]
    A = np.column_stack([x, y, np.ones_like(x)])
    sol, *_ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
    cx, cy = sol[0] / 2.0, sol[1] / 2.0
    r = np.sqrt(max(0.0, sol[2] + cx * cx + cy * cy))
    res = float(np.sqrt(((np.hypot(x - cx, y - cy) - r) ** 2).mean()))
    return cx, cy, r, res, len(pts)


def _strong_open_bbox(comp, rmax, rmin, core_min):
    """Centre and area of the marker body after the strongest dash-stripping opening
    that still leaves >= core_min px. core_area is 0 (raw bbox) if nothing survives."""
    b = (comp > 0).astype(np.uint8)
    for r in range(rmax, rmin - 1, -1):
        ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1,) * 2)
        op = cv2.morphologyEx(b, cv2.MORPH_OPEN, ker)
        n, lab, stats, cent = cv2.connectedComponentsWithStats(op, 8)
        if n <= 1:
            continue
        j = 1 + int(np.argmax(stats[1:, 4]))
        if stats[j, 4] < core_min:
            continue
        x, y, w, h, a = stats[j]
        return x + (w - 1) / 2.0, y + (h - 1) / 2.0, w, h, int(a)
    ys, xs = np.where(b > 0)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    return (x0 + x1) / 2.0, (y0 + y1) / 2.0, x1 - x0 + 1, y1 - y0 + 1, 0


def _light_open_centroid_y(comp, r=2):
    """y of the centroid of the largest component after a light opening; matplotlib
    puts a triangle's data point at its circumcircle centre (= centroid, ~1/3 up
    from the base), not the bbox mid-height. A light opening detaches a thin dash
    while keeping the apex."""
    b = (comp > 0).astype(np.uint8)
    op = cv2.morphologyEx(b, cv2.MORPH_OPEN,
                          cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1,) * 2))
    n, lab, stats, cent = cv2.connectedComponentsWithStats(op, 8)
    if n <= 1:
        ys, _ = np.where(b > 0)
        return float(ys.mean())
    j = 1 + int(np.argmax(stats[1:, 4]))
    return float(cent[j][1])


def marker_center(comp, rmax=OPEN_RMAX, rmin=OPEN_RMIN, core_min=CORE_MIN, shape=""):
    """Geometric centre of one colour blob (a marker, possibly with a fused dash).

    Strong morphological opening strips the thin Sim-line dash even where collinear,
    leaving a body whose bbox centre is symmetric about the data point for every
    shape. ``shape`` refines: "circle" tries a circle fit first; "triangle" takes y
    from the light-opening centroid. Returns ``(cx, cy, core_area)``; core_area 0
    means nothing survived (pure dash / heavy occlusion) and the raw bbox is used."""
    if shape == "circle":
        fit = fit_circle(comp)
        if fit is not None:
            fcx, fcy, r, res, _ = fit
            if FIT_RMIN < r < FIT_RMAX and res < FIT_RES_MAX:
                return fcx, fcy, int(round(np.pi * r * r))

    cx, cy, w, h, core_area = _strong_open_bbox(comp, rmax, rmin, core_min)
    if shape == "triangle" and core_area > 0:
        cy = _light_open_centroid_y(comp)
    return cx, cy, core_area


def find_markers(mask, box, legend, min_dim=15, max_area=3000, elong=1.5, shape=""):
    """Marker geometric centres ``[(col, row, area)]`` for one species colour mask.

    Keeps only confident, blob-like components (min side >= min_dim rejects dashes,
    area >= FULL_AREA rejects dash junctions), places each at its dash-stripped
    centre, and drops anything inside the box/legend rectangles. An elongated blob
    whose core does not survive the opening was a pure dash -> dropped."""
    L, R, T, B = box
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=1)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(mask, 8)
    pts = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < FULL_AREA or area > max_area:
            continue
        if min(w, h) < min_dim:
            continue
        elongated = max(w, h) / float(min(w, h)) > elong
        bx, by, core_area = marker_center(
            (lab[y:y + h, x:x + w] == i).astype(np.uint8) * 255, shape=shape)
        if elongated and core_area < CORE_MIN:
            continue
        cx, cy = x + bx, y + by
        if not (L < cx < R and T < cy < B):
            continue
        if in_rect(cx, cy, legend):
            continue
        pts.append((cx, cy, float(area)))
    return merge_near(pts)


def merge_near(pts, dist=MERGE_DIST):
    """Collapse blobs within ``dist`` px (one marker split by a crossing dash) into
    one point at the largest blob. Returns ``[(cx, cy), ...]``."""
    pts = sorted(pts, key=lambda p: -p[2])
    kept = []
    for cx, cy, area in pts:
        if any((cx - kx) ** 2 + (cy - ky) ** 2 < dist * dist for kx, ky in kept):
            continue
        kept.append((cx, cy))
    return kept


# ---------------------------------------------------------------------------
# High-level: detect / apply edits / export
# ---------------------------------------------------------------------------


def detect_plot_points(name: str, cfg: PlotConfig | None = None) -> dict[str, list[Point]]:
    """Run auto-detection for one plot. Returns ``{out_series: [auto Point, ...]}``.

    Auto ids are assigned in a deterministic spatial order (by px, then py) so the
    same blob gets the same id on every run; edits.json keys on these ids."""
    cfg = cfg or load(name)
    img = cv2.imread(cfg.image_path)
    if img is None:
        raise FileNotFoundError(cfg.image_path)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    out: dict[str, list[Point]] = {}
    for sp, spec in cfg.species.items():
        series = cfg.out_series(sp)
        raw = find_markers(mask_for(hsv, resolve_ranges(spec, hsv)), cfg.box, cfg.legend,
                           shape=spec.shape)
        pts = []
        for idx, (cx, cy) in enumerate(sorted(raw, key=lambda p: (round(p[0], 1),
                                                                  round(p[1], 1))), 1):
            pts.append(Point(id=f"auto_{series}_{idx:03d}", plot=name, series=series,
                             px=cx, py=cy, source="auto", orig_px=cx, orig_py=cy))
        out[series] = pts
    return out


def _nearest(points: list[Point], px: float, py: float, radius: float):
    """The auto/override Point within ``radius`` px of (px, py) closest to it, or None."""
    best, bestd = None, radius * radius
    for p in points:
        if p.source == "manual" or p.deleted:
            continue
        d = (p.px - px) ** 2 + (p.py - py) ** 2
        if d < bestd:
            best, bestd = p, d
    return best


def apply_edits(points: dict[str, list[Point]], edits: dict,
                radius: float = OVERRIDE_RADIUS) -> dict[str, list[Point]]:
    """Apply one plot's edits onto freshly detected auto points.

    ``edits`` is ``{series: {"overrides": [...], "manual": [...], "deleted": [...]}}``.
      * deleted  -- auto ids to flag ``deleted=True`` (kept so the reviewer can restore).
      * overrides-- move an auto point to (px, py); target by ``target_auto_id`` if it
                    still exists, else the nearest auto point within ``radius``.
      * manual   -- add a new hand-placed point.
    Returns a fresh ``{series: [Point, ...]}`` (input not mutated)."""
    result: dict[str, list[Point]] = {s: [Point(**vars(p)) for p in ps]
                                       for s, ps in points.items()}
    for series, e in (edits or {}).items():
        pts = result.setdefault(series, [])
        by_id = {p.id: p for p in pts}

        for pid in e.get("deleted", []):
            if pid in by_id:
                by_id[pid].deleted = True

        for ov in e.get("overrides", []):
            px, py = float(ov["px"]), float(ov["py"])
            target = by_id.get(ov.get("target_auto_id")) or _nearest(pts, px, py, radius)
            if target is not None and not target.deleted:
                target.px, target.py = px, py
                target.source = "override"
                target.note = ov.get("note", "")
            else:                                  # nothing nearby -> standalone add
                pts.append(Point(id=f"override_{series}_{len(pts):03d}", plot=next(
                    (p.plot for p in pts), ""), series=series, px=px, py=py,
                    source="override", note=ov.get("note", "")))

        plot = next((p.plot for p in pts), "")
        for i, mp in enumerate(e.get("manual", []), 1):
            pts.append(Point(id=f"manual_{series}_{i:03d}", plot=plot, series=series,
                             px=float(mp["px"]), py=float(mp["py"]),
                             source="manual", note=mp.get("note", "")))
    return result


def live_points(series_points: list[Point]) -> list[Point]:
    """Non-deleted points of a series, sorted left-to-right (== ascending T)."""
    return sorted((p for p in series_points if not p.deleted), key=lambda p: (p.px, p.py))


def export_csv(points: dict[str, list[Point]], cfg: PlotConfig) -> dict[str, int]:
    """Write one ``<plot>_<series>.csv`` per series (T_K, mole_fraction; T-sorted).
    Returns ``{series: n_rows}``."""
    summary = {}
    for series, pts in points.items():
        rows = sorted(px_to_data(p.px, p.py, cfg.calib) for p in live_points(pts))
        path = os.path.join(cfg.out_dir, f"{cfg.name}_{series}.csv")
        with open(path, "w") as fh:
            fh.write("T_K,mole_fraction\n")
            for T, mf in rows:
                fh.write(f"{T:.1f},{mf:.4e}\n")
        summary[series] = len(rows)
    return summary


def make_overlay(points: dict[str, list[Point]], cfg: PlotConfig,
                 out_path: str | None = None):
    """Draw rings + crosses + T-order numbers over the source image. Hand-edited
    points (override/manual) get a cyan ring to stand out from auto detections."""
    img = cv2.imread(cfg.image_path)
    cv2.rectangle(img, (cfg.legend[0], cfg.legend[2]), (cfg.legend[1], cfg.legend[3]),
                  (120, 120, 120), 1)
    for series, pts in points.items():
        col = PALETTE.get(series, (0, 0, 0))
        for idx, p in enumerate(live_points(pts), 1):
            ring = (255, 255, 0) if p.source != "auto" else col
            ix, iy = int(round(p.px)), int(round(p.py))
            cv2.circle(img, (ix, iy), 11, ring, 2)
            cv2.drawMarker(img, (ix, iy), (0, 0, 0), cv2.MARKER_CROSS, 9, 1)
            cv2.putText(img, str(idx), (ix + 12, iy - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, col, 1, cv2.LINE_AA)
    out_path = out_path or os.path.join(cfg.out_dir, f"overlay_{cfg.name}.png")
    cv2.imwrite(out_path, img)
    return out_path
