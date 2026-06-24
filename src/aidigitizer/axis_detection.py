from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import cv2
import numpy as np


@dataclass(frozen=True)
class LineSegment:
    """One detected line segment in image coordinates."""

    x1: int
    y1: int
    x2: int
    y2: int
    score: float = 0.0

    @property
    def length(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)

    @property
    def midpoint(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    @property
    def x_min(self) -> int:
        return min(self.x1, self.x2)

    @property
    def x_max(self) -> int:
        return max(self.x1, self.x2)

    @property
    def y_min(self) -> int:
        return min(self.y1, self.y2)

    @property
    def y_max(self) -> int:
        return max(self.y1, self.y2)

    def as_points(self) -> tuple[tuple[int, int], tuple[int, int]]:
        return (self.x1, self.y1), (self.x2, self.y2)

    def x_calibration_points(self) -> tuple[tuple[float, float], tuple[float, float]]:
        """Return left-to-right calibration points for a horizontal axis."""

        y = (self.y1 + self.y2) / 2.0
        return (float(self.x_min), y), (float(self.x_max), y)

    def y_calibration_points(self) -> tuple[tuple[float, float], tuple[float, float]]:
        """Return bottom-to-top calibration points for a vertical axis."""

        x = (self.x1 + self.x2) / 2.0
        return (x, float(self.y_max)), (x, float(self.y_min))


@dataclass(frozen=True)
class AxisDetectionResult:
    """Detected x/y axis pair and confidence score."""

    x_axis: LineSegment | None
    y_axis: LineSegment | None
    confidence: float
    horizontal_candidates: tuple[LineSegment, ...] = ()
    vertical_candidates: tuple[LineSegment, ...] = ()

    @property
    def is_complete(self) -> bool:
        return self.x_axis is not None and self.y_axis is not None


def detect_axes(
    image: np.ndarray,
    *,
    canny_low: int = 50,
    canny_high: int = 150,
    hough_threshold: int = 60,
    max_angle_deviation_deg: float = 4.0,
) -> AxisDetectionResult:
    """Detect likely x/y axes from a plot image.

    The detector is deliberately conservative. It tries to find long horizontal
    and vertical line segments, then scores pairs that intersect near the lower
    left of the image. It is meant to suggest calibration points to the user,
    not to silently decide the truth on behalf of science. We have spreadsheets
    for that kind of quiet sabotage.
    """

    if image.size == 0:
        return AxisDetectionResult(None, None, 0.0)

    gray = _to_gray(image)
    height, width = gray.shape[:2]
    min_len = max(30, int(min(width, height) * 0.18))

    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blurred, canny_low, canny_high)

    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=hough_threshold,
        minLineLength=min_len,
        maxLineGap=max(8, int(min(width, height) * 0.02)),
    )

    if lines is None:
        return AxisDetectionResult(None, None, 0.0)

    horizontal: list[LineSegment] = []
    vertical: list[LineSegment] = []

    for raw in lines[:, 0, :]:
        x1, y1, x2, y2 = (int(v) for v in raw)
        segment = LineSegment(x1, y1, x2, y2)
        if segment.length < min_len:
            continue
        angle = abs(math.degrees(math.atan2(y2 - y1, x2 - x1)))
        angle = min(angle, 180.0 - angle)
        if angle <= max_angle_deviation_deg:
            horizontal.append(segment)
        elif abs(angle - 90.0) <= max_angle_deviation_deg:
            vertical.append(segment)

    horizontal = _merge_horizontal_segments(horizontal, width, height)
    vertical = _merge_vertical_segments(vertical, width, height)

    if not horizontal or not vertical:
        return AxisDetectionResult(
            None,
            None,
            0.0,
            tuple(_rank_horizontal(horizontal, width, height)),
            tuple(_rank_vertical(vertical, width, height)),
        )

    best_pair: tuple[LineSegment, LineSegment] | None = None
    best_score = -math.inf

    for h_seg in _rank_horizontal(horizontal, width, height)[:12]:
        for v_seg in _rank_vertical(vertical, width, height)[:12]:
            score = _score_axis_pair(h_seg, v_seg, width, height)
            if score > best_score:
                best_score = score
                best_pair = (h_seg, v_seg)

    if best_pair is None:
        return AxisDetectionResult(None, None, 0.0)

    x_axis, y_axis = best_pair
    confidence = max(0.0, min(1.0, best_score / 6.0))
    return AxisDetectionResult(
        x_axis=x_axis,
        y_axis=y_axis,
        confidence=confidence,
        horizontal_candidates=tuple(_rank_horizontal(horizontal, width, height)[:8]),
        vertical_candidates=tuple(_rank_vertical(vertical, width, height)[:8]),
    )


def _to_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    if image.ndim == 3 and image.shape[2] == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if image.ndim == 3 and image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    raise ValueError(f"Unsupported image shape: {image.shape}")


def _merge_horizontal_segments(
    segments: Iterable[LineSegment],
    width: int,
    height: int,
) -> list[LineSegment]:
    del height
    buckets: dict[int, list[LineSegment]] = {}
    for seg in segments:
        y = int(round((seg.y1 + seg.y2) / 2.0))
        key = round(y / 4)
        buckets.setdefault(key, []).append(seg)

    merged: list[LineSegment] = []
    gap_threshold = max(15, int(width * 0.03))

    for group in buckets.values():
        sorted_group = sorted(group, key=lambda seg: seg.x_min)
        current_group: list[LineSegment] = []
        for seg in sorted_group:
            if not current_group:
                current_group = [seg]
                continue
            current_x_max = max(item.x_max for item in current_group)
            if seg.x_min - current_x_max <= gap_threshold:
                current_group.append(seg)
            else:
                merged.append(_collapse_horizontal_group(current_group))
                current_group = [seg]
        if current_group:
            merged.append(_collapse_horizontal_group(current_group))

    return merged


def _merge_vertical_segments(
    segments: Iterable[LineSegment],
    width: int,
    height: int,
) -> list[LineSegment]:
    del width
    buckets: dict[int, list[LineSegment]] = {}
    for seg in segments:
        x = int(round((seg.x1 + seg.x2) / 2.0))
        key = round(x / 4)
        buckets.setdefault(key, []).append(seg)

    merged: list[LineSegment] = []
    gap_threshold = max(15, int(height * 0.03))

    for group in buckets.values():
        sorted_group = sorted(group, key=lambda seg: seg.y_min)
        current_group: list[LineSegment] = []
        for seg in sorted_group:
            if not current_group:
                current_group = [seg]
                continue
            current_y_max = max(item.y_max for item in current_group)
            if seg.y_min - current_y_max <= gap_threshold:
                current_group.append(seg)
            else:
                merged.append(_collapse_vertical_group(current_group))
                current_group = [seg]
        if current_group:
            merged.append(_collapse_vertical_group(current_group))

    return merged


def _collapse_horizontal_group(group: list[LineSegment]) -> LineSegment:
    y = int(round(sum((seg.y1 + seg.y2) / 2.0 for seg in group) / len(group)))
    return LineSegment(
        x1=min(seg.x_min for seg in group),
        y1=y,
        x2=max(seg.x_max for seg in group),
        y2=y,
    )


def _collapse_vertical_group(group: list[LineSegment]) -> LineSegment:
    x = int(round(sum((seg.x1 + seg.x2) / 2.0 for seg in group) / len(group)))
    return LineSegment(
        x1=x,
        y1=min(seg.y_min for seg in group),
        x2=x,
        y2=max(seg.y_max for seg in group),
    )


def _rank_horizontal(segments: list[LineSegment], width: int, height: int) -> list[LineSegment]:
    ranked: list[LineSegment] = []
    for seg in segments:
        _, y = seg.midpoint
        length_score = seg.length / max(1, width)
        bottom_score = y / max(1, height)
        margin_penalty = 0.25 if y < height * 0.08 or y > height * 0.98 else 0.0
        score = 2.0 * length_score + 1.3 * bottom_score - margin_penalty
        ranked.append(LineSegment(seg.x1, seg.y1, seg.x2, seg.y2, score))
    return sorted(ranked, key=lambda item: item.score, reverse=True)


def _rank_vertical(segments: list[LineSegment], width: int, height: int) -> list[LineSegment]:
    ranked: list[LineSegment] = []
    for seg in segments:
        x, _ = seg.midpoint
        length_score = seg.length / max(1, height)
        left_score = 1.0 - x / max(1, width)
        margin_penalty = 0.25 if x < width * 0.02 or x > width * 0.92 else 0.0
        score = 2.0 * length_score + 1.3 * left_score - margin_penalty
        ranked.append(LineSegment(seg.x1, seg.y1, seg.x2, seg.y2, score))
    return sorted(ranked, key=lambda item: item.score, reverse=True)


def _score_axis_pair(horizontal: LineSegment, vertical: LineSegment, width: int, height: int) -> float:
    h_y = (horizontal.y1 + horizontal.y2) / 2.0
    v_x = (vertical.x1 + vertical.x2) / 2.0

    horizontal_contains_intersection = horizontal.x_min - 8 <= v_x <= horizontal.x_max + 8
    vertical_contains_intersection = vertical.y_min - 8 <= h_y <= vertical.y_max + 8

    intersection_score = 1.5 if horizontal_contains_intersection and vertical_contains_intersection else -1.0
    lower_left_score = int(v_x <= width * 0.45) + int(h_y >= height * 0.45)
    span_score = min(horizontal.length / max(1, width), 1.0) + min(vertical.length / max(1, height), 1.0)

    # A useful x-axis should mostly extend to the right of the y-axis, and a
    # useful y-axis should mostly extend above the x-axis. This avoids choosing
    # random grid or legend frame lines when several long lines are present.
    extension_score = 0.0
    if horizontal.x_max - v_x > width * 0.30:
        extension_score += 0.6
    if h_y - vertical.y_min > height * 0.30:
        extension_score += 0.6

    return horizontal.score + vertical.score + intersection_score + lower_left_score + span_score + extension_score
