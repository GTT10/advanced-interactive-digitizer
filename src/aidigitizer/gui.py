from __future__ import annotations

import sys

import cv2
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from aidigitizer.calibration import AxisCalibration, AxisScale, PlotCalibration
from aidigitizer.core import AdvancedDigitizerCore
from aidigitizer.models import DataSeries, DigitizerProject
from aidigitizer.project import load_project, save_project, write_csv


class DigitizerUI(QMainWindow):
    """PyQt GUI for calibrated interactive plot digitizing."""

    def __init__(self) -> None:
        super().__init__()
        self.core = AdvancedDigitizerCore()
        self.project = DigitizerProject()
        self.current_label: str | None = None
        self.mode = "view"
        self.selection_rect: QRect | None = None
        self.start_point: QPoint | None = None
        self.pending_axis: str | None = None
        self.pending_axis_values: tuple[float, float, AxisScale] | None = None
        self.pending_axis_pixels: list[tuple[float, float]] = []
        self.x_axis: AxisCalibration | None = None
        self.y_axis: AxisCalibration | None = None
        self.display_image: QPixmap | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        self.setWindowTitle("Advanced Interactive Digitizer")
        self.setGeometry(100, 100, 1280, 820)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("background-color: #222; border: 1px solid #555;")
        self.image_label.setMouseTracking(True)
        self.image_label.mousePressEvent = self._handle_image_mouse_press
        self.image_label.mouseMoveEvent = self._handle_image_mouse_move
        self.image_label.mouseReleaseEvent = self._handle_image_mouse_release
        layout.addWidget(self.image_label, 4)

        panel = QVBoxLayout()
        self.status_label = QLabel("Load an image to start.")
        self.status_label.setWordWrap(True)
        panel.addWidget(self.status_label)

        self._add_button(panel, "画像を読み込む", self.load_image)
        self._add_button(panel, "プロジェクトを開く", self.open_project)
        self._add_button(panel, "プロジェクトを保存", self.save_current_project)

        self.label_list = QListWidget()
        self.label_list.itemClicked.connect(self.select_label)
        panel.addWidget(QLabel("系列:"))
        panel.addWidget(self.label_list)

        self._add_button(panel, "系列追加", self.add_series)
        self._add_button(panel, "X軸校正", lambda: self.start_axis_calibration("x"))
        self._add_button(panel, "Y軸校正", lambda: self.start_axis_calibration("y"))
        self._add_button(panel, "凡例テンプレート学習", self.start_learning)
        self._add_button(panel, "点追加モード", self.start_digitizing)
        self._add_button(panel, "モード終了", self.stop_interaction)
        self._add_button(panel, "最後の点を削除", self.delete_last_point)
        self._add_button(panel, "自動一括検出", self.auto_detect)
        self._add_button(panel, "CSVエクスポート", self.export_data)

        panel.addStretch()
        layout.addLayout(panel, 1)

    def _add_button(self, panel: QVBoxLayout, text: str, callback) -> None:
        button = QPushButton(text)
        button.clicked.connect(callback)
        panel.addWidget(button)

    def load_image(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "画像を開く",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)",
        )
        if not file_path:
            return
        self._load_image_path(file_path)
        self.project = DigitizerProject(image_path=file_path)
        self.current_label = None
        self.x_axis = None
        self.y_axis = None
        self.label_list.clear()
        self.update_display()

    def _load_image_path(self, file_path: str) -> None:
        self.core.load_image(file_path)
        self.project.image_path = file_path
        self.status_label.setText(f"Image: {file_path}")

    def open_project(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "プロジェクトを開く", "", "AID JSON (*.aid.json *.json)")
        if not file_path:
            return
        try:
            project = load_project(file_path)
            if project.image_path:
                self._load_image_path(project.image_path)
            self.project = project
            self.x_axis = None if project.calibration is None else project.calibration.x_axis
            self.y_axis = None if project.calibration is None else project.calibration.y_axis
            self.refresh_series_list()
            self.update_display()
        except Exception as exc:  # pragma: no cover - GUI feedback path
            QMessageBox.critical(self, "読み込み失敗", str(exc))

    def save_current_project(self) -> None:
        if not self.project.image_path:
            QMessageBox.warning(self, "警告", "先に画像を読み込んでください。")
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "プロジェクト保存", "", "AID JSON (*.aid.json)")
        if not file_path:
            return
        if not file_path.endswith(".aid.json"):
            file_path += ".aid.json"
        self.project.update_data_coordinates()
        save_project(self.project, file_path)
        self.status_label.setText(f"Saved project: {file_path}")

    def refresh_series_list(self) -> None:
        self.label_list.clear()
        for series in self.project.series:
            self.label_list.addItem(series.label)
        self.current_label = self.project.series[0].label if self.project.series else None

    def current_series(self) -> DataSeries | None:
        if self.current_label is None:
            return None
        return self.project.get_or_create_series(self.current_label)

    def add_series(self) -> None:
        label, ok = QInputDialog.getText(self, "系列追加", "系列名:")
        if not ok or not label.strip():
            return
        label = label.strip()
        self.project.get_or_create_series(label)
        self.current_label = label
        self.refresh_series_list()
        matching = self.label_list.findItems(label, Qt.MatchFlag.MatchExactly)
        if matching:
            self.label_list.setCurrentItem(matching[0])

    def select_label(self, item) -> None:
        self.current_label = item.text()
        self.update_display()

    def start_axis_calibration(self, axis: str) -> None:
        if self.core.image is None:
            QMessageBox.warning(self, "警告", "先に画像を読み込んでください。")
            return
        v1, ok = QInputDialog.getDouble(self, f"{axis.upper()}軸校正", "1点目の実値:", decimals=12)
        if not ok:
            return
        v2, ok = QInputDialog.getDouble(self, f"{axis.upper()}軸校正", "2点目の実値:", decimals=12)
        if not ok:
            return
        scale_text, ok = QInputDialog.getItem(
            self,
            f"{axis.upper()}軸スケール",
            "スケール:",
            [AxisScale.LINEAR.value, AxisScale.LOG10.value],
            0,
            False,
        )
        if not ok:
            return
        self.mode = "axis"
        self.pending_axis = axis
        self.pending_axis_values = (v1, v2, AxisScale(scale_text))
        self.pending_axis_pixels = []
        self.status_label.setText(f"{axis.upper()}軸: 1点目、2点目の順に画像上をクリック。")

    def start_learning(self) -> None:
        if self.core.image is None:
            QMessageBox.warning(self, "警告", "先に画像を読み込んでください。")
            return
        if self.current_label is None:
            self.add_series()
            if self.current_label is None:
                return
        self.mode = "learn"
        self.selection_rect = None
        self.start_point = None
        self.status_label.setText("凡例内のシンボルをドラッグで囲む。")

    def start_digitizing(self) -> None:
        if self.core.image is None:
            QMessageBox.warning(self, "警告", "先に画像を読み込んでください。")
            return
        if self.current_label is None:
            self.add_series()
            if self.current_label is None:
                return
        self.mode = "digitize"
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.status_label.setText("点追加モード: プロット点をクリック。")

    def stop_interaction(self) -> None:
        self.mode = "view"
        self.pending_axis = None
        self.pending_axis_values = None
        self.pending_axis_pixels = []
        self.selection_rect = None
        self.start_point = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.status_label.setText("View mode.")
        self.update_display()

    def delete_last_point(self) -> None:
        series = self.current_series()
        if series is None or not series.points:
            return
        series.points.pop()
        self.update_display()

    def auto_detect(self) -> None:
        series = self.current_series()
        if series is None:
            return
        detected = self.core.detect_all_instances(series.label)
        series.points.clear()
        for x, y in detected:
            series.add_point(x, y, self.project.calibration)
        self.update_display()
        QMessageBox.information(self, "完了", f"{len(detected)} 個の候補点を検出しました。")

    def export_data(self) -> None:
        if not self.project.series:
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "CSV保存", "", "CSV Files (*.csv)")
        if not file_path:
            return
        if not file_path.endswith(".csv"):
            file_path += ".csv"
        self.project.update_data_coordinates()
        write_csv(self.project, file_path)
        QMessageBox.information(self, "完了", "CSVをエクスポートしました。")

    def update_display(self) -> None:
        if self.core.image is None:
            return
        image = self.core.image.copy()

        for series in self.project.series:
            active = series.label == self.current_label
            color = (0, 0, 255) if active else (255, 0, 0)
            for point in series.points:
                x = int(round(point.image_x))
                y = int(round(point.image_y))
                cv2.circle(image, (x, y), 5, color, -1)
                cv2.putText(
                    image,
                    series.label,
                    (x + 7, y - 7),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (255, 255, 255),
                    1,
                )

        if self.selection_rect:
            r = self.selection_rect
            cv2.rectangle(image, (r.x(), r.y()), (r.x() + r.width(), r.y() + r.height()), (0, 255, 0), 2)

        for px, py in self.pending_axis_pixels:
            cv2.circle(image, (int(px), int(py)), 6, (0, 255, 255), -1)

        height, width, _ = image.shape
        q_image = QImage(image.data, width, height, 3 * width, QImage.Format.Format_BGR888)
        self.display_image = QPixmap.fromImage(q_image)
        scaled = self.display_image.scaled(
            self.image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self.update_display()
        super().resizeEvent(event)

    def _handle_image_mouse_press(self, event) -> None:
        if self.core.image is None:
            return
        image_pos = self.map_to_img_coords(event.position().toPoint())
        pixel = (float(image_pos.x()), float(image_pos.y()))

        if self.mode == "axis":
            self.pending_axis_pixels.append(pixel)
            self.update_display()
            if len(self.pending_axis_pixels) == 2:
                self._finish_axis_calibration()
            return

        if self.mode == "learn":
            self.start_point = image_pos
            self.selection_rect = QRect(image_pos, image_pos)
            self.update_display()
            return

        if self.mode == "digitize":
            series = self.current_series()
            if series is None:
                return
            refined = self.core.refine_point(series.label, image_pos.x(), image_pos.y())
            x, y = refined if refined is not None else (image_pos.x(), image_pos.y())
            series.add_point(float(x), float(y), self.project.calibration)
            self.update_display()

    def _handle_image_mouse_move(self, event) -> None:
        if self.mode != "learn" or self.start_point is None or self.core.image is None:
            return
        image_pos = self.map_to_img_coords(event.position().toPoint())
        self.selection_rect = QRect(self.start_point, image_pos).normalized()
        self.update_display()

    def _handle_image_mouse_release(self, event) -> None:
        if self.mode != "learn" or self.selection_rect is None or self.current_label is None:
            return
        r = self.selection_rect.normalized()
        try:
            self.core.learn_from_legend(self.current_label, (r.x(), r.y(), r.width(), r.height()))
            QMessageBox.information(self, "完了", f"'{self.current_label}' のテンプレートを学習しました。")
        except Exception as exc:  # pragma: no cover - GUI feedback path
            QMessageBox.critical(self, "学習失敗", str(exc))
        finally:
            self.selection_rect = None
            self.start_point = None
            self.mode = "view"
            self.update_display()

    def _finish_axis_calibration(self) -> None:
        if self.pending_axis is None or self.pending_axis_values is None:
            return
        v1, v2, scale = self.pending_axis_values
        p1, p2 = self.pending_axis_pixels
        try:
            axis_calibration = AxisCalibration(p1, v1, p2, v2, scale)
            if self.pending_axis == "x":
                self.x_axis = axis_calibration
            else:
                self.y_axis = axis_calibration
            if self.x_axis is not None and self.y_axis is not None:
                self.project.calibration = PlotCalibration(self.x_axis, self.y_axis)
                self.project.update_data_coordinates()
                self.status_label.setText("X/Y軸校正完了。点は実座標としてCSV出力されます。")
            else:
                self.status_label.setText(f"{self.pending_axis.upper()}軸校正完了。もう片方の軸も設定してください。")
        except Exception as exc:  # pragma: no cover - GUI feedback path
            QMessageBox.critical(self, "校正失敗", str(exc))
        finally:
            self.mode = "view"
            self.pending_axis = None
            self.pending_axis_values = None
            self.pending_axis_pixels = []
            self.update_display()

    def map_to_img_coords(self, pos: QPoint) -> QPoint:
        pixmap = self.image_label.pixmap()
        if pixmap is None or self.core.image is None:
            return pos

        label_w = self.image_label.width()
        label_h = self.image_label.height()
        pix_w = pixmap.width()
        pix_h = pixmap.height()
        if pix_w == 0 or pix_h == 0:
            return pos

        offset_x = (label_w - pix_w) / 2
        offset_y = (label_h - pix_h) / 2
        image_h, image_w = self.core.image.shape[:2]
        real_x = int((pos.x() - offset_x) * image_w / pix_w)
        real_y = int((pos.y() - offset_y) * image_h / pix_h)
        return QPoint(max(0, min(image_w - 1, real_x)), max(0, min(image_h - 1, real_y)))


def main() -> None:
    app = QApplication(sys.argv)
    window = DigitizerUI()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
