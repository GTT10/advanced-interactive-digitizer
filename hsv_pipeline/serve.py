#!/usr/bin/env python
"""Local web backend for the browser point reviewer (first slice).

    python digitizer/serve.py [--port 8000] [--plot amn_1.0]
    then open http://localhost:8000/

No extra dependency -- stdlib http.server only. It reuses extract_core / edits_io,
so the browser UI shares the exact data model, calibration and edits.json format with
review_points.py (the matplotlib reviewer). The browser does no image processing; it
asks for detected+edited points, lets the human move/add/delete them, and POSTs the
working set back, which the server serialises with points_to_edits and saves.

Routes
------
  GET  /                       index.html
  GET  /app.js                 frontend script
  GET  /api/plots              -> ["amn_1.0", ...]
  GET  /api/state?plot=NAME    -> {plot,width,height,calib,palette,order,series}
  GET  /img?plot=NAME          -> the source PNG
  POST /api/save  {plot,series,export?}-> writes edits.json, then (export!=false)
                  regenerates the CSVs + overlay for that plot; returns row counts.
"""
from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import cv2

from plot_config import load, plot_names
from extract_core import (Point, PALETTE, detect_plot_points, apply_edits)
from edits_io import load_edits, save_edits, edits_for, points_to_edits
from extract_points import run as regenerate   # detect -> apply edits -> CSV + overlay

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def _hex(series: str) -> str:
    b, g, r = PALETTE.get(series, (0, 0, 0))
    return f"#{r:02x}{g:02x}{b:02x}"


def build_state(name: str) -> dict:
    cfg = load(name)
    auto = detect_plot_points(name, cfg)
    pts = apply_edits(auto, edits_for(load_edits(cfg.out_dir), name))
    img = cv2.imread(cfg.image_path)
    h, w = img.shape[:2]
    c = cfg.calib
    series = {
        s: [dict(id=p.id, px=p.px, py=p.py, source=p.source, deleted=p.deleted,
                 note=p.note, orig_px=p.orig_px, orig_py=p.orig_py) for p in plist]
        for s, plist in pts.items()
    }
    return {
        "plot": name, "width": w, "height": h,
        "calib": {"x_p0": c.x_p0, "x_k0": c.x_k0, "x_KperPx": c.x_KperPx,
                  "y0px": c.y0px, "y_log0": c.y_log0, "y_pxPerDecade": c.y_pxPerDecade},
        "palette": {s: _hex(s) for s in series},
        "order": list(series.keys()),
        "series": series,
    }


def save_state(name: str, series_json: dict) -> str:
    cfg = load(name)
    points = {
        s: [Point(id=p["id"], plot=name, series=s, px=float(p["px"]), py=float(p["py"]),
                  source=p.get("source", "auto"), deleted=bool(p.get("deleted")),
                  note=p.get("note", "")) for p in plist]
        for s, plist in series_json.items()
    }
    data = load_edits(cfg.out_dir)
    block = points_to_edits(points)
    if block:
        data[name] = block
    else:
        data.pop(name, None)
    return save_edits(cfg.out_dir, data)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # quiet

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")   # local dev: never serve stale JS
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype):
        if not os.path.exists(path):
            return self._send(404, {"error": "not found"})
        with open(path, "rb") as fh:
            self._send(200, fh.read(), ctype)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/":
                return self._file(os.path.join(WEB, "index.html"), "text/html")
            if u.path == "/app.js":
                return self._file(os.path.join(WEB, "app.js"), "text/javascript")
            if u.path == "/api/plots":
                return self._send(200, plot_names())
            if u.path == "/api/state":
                return self._send(200, build_state(q["plot"][0]))
            if u.path == "/img":
                return self._file(load(q["plot"][0]).image_path, "image/png")
            return self._send(404, {"error": "no route"})
        except Exception as e:                       # surface errors to the browser
            return self._send(500, {"error": repr(e)})

    def do_POST(self):
        u = urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            if u.path == "/api/save":
                plot = body["plot"]
                path = save_state(plot, body["series"])
                out = {"ok": True, "path": path}
                if body.get("export", True):     # regenerate CSV + overlay for this plot
                    out["csv"] = regenerate(plot)
                    out["overlay"] = f"overlay_{plot}.png"
                return self._send(200, out)
            return self._send(404, {"error": "no route"})
        except Exception as e:
            return self._send(500, {"error": repr(e)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--plot", default=None, help="plot to open by default in the UI")
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    default = args.plot or plot_names()[0]
    print(f"digitizer web reviewer on http://localhost:{args.port}/?plot={default}")
    print("Ctrl-C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
