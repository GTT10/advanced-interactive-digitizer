from __future__ import annotations

import cv2
import numpy as np
import pytest

from aidigitizer.axis_detection import detect_axes


def make_plot_image(*, include_frame: bool = False, include_grid: bool = False) -> np.ndarray:
    image = np.full((500, 600, 3), 255, dtype=np.uint8)

    if include_grid:
        for x in range(160, 521, 90):
            cv2.line(image, (x, 80), (x, 420), (220, 220, 220), 1)
        for y in range(140, 421, 70):
            cv2.line(image, (80, y), (520, y), (220, 220, 220), 1)

    cv2.line(image, (80, 420), (520, 420), (0, 0, 0), 2)
    cv2.line(image, (80, 420), (80, 80), (0, 0, 0), 2)

    if include_frame:
        cv2.line(image, (80, 80), (520, 80), (0, 0, 0), 1)
        cv2.line(image, (520, 420), (520, 80), (0, 0, 0), 1)

    return image


def test_detect_axes_from_clean_plot() -> None:
    result = detect_axes(make_plot_image())

    assert result.is_complete
    assert result.confidence > 0.6
    assert result.x_axis is not None
    assert result.y_axis is not None
    assert (result.x_axis.y1 + result.x_axis.y2) / 2 == pytest.approx(420, abs=5)
    assert (result.y_axis.x1 + result.y_axis.x2) / 2 == pytest.approx(80, abs=5)


def test_detect_axes_prefers_left_bottom_axes_over_plot_frame() -> None:
    result = detect_axes(make_plot_image(include_frame=True, include_grid=True))

    assert result.is_complete
    assert result.x_axis is not None
    assert result.y_axis is not None
    assert (result.x_axis.y1 + result.x_axis.y2) / 2 == pytest.approx(420, abs=6)
    assert (result.y_axis.x1 + result.y_axis.x2) / 2 == pytest.approx(80, abs=6)


def test_detect_axes_returns_incomplete_result_when_no_lines_exist() -> None:
    image = np.full((400, 400, 3), 255, dtype=np.uint8)

    result = detect_axes(image)

    assert not result.is_complete
    assert result.confidence == 0.0
