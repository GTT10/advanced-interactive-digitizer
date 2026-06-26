#!/usr/bin/env python
"""Interactive matplotlib reviewer for hand-correcting extracted points.

    python digitizer/review_points.py <plot> [<series>]
    e.g. python digitizer/review_points.py amn_1.0 CO

Loads auto-detected points + the current edits.json, lets you nudge / add / delete /
re-key markers on the figure, and writes the corrections back to edits.json. It does
NO image processing -- detection lives in extract_core. After saving, run
``extract_points.py`` to regenerate the CSVs and overlay with the new edits.

You edit in PIXEL space (you drag the marker on the image); data coords (T, mf) are
only used by the 'r' key for direct numeric entry, converted via the calibration.

Keys
----
  arrows            move selected point  0.5 px / zoom   (WPD-style)
  shift+arrows      move selected point  5   px / zoom
  tab / shift+tab   select next / previous point in this series
  , .               previous / next series
  click             select nearest point in series; empty space -> add a point
  d / delete        toggle delete on the selected point
  r                 type T_K and mole_fraction to place the point exactly
  u                 restore an overridden point back to its auto detection
  s                 save edits.json
  q                 quit (warns if there are unsaved edits)

Mouse wheel zooms about the cursor; the toolbar pan/zoom also work. The move step
follows WPD: ``step = base_px / zoom`` where ``zoom = full_width / current_view_width``.
"""
from __future__ import annotations

import sys

import cv2
import matplotlib
import matplotlib.pyplot as plt

from plot_config import load, plot_names
from extract_core import (Point, detect_plot_points, apply_edits, data_to_px,
                          px_to_data, PALETTE)
from edits_io import load_edits, save_edits, edits_for, points_to_edits

BASE_PX = 0.5          # WPD nudge at zoom == 1 (one image width fills the view)
SHIFT_PX = 5.0
CLICK_PX = 12.0        # within this many image px of a marker -> select, else add


def _rgb(series):
    b, g, r = PALETTE.get(series, (0, 0, 0))
    return (r / 255.0, g / 255.0, b / 255.0)


class Reviewer:
    def __init__(self, name: str, series: str | None = None):
        self.cfg = load(name)
        self.name = name
        # Image in RGB for imshow; axes are then in pixel coords (x=col, y=row).
        import cv2
        bgr = cv2.imread(self.cfg.image_path)
        if bgr is None:
            raise FileNotFoundError(self.cfg.image_path)
        self.img = bgr[:, :, ::-1]
        self.img_h, self.img_w = self.img.shape[:2]

        auto = detect_plot_points(name, self.cfg)
        self.points = apply_edits(auto, edits_for(load_edits(self.cfg.out_dir), name))
        self.series_list = list(self.points.keys())
        self.si = self.series_list.index(series) if series in self.series_list else 0
        self.sel: Point | None = None
        self.dirty = False
        self._artists: list = []
        self.fig = self.ax = None

    # -- helpers ----------------------------------------------------------
    @property
    def series(self) -> str:
        return self.series_list[self.si]

    def _series_points(self, live_only=False, ordered=True):
        pts = self.points[self.series]
        if live_only:
            pts = [p for p in pts if not p.deleted]
        return sorted(pts, key=lambda p: (p.px, p.py)) if ordered else pts

    def _zoom(self) -> float:
        x0, x1 = self.ax.get_xlim()
        w = abs(x1 - x0)
        return self.img_w / w if w else 1.0

    def _step(self, shift: bool) -> float:
        return (SHIFT_PX if shift else BASE_PX) / self._zoom()

    def _next_manual_id(self) -> str:
        n = sum(1 for p in self.points[self.series] if p.id.startswith("manual_"))
        return f"manual_{self.series}_{n + 1:03d}"

    def _mark_override(self, p: Point):
        """A nudged auto point becomes an override; manual/override keep their kind."""
        if p.source == "auto":
            p.source = "override"

    # -- mutations --------------------------------------------------------
    def move(self, dx: float, dy: float):
        if self.sel is None:
            return
        self.sel.px += dx
        self.sel.py += dy
        self._mark_override(self.sel)
        self.dirty = True

    def toggle_delete(self):
        if self.sel is None:
            return
        self.sel.deleted = not self.sel.deleted
        self.dirty = True

    def restore_auto(self):
        if self.sel is None or not self.sel.id.startswith("auto_"):
            return
        self.sel.px, self.sel.py = self.sel.orig_px, self.sel.orig_py
        self.sel.source = "auto"
        self.sel.note = ""
        self.sel.deleted = False
        self.dirty = True

    def set_from_data(self, T: float, mf: float):
        if self.sel is None:
            return
        self.sel.px, self.sel.py = data_to_px(T, mf, self.cfg.calib)
        self._mark_override(self.sel)
        self.dirty = True

    def add_manual(self, px: float, py: float) -> Point:
        p = Point(id=self._next_manual_id(), plot=self.name, series=self.series,
                  px=px, py=py, source="manual")
        self.points[self.series].append(p)
        self.dirty = True
        return p

    def select_offset(self, d: int):
        pts = self._series_points()
        if not pts:
            self.sel = None
            return
        i = pts.index(self.sel) if self.sel in pts else -1 if d > 0 else 0
        self.sel = pts[(i + d) % len(pts)]

    def change_series(self, d: int):
        self.si = (self.si + d) % len(self.series_list)
        self.sel = None

    def select_near(self, px: float, py: float):
        pts = self._series_points()
        if pts:
            p = min(pts, key=lambda q: (q.px - px) ** 2 + (q.py - py) ** 2)
            if (p.px - px) ** 2 + (p.py - py) ** 2 <= CLICK_PX ** 2:
                self.sel = p
                return
        self.sel = self.add_manual(px, py)

    def save(self):
        data = load_edits(self.cfg.out_dir)               # all plots
        block = points_to_edits(self.points)
        if block:
            data[self.name] = block
        else:
            data.pop(self.name, None)
        path = save_edits(self.cfg.out_dir, data)
        self.dirty = False
        print(f"[saved] {path}")

    # -- rendering --------------------------------------------------------
    def _draw(self):
        for a in self._artists:
            a.remove()
        self._artists = []
        for s in self.series_list:
            cur = s == self.series
            col = _rgb(s)
            live = [p for p in self.points[s] if not p.deleted]
            auto = [p for p in live if p.source == "auto"]
            edited = [p for p in live if p.source != "auto"]
            dead = [p for p in self.points[s] if p.deleted]
            base_a = 1.0 if cur else 0.30
            ms = 9 if cur else 6
            if auto:
                self._scatter(auto, marker="o", s=ms ** 2, facecolor=col,
                              edgecolor="black", lw=0.6, alpha=base_a, zorder=3)
            if edited:
                self._scatter(edited, marker="o", s=(ms + 1) ** 2, facecolor=col,
                              edgecolor="cyan", lw=1.8, alpha=base_a, zorder=4)
            if dead and cur:
                self._scatter(dead, marker="x", s=ms ** 2, c="0.5", lw=1.2,
                              alpha=0.5, zorder=2)
        if self.sel is not None:
            self._scatter([self.sel], marker="o", s=220, facecolor="none",
                          edgecolor="red", lw=2.0, zorder=5)
        self._title()
        self.fig.canvas.draw_idle()

    def _scatter(self, pts, **kw):
        xs = [p.px for p in pts]
        ys = [p.py for p in pts]
        self._artists.append(self.ax.scatter(xs, ys, **kw))

    def _title(self):
        n_live = len(self._series_points(live_only=True))
        sel = "-"
        if self.sel is not None:
            T, mf = px_to_data(self.sel.px, self.sel.py, self.cfg.calib)
            tag = "DEL " if self.sel.deleted else ""
            sel = f"{tag}{self.sel.id} [{self.sel.source}]  T={T:.1f}K  mf={mf:.4e}"
        dirty = "  *unsaved*" if self.dirty else ""
        self.ax.set_title(
            f"{self.name}   series {self.si + 1}/{len(self.series_list)}: "
            f"{self.series} ({n_live} live)   zoom x{self._zoom():.1f}{dirty}\n"
            f"sel: {sel}", fontsize=9)

    # -- events -----------------------------------------------------------
    def _on_key(self, e):
        k = e.key
        if k in ("left", "right", "up", "down",
                 "shift+left", "shift+right", "shift+up", "shift+down"):
            shift = k.startswith("shift+")
            step = self._step(shift)
            d = k.split("+")[-1]
            self.move(-step if d == "left" else step if d == "right" else 0,
                      -step if d == "up" else step if d == "down" else 0)
        elif k == "tab":
            self.select_offset(+1)
        elif k in ("shift+tab", "backtab"):
            self.select_offset(-1)
        elif k == ".":
            self.change_series(+1)
        elif k == ",":
            self.change_series(-1)
        elif k in ("d", "delete"):
            self.toggle_delete()
        elif k == "u":
            self.restore_auto()
        elif k == "r":
            self._prompt_data()
        elif k == "s":
            self.save()
        elif k == "q":
            if self.dirty:
                print("[quit] unsaved edits -- press s to save, or q again to discard")
                self.dirty = False          # second q within session discards
                return
            plt.close(self.fig)
            return
        else:
            return
        self._draw()

    def _on_click(self, e):
        if e.inaxes is not self.ax or self.fig.canvas.toolbar.mode:
            return                          # ignore clicks while pan/zoom tool active
        if e.xdata is None:
            return
        self.select_near(e.xdata, e.ydata)
        self._draw()

    def _on_scroll(self, e):
        if e.inaxes is not self.ax or e.xdata is None:
            return
        f = 0.8 if e.button == "up" else 1.25
        for get, set_ in ((self.ax.get_xlim, self.ax.set_xlim),
                          (self.ax.get_ylim, self.ax.set_ylim)):
            lo, hi = get()
            c = e.xdata if get is self.ax.get_xlim else e.ydata
            set_(c + (lo - c) * f, c + (hi - c) * f)
        self._draw()

    def _prompt_data(self):
        if self.sel is None:
            print("[r] select a point first")
            return
        try:
            T = float(input("  T_K: "))
            mf = float(input("  mole_fraction: "))
        except (ValueError, EOFError):
            print("  cancelled")
            return
        self.set_from_data(T, mf)

    # -- run --------------------------------------------------------------
    def run(self):
        for km in ("save", "quit", "quit_all", "fullscreen", "back", "forward",
                   "home", "yscale", "xscale", "grid", "grid_minor"):
            matplotlib.rcParams[f"keymap.{km}"] = []
        self.fig, self.ax = plt.subplots(figsize=(13, 9))
        self.ax.imshow(self.img, origin="upper")
        self.ax.set_xlim(0, self.img_w)
        self.ax.set_ylim(self.img_h, 0)
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)
        self.fig.canvas.mpl_connect("button_press_event", self._on_click)
        self.fig.canvas.mpl_connect("scroll_event", self._on_scroll)
        print(__doc__.split("Keys")[1])
        self._draw()
        plt.show()


def main(argv):
    if not argv:
        print(f"usage: review_points.py <plot> [<series>]   plots: {', '.join(plot_names())}")
        return 1
    Reviewer(argv[0], argv[1] if len(argv) > 1 else None).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
