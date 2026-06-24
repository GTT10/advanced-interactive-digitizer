from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aidigitizer.calibration import PlotCalibration


@dataclass
class DigitizedPoint:
    """One point in both image and optional calibrated data coordinates."""

    image_x: float
    image_y: float
    data_x: float | None = None
    data_y: float | None = None
    note: str = ""

    @property
    def image_pixel(self) -> tuple[float, float]:
        return (self.image_x, self.image_y)

    def update_data_coordinates(self, calibration: PlotCalibration | None) -> None:
        if calibration is None:
            self.data_x = None
            self.data_y = None
            return
        self.data_x, self.data_y = calibration.pixel_to_data(self.image_pixel)

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_x": self.image_x,
            "image_y": self.image_y,
            "data_x": self.data_x,
            "data_y": self.data_y,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DigitizedPoint":
        return cls(
            image_x=float(data["image_x"]),
            image_y=float(data["image_y"]),
            data_x=None if data.get("data_x") is None else float(data["data_x"]),
            data_y=None if data.get("data_y") is None else float(data["data_y"]),
            note=str(data.get("note", "")),
        )


@dataclass
class DataSeries:
    """A named data series extracted from one plot."""

    label: str
    points: list[DigitizedPoint] = field(default_factory=list)
    style: dict[str, Any] = field(default_factory=dict)

    def add_point(
        self,
        image_x: float,
        image_y: float,
        calibration: PlotCalibration | None = None,
    ) -> DigitizedPoint:
        point = DigitizedPoint(image_x=image_x, image_y=image_y)
        point.update_data_coordinates(calibration)
        self.points.append(point)
        return point

    def update_data_coordinates(self, calibration: PlotCalibration | None) -> None:
        for point in self.points:
            point.update_data_coordinates(calibration)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "points": [point.to_dict() for point in self.points],
            "style": self.style,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DataSeries":
        return cls(
            label=str(data["label"]),
            points=[DigitizedPoint.from_dict(item) for item in data.get("points", [])],
            style=dict(data.get("style", {})),
        )


@dataclass
class DigitizerProject:
    """Serializable project state for one digitizing session."""

    image_path: str = ""
    calibration: PlotCalibration | None = None
    series: list[DataSeries] = field(default_factory=list)

    def get_or_create_series(self, label: str) -> DataSeries:
        for item in self.series:
            if item.label == label:
                return item
        item = DataSeries(label=label)
        self.series.append(item)
        return item

    def update_data_coordinates(self) -> None:
        for item in self.series:
            item.update_data_coordinates(self.calibration)

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_path": self.image_path,
            "calibration": None if self.calibration is None else self.calibration.to_dict(),
            "series": [item.to_dict() for item in self.series],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DigitizerProject":
        calibration_data = data.get("calibration")
        project = cls(
            image_path=str(data.get("image_path", "")),
            calibration=None
            if calibration_data is None
            else PlotCalibration.from_dict(calibration_data),
            series=[DataSeries.from_dict(item) for item in data.get("series", [])],
        )
        project.update_data_coordinates()
        return project
