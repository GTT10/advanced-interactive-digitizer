from __future__ import annotations

import io

from aidigitizer.calibration import AxisCalibration, PlotCalibration
from aidigitizer.models import DigitizerProject
from aidigitizer.project import load_project, save_project, write_csv


def build_project() -> DigitizerProject:
    calibration = PlotCalibration(
        x_axis=AxisCalibration((0, 10), 0.0, (10, 10), 1.0),
        y_axis=AxisCalibration((0, 10), 0.0, (0, 0), 100.0),
    )
    project = DigitizerProject(image_path="figure.png", calibration=calibration)
    series = project.get_or_create_series("AMN")
    series.add_point(5, 5, calibration)
    return project


def test_project_roundtrip(tmp_path) -> None:
    path = tmp_path / "figure.aid.json"
    project = build_project()

    save_project(project, path)
    loaded = load_project(path)

    assert loaded.image_path == "figure.png"
    assert loaded.series[0].label == "AMN"
    assert loaded.series[0].points[0].data_x == 0.5
    assert loaded.series[0].points[0].data_y == 50.0


def test_write_csv_includes_data_and_image_coordinates() -> None:
    project = build_project()
    fp = io.StringIO()

    write_csv(project, fp)

    csv_text = fp.getvalue()
    assert "label,data_x,data_y,image_x,image_y,note" in csv_text
    assert "AMN,0.5,50.0,5,5," in csv_text
