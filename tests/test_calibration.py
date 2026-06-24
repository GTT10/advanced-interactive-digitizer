from __future__ import annotations

import pytest

from aidigitizer.calibration import AxisCalibration, AxisScale, PlotCalibration


def test_linear_axis_calibration_horizontal_axis() -> None:
    axis = AxisCalibration(
        pixel1=(100, 500),
        value1=0.0,
        pixel2=(500, 500),
        value2=10.0,
    )

    assert axis.pixel_to_value((300, 500)) == pytest.approx(5.0)


def test_linear_axis_calibration_vertical_axis() -> None:
    axis = AxisCalibration(
        pixel1=(120, 650),
        value1=0.0,
        pixel2=(120, 150),
        value2=100.0,
    )

    assert axis.pixel_to_value((120, 400)) == pytest.approx(50.0)


def test_log_axis_calibration() -> None:
    axis = AxisCalibration(
        pixel1=(100, 500),
        value1=1.0,
        pixel2=(500, 500),
        value2=100.0,
        scale=AxisScale.LOG10,
    )

    assert axis.pixel_to_value((300, 500)) == pytest.approx(10.0)


def test_plot_calibration_converts_xy() -> None:
    calibration = PlotCalibration(
        x_axis=AxisCalibration((100, 500), 0.0, (500, 500), 10.0),
        y_axis=AxisCalibration((100, 500), 0.0, (100, 100), 20.0),
    )

    assert calibration.pixel_to_data((300, 300)) == pytest.approx((5.0, 10.0))


def test_log_scale_rejects_non_positive_values() -> None:
    with pytest.raises(ValueError):
        AxisCalibration((0, 0), 0.0, (1, 0), 10.0, AxisScale.LOG10)
