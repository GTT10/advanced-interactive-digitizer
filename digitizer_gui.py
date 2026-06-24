import sys
import cv2
import numpy as np
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QFileDialog, QListWidget, QMessageBox, QInputDialog)
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QCursor
from PyQt6.QtCore import Qt, QPoint, QRect
from digitizer_core import AdvancedDigitizerCore

class DigitizerUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.core = AdvancedDigitizerCore()
        self.initUI()
        
        self.image_path = None
        self.display_image = None
        self.mode = "VIEW" # VIEW, LEARN, DIGITIZE
        self.current_label = None
        self.points = {} # label -> list of (x, y)
        self.selection_rect = None
        self.start_point = None

    def initUI(self):
        self.setWindowTitle('Advanced Plot Digitizer')
        self.setGeometry(100, 100, 1200, 800)

        # メインレイアウト
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)

        # 左側：画像表示エリア
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("background-color: #222; border: 1px solid #555;")
        self.image_label.setMouseTracking(True)
        layout.addWidget(self.image_label, 4)

        # 右側：コントロールパネル
        panel = QVBoxLayout()
        
        btn_load = QPushButton("画像を読み込む")
        btn_load.clicked.connect(self.load_image)
        panel.addWidget(btn_load)

        self.label_list = QListWidget()
        self.label_list.itemClicked.connect(self.select_label)
        panel.addWidget(QLabel("凡例/カテゴリ:"))
        panel.addWidget(self.label_list)

        btn_add_label = QPushButton("カテゴリ追加 & 凡例学習")
        btn_add_label.clicked.connect(self.start_learning)
        panel.addWidget(btn_add_label)

        btn_digitize = QPushButton("プロット指定モード")
        btn_digitize.clicked.connect(self.start_digitizing)
        panel.addWidget(btn_digitize)

        btn_auto = QPushButton("自動一括検出")
        btn_auto.clicked.connect(self.auto_detect)
        panel.addWidget(btn_auto)

        btn_export = QPushButton("CSVエクスポート")
        btn_export.clicked.connect(self.export_data)
        panel.addWidget(btn_export)

        panel.addStretch()
        layout.addLayout(panel, 1)

    def load_image(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "画像を開く", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if file_path:
            self.image_path = file_path
            self.core.load_image(file_path)
            self.update_display()

    def update_display(self):
        if self.core.image is None:
            return

        img = self.core.image.copy()
        
        # 描画済みのポイントを表示
        for label, pts in self.points.items():
            color = QColor(Qt.GlobalColor.red) if label == self.current_label else QColor(Qt.GlobalColor.blue)
            for x, y in pts:
                cv2.circle(img, (x, y), 5, (0, 0, 255) if label == self.current_label else (255, 0, 0), -1)
                cv2.putText(img, label, (x+7, y-7), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        # 選択中の矩形を描画
        if self.selection_rect:
            r = self.selection_rect
            cv2.rectangle(img, (r.x(), r.y()), (r.x() + r.width(), r.y() + r.height()), (0, 255, 0), 2)

        # OpenCV(BGR) -> QImage(RGB)
        height, width, channel = img.shape
        bytesPerLine = 3 * width
        qImg = QImage(img.data, width, height, bytesPerLine, QImage.Format.Format_BGR888)
        self.display_image = QPixmap.fromImage(qImg)
        
        # スケーリングして表示
        scaled_pixmap = self.display_image.scaled(self.image_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.image_label.setPixmap(scaled_pixmap)

    def resizeEvent(self, event):
        self.update_display()
        super().resizeEvent(event)

    def mousePressEvent(self, event):
        if not self.image_path: return
        
        pos = self.image_label.mapFromParent(event.pos())
        if not self.image_label.rect().contains(pos): return

        # 表示座標から画像座標への変換
        img_pos = self.map_to_img_coords(pos)

        if self.mode == "LEARN":
            self.start_point = img_pos
            self.selection_rect = QRect(img_pos, img_pos)
        elif self.mode == "DIGITIZE":
            if self.current_label:
                # アルゴリズムによる補正
                refined = self.core.refine_point(self.current_label, img_pos.x(), img_pos.y())
                if refined:
                    self.points[self.current_label].append(refined)
                    self.update_display()

    def mouseMoveEvent(self, event):
        if self.mode == "LEARN" and self.start_point:
            pos = self.image_label.mapFromParent(event.pos())
            img_pos = self.map_to_img_coords(pos)
            self.selection_rect = QRect(self.start_point, img_pos).normalized()
            self.update_display()

    def mouseReleaseEvent(self, event):
        if self.mode == "LEARN" and self.start_point:
            label, ok = QInputDialog.getText(self, '学習', 'カテゴリ名を入力:')
            if ok and label:
                r = self.selection_rect
                self.core.learn_from_legend(label, (r.x(), r.y(), r.width(), r.height()))
                self.label_list.addItem(label)
                self.points[label] = []
                self.current_label = label
                QMessageBox.information(self, "完了", f"'{label}' の形状を学習しました。")
            
            self.start_point = None
            self.selection_rect = None
            self.mode = "VIEW"
            self.update_display()

    def map_to_img_coords(self, pos):
        # QLabel内での画像表示オフセットとスケーリングを考慮
        pixmap = self.image_label.pixmap()
        if not pixmap: return pos
        
        lbl_w, lbl_h = self.image_label.width(), self.image_label.height()
        pix_w, pix_h = pixmap.width(), pixmap.height()
        
        offset_x = (lbl_w - pix_w) / 2
        offset_y = (lbl_h - pix_h) / 2
        
        img_w, img_h = self.core.image.shape[1], self.core.image.shape[0]
        
        scale_x = img_w / pix_w
        scale_y = img_h / pix_h
        
        real_x = int((pos.x() - offset_x) * scale_x)
        real_y = int((pos.y() - offset_y) * scale_y)
        
        return QPoint(max(0, min(img_w-1, real_x)), max(0, min(img_h-1, real_y)))

    def start_learning(self):
        self.mode = "LEARN"
        QMessageBox.information(self, "手順", "凡例のシンボルをマウスで囲んでください。")

    def start_digitizing(self):
        if not self.current_label:
            QMessageBox.warning(self, "警告", "まずカテゴリを選択または作成してください。")
            return
        self.mode = "DIGITIZE"
        self.setCursor(Qt.CursorShape.CrossCursor)

    def select_label(self, item):
        self.current_label = item.text()
        self.update_display()

    def auto_detect(self):
        if not self.current_label: return
        pts = self.core.detect_all_instances(self.current_label)
        self.points[self.current_label] = pts
        self.update_display()
        QMessageBox.information(self, "完了", f"{len(pts)} 個のポイントを自動検出しました。")

    def export_data(self):
        if not self.points: return
        file_path, _ = QFileDialog.getSaveFileName(self, "CSV保存", "", "CSV Files (*.csv)")
        if file_path:
            with open(file_path, 'w') as f:
                f.write("label,x,y\n")
                for label, pts in self.points.items():
                    for x, y in pts:
                        f.write(f"{label},{x},{y}\n")
            QMessageBox.information(self, "完了", "データをエクスポートしました。")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = DigitizerUI()
    ex.show()
    sys.exit(app.exec())
