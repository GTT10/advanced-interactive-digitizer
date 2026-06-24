from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Any


class AxisScale(str, Enum):
    """Supported axis scales."""

    LINEAR = "linear"
    LOG10 = "log10"


@dataclass(frozen=True)
class AxisCalibration:
    """One-dimensional calibration along an arbitrary image-space axis.

    The mapping projects a clicked pixel onto the line connecting the two calibration
    pixels, then interpolates between the two data values. This works for tilted or
    scanned plots as long as the axes are still approximately straight.
    """

    pixel1: tuple[float, float]
    value1: float
    pixel2: tuple[float, float]
    value2: float
    scale: AxisScale = AxisScale.LINEAR

    def __post_init__(self) -> None:
        object.__setattr__(self, "scale", AxisScale(self.scale))
        if self.pixel1 == self.pixel2:
            raise ValueError("Calibration pixels must not be identical.")
        if self.scale is AxisScale.LOG10 and (self.value1 <= 0 or self.value2 <= 0):
            raise ValueError("Log-scale calibration values must be positive.")

    def pixel_to_value(self, pixel: tuple[float, float]) -> float:
        """Convert one image-space pixel to a data value."""

        x1, y1 = self.pixel1
        x2, y2 = self.pixel2
        px, py = pixel

        dx = x2 - x1
        dy = y2 - y1
        denom = dx * dx + dy * dy
        if denom == 0:
            raise ValueError("Calibration pixels must not be identical.")

        t = ((px - x1) * dx + (py - y1) * dy) / denom

        if self.scale is AxisScale.LINEAR:
            return self.value1 + t * (self.value2 - self.value1)

        log_v1 = math.log10(self.value1)
        log_v2 = math.log10(self.value2)
        return 10 ** (log_v1 + t * (log_v2 - log_v1))

    def value_to_pixel_parameter(self, value: float) -> float:
        """Return the normalized parameter t for a data value on this axis."""

        if self.scale is AxisScale.LINEAR:
            denom = self.value2 - self.value1
            if denom == 0:
                raise ValueError("Calibration values must not be identical.")
            return (value - self.value1) / denom

        if value <= 0:
            raise ValueError("Log-scale values must be positive.")
        log_v1 = math.log10(self.value1)
        log_v2 = math.log10(self.value2)
        denom = log_v2 - log_v1
        if denom == 0:
            raise ValueError("Calibration values must not be identical.")
        return (math.log10(value) - log_v1) / denom

    def to_dict(self) -> dict[str, Any]:
        return {
            "pixel1": list(self.pixel1),
            "value1": self.value1,
            "pixel2": list(self.pixel2),
            "value2": self.value2,
            "scale": self.scale.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AxisCalibration":
        return cls(
            pixel1=tuple(data["pixel1"]),
            value1=float(data["value1"]),
            pixel2=tuple(data["pixel2"]),
            value2=float(data["value2"]),
            scale=AxisScale(data.get("scale", AxisScale.LINEAR.value)),
        )


@dataclass(frozen=True)
class PlotCalibration:
    """Full 2D plot calibration."""

    x_axis: AxisCalibration
    y_axis: AxisCalibration

    def pixel_to_data(self, pixel: tuple[float, float]) -> tuple[float, float]:
        """Convert one image-space point to graph data coordinates."""

        return (
            self.x_axis.pixel_to_value(pixel),
            self.y_axis.pixel_to_value(pixel),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "x_axis": self.x_axis.to_dict(),
            "y_axis": self.y_axis.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlotCalibration":
        return cls(
            x_axis=AxisCalibration.from_dict(data["x_axis"]),
            y_axis=AxisCalibration.from_dict(data["y_axis"]),
        )
