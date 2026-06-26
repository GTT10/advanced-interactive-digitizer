"""Load and expose the plot digitiser configuration (configs/plots.yaml).

This is the only module that knows the YAML schema. Everything else asks for a
``PlotConfig`` by name and works with typed attributes, so the detection code in
``extract_core`` never touches raw config dicts or filesystem paths.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

import yaml

PKG_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PKG_ROOT, "configs", "plots.yaml")


@dataclass(frozen=True)
class Calib:
    """Affine pixel<->data mapping. X is linear in T; Y is log10(mole fraction)."""
    x_p0: float
    x_k0: float
    x_KperPx: float
    y0px: float
    y_log0: float
    y_pxPerDecade: float


@dataclass(frozen=True)
class Species:
    name: str
    ranges: tuple = ()         # tuple of (h0,h1,s0,s1,v0,v1) HSV boxes (explicit)
    shape: str = ""            # "", "circle" or "triangle"
    swatch: tuple | None = None  # (x, y) px of the legend colour swatch; if no explicit
                                 # ranges are given, the HSV box is sampled from here.


@dataclass(frozen=True)
class PlotConfig:
    name: str
    family: str
    image_path: str
    calib: Calib
    box: tuple                 # (left, right, top, bottom) px
    legend: tuple              # (left, right, top, bottom) px
    species: dict              # name -> Species
    green: str | None = None   # output name for the shared GREEN series, if any
    out_dir: str = field(default="")

    def out_series(self, series: str) -> str:
        """Map the internal series key to its output/CSV name (GREEN -> C16H34 etc.)."""
        return self.green if series == "GREEN" and self.green else series


def _make_species(sp: str, cfg: dict) -> Species:
    ranges = tuple(tuple(int(v) for v in box) for box in cfg.get("ranges", []))
    sw = cfg.get("swatch")
    swatch = (int(sw[0]), int(sw[1])) if sw else None
    if not ranges and not swatch:
        raise ValueError(f"species {sp!r}: give either 'ranges' or a 'swatch' [x, y]")
    return Species(name=sp, ranges=ranges, shape=cfg.get("shape", ""), swatch=swatch)


def _resolve(base: str, raw: dict, key: str, default: str) -> str:
    path = raw.get(key, default)
    return path if os.path.isabs(path) else os.path.normpath(os.path.join(base, path))


@lru_cache(maxsize=1)
def _load_raw() -> dict:
    with open(CONFIG_PATH) as fh:
        return yaml.safe_load(fh)


def out_dir() -> str:
    raw = _load_raw()
    d = _resolve(PKG_ROOT, raw, "out_dir", "extracted")
    os.makedirs(d, exist_ok=True)
    return d


def plot_names() -> list[str]:
    return list(_load_raw()["plots"].keys())


@lru_cache(maxsize=None)
def load(name: str) -> PlotConfig:
    raw = _load_raw()
    if name not in raw["plots"]:
        raise KeyError(f"unknown plot {name!r}; known: {', '.join(plot_names())}")
    p = raw["plots"][name]
    image_dir = _resolve(PKG_ROOT, raw, "image_dir", "demo")

    c = p["calib"]
    calib = Calib(
        x_p0=float(c["x_p0"]), x_k0=float(c["x_k0"]),
        x_KperPx=float(c["x_span_K"]) / (float(c["x_px_hi"]) - float(c["x_px_lo"])),
        y0px=float(c["y0px"]), y_log0=float(c["y_log0"]),
        y_pxPerDecade=float(c["y_pxPerDecade"]),
    )

    fam = raw["families"][p["family"]]["species"]
    species = {sp: _make_species(sp, cfg) for sp, cfg in fam.items()}

    return PlotConfig(
        name=name,
        family=p["family"],
        image_path=os.path.join(image_dir, p["image"]),
        calib=calib,
        box=tuple(p["box"]),
        legend=tuple(p["legend"]),
        species=species,
        green=p.get("green"),
        out_dir=out_dir(),
    )
