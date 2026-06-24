from __future__ import annotations

from typing import Optional

import cv2
import numpy as np


class AdvancedDigitizerCore:
    """Image-processing core for symbol-assisted plot digitizing."""

    def __init__(self) -> None:
        self.image: np.ndarray | None = None
        self.gray_image: np.ndarray | None = None
        self.templates: dict[str, dict[str, object]] = {}

    def load_image(self, image_path: str) -> None:
        image = cv2.imread(image_path)
        if image is None:
            raise ValueError(f"Failed to load image: {image_path}")
        self.image = image
        self.gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    def _require_gray(self) -> np.ndarray:
        if self.gray_image is None:
            raise RuntimeError("No image has been loaded.")
        return self.gray_image

    def learn_from_legend(self, label: str, bbox: tuple[int, int, int, int]) -> bool:
        """Learn a plot symbol from a legend bounding box.

        Parameters
        ----------
        label:
            Series label to associate with the template.
        bbox:
            Bounding box as ``(x, y, width, height)`` in image coordinates.
        """

        gray = self._require_gray()
        x, y, w, h = bbox
        if w <= 0 or h <= 0:
            raise ValueError("Legend bounding box width and height must be positive.")

        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(gray.shape[1], x + w)
        y1 = min(gray.shape[0], y + h)
        template = gray[y0:y1, x0:x1]
        if template.size == 0:
            raise ValueError("Legend bounding box is outside the image.")

        self.templates[label] = {
            "img": template.copy(),
            "bbox": (x0, y0, x1 - x0, y1 - y0),
        }
        return True

    def refine_point(
        self,
        label: str,
        rough_x: int,
        rough_y: int,
        search_window: int = 50,
    ) -> Optional[tuple[int, int]]:
        """Refine a rough click using local template matching and centroiding."""

        gray = self._require_gray()
        if label not in self.templates:
            return (rough_x, rough_y)

        template = self.templates[label]["img"]
        if not isinstance(template, np.ndarray):
            return (rough_x, rough_y)

        tw, th = template.shape[::-1]
        x_start = max(0, rough_x - search_window)
        y_start = max(0, rough_y - search_window)
        x_end = min(gray.shape[1], rough_x + search_window)
        y_end = min(gray.shape[0], rough_y + search_window)
        roi = gray[y_start:y_end, x_start:x_end]

        if roi.shape[0] < th or roi.shape[1] < tw:
            return (rough_x, rough_y)

        result = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
        _, _, _, max_loc = cv2.minMaxLoc(result)
        match_x, match_y = max_loc

        matched_roi = roi[match_y : match_y + th, match_x : match_x + tw]
        _, thresh = cv2.threshold(
            matched_roi,
            0,
            255,
            cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
        )
        moments = cv2.moments(thresh)

        if moments["m00"] != 0:
            cx = moments["m10"] / moments["m00"]
            cy = moments["m01"] / moments["m00"]
            return (int(x_start + match_x + cx), int(y_start + match_y + cy))

        return (x_start + match_x + tw // 2, y_start + match_y + th // 2)

    def detect_all_instances(self, label: str, threshold: float = 0.7) -> list[tuple[int, int]]:
        """Detect all likely instances of a learned template."""

        gray = self._require_gray()
        if label not in self.templates:
            return []

        template = self.templates[label]["img"]
        if not isinstance(template, np.ndarray):
            return []

        tw, th = template.shape[::-1]
        if tw < 2 or th < 2:
            return []

        small_gray = cv2.resize(gray, (0, 0), fx=0.5, fy=0.5)
        small_template = cv2.resize(template, (0, 0), fx=0.5, fy=0.5)
        if small_template.shape[0] < 1 or small_template.shape[1] < 1:
            return []

        result = cv2.matchTemplate(small_gray, small_template, cv2.TM_CCOEFF_NORMED)
        raw_locations = list(zip(*np.where(result >= threshold)[::-1]))
        if not raw_locations:
            return []

        raw_locations.sort(key=lambda pt: result[pt[1], pt[0]], reverse=True)
        points: list[tuple[int, int]] = []
        min_dx = max(2, tw // 2)
        min_dy = max(2, th // 2)

        for pt in raw_locations:
            orig_x = int(pt[0] * 2 + tw // 2)
            orig_y = int(pt[1] * 2 + th // 2)
            if all(abs(px - orig_x) >= min_dx or abs(py - orig_y) >= min_dy for px, py in points):
                points.append((orig_x, orig_y))

        return points
