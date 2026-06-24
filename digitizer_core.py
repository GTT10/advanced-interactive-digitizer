import cv2
import numpy as np
from typing import List, Tuple, Dict, Optional

class AdvancedDigitizerCore:
    """
    高度なデジタイザコアアルゴリズム
    1. 凡例領域からのシンボル学習
    2. ユーザー指定座標周辺での精密形状マッチング
    3. ヒューマンフィードバックによる補正
    """
    def __init__(self):
        self.image = None
        self.gray_image = None
        self.templates = {}  # label -> {template_img, mask, keypoints, descriptors}
        self.sift = cv2.SIFT_create()
        self.matcher = cv2.BFMatcher()

    def load_image(self, image_path: str):
        self.image = cv2.imread(image_path)
        if self.image is None:
            raise ValueError("画像の読み込みに失敗しました。")
        self.gray_image = cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY)

    def learn_from_legend(self, label: str, bbox: Tuple[int, int, int, int]):
        """
        凡例のバウンディングボックス(x, y, w, h)からシンボルを学習する
        """
        x, y, w, h = bbox
        template = self.gray_image[y:y+h, x:x+w]
        
        # SIFT特徴量の抽出（幾何学的な不変性を高めるため）
        kp, des = self.sift.detectAndCompute(template, None)
        
        self.templates[label] = {
            'img': template,
            'kp': kp,
            'des': des,
            'bbox': bbox
        }
        return True

    def refine_point(self, label: str, rough_x: int, rough_y: int, search_window: int = 50) -> Optional[Tuple[int, int]]:
        """
        ユーザーが指定した大まかな位置をアルゴリズムで補正する
        """
        if label not in self.templates:
            return (rough_x, rough_y)

        template_info = self.templates[label]
        temp_img = template_info['img']
        tw, th = temp_img.shape[::-1]

        # 検索窓の設定
        x_start = max(0, rough_x - search_window)
        y_start = max(0, rough_y - search_window)
        x_end = min(self.gray_image.shape[1], rough_x + search_window)
        y_end = min(self.gray_image.shape[0], rough_y + search_window)
        
        roi = self.gray_image[y_start:y_end, x_start:x_end]
        
        if roi.shape[0] < th or roi.shape[1] < tw:
            return (rough_x, rough_y)

        # 1. テンプレートマッチングによる粗い位置特定
        res = cv2.matchTemplate(roi, temp_img, cv2.TM_CCOEFF_NORMED)
        _, _, _, max_loc = cv2.minMaxLoc(res)
        
        # 2. 重心による精密補正
        # マッチングした左上座標 (ROI内)
        match_x_in_roi = max_loc[0]
        match_y_in_roi = max_loc[1]
        
        # マッチングした領域を抽出
        matched_roi = roi[match_y_in_roi:match_y_in_roi+th, match_x_in_roi:match_x_in_roi+tw]
        
        # 二値化して重心を求める（背景が白、シンボルが色付きを想定）
        # グレースケールで暗い部分（シンボル）を抽出
        _, thresh = cv2.threshold(matched_roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        M = cv2.moments(thresh)
        
        if M["m00"] != 0:
            # ROI内での重心相対座標
            cx = M["m10"] / M["m00"]
            cy = M["m01"] / M["m00"]
            # 画像全体での絶対座標
            final_x = int(x_start + match_x_in_roi + cx)
            final_y = int(y_start + match_y_in_roi + cy)
            return (final_x, final_y)
        
        # 重心が取れない場合はテンプレートの中心を返す
        return (x_start + match_x_in_roi + tw//2, y_start + match_y_in_roi + th//2)

    def detect_all_instances(self, label: str, threshold: float = 0.7) -> List[Tuple[int, int]]:
        """
        学習したテンプレートに基づき、画像全体から同一形状を自動検出する
        """
        if label not in self.templates:
            return []
            
        temp_img = self.templates[label]['img']
        tw, th = temp_img.shape[::-1]
        
        # 高速化のため、マルチスケールではなく単一スケールだが、
        # マッチング前に二値化やエッジ強調を行うことで精度と速度を調整
        # 1/2に縮小して高速マッチング
        # ※縮小後テンプレートが 0px になる場合 (int(1 * 0.5) = 0) はクラッシュするため
        #   resize 前にサイズを確認して早期リターンする
        if int(temp_img.shape[0] * 0.5) < 1 or int(temp_img.shape[1] * 0.5) < 1:
            return []
        small_gray = cv2.resize(self.gray_image, (0,0), fx=0.5, fy=0.5)
        small_temp = cv2.resize(temp_img, (0,0), fx=0.5, fy=0.5)
        res = cv2.matchTemplate(small_gray, small_temp, cv2.TM_CCOEFF_NORMED)
        
        # 閾値以上の位置を抽出
        loc = np.where(res >= threshold)
        raw_points = list(zip(*loc[::-1]))
        
        if not raw_points:
            return []

        # 近接点のクラスタリング（Non-Maximum Suppression的な処理）
        points = []
        raw_points.sort(key=lambda x: res[x[1], x[0]], reverse=True)
        
        for pt in raw_points:
            # 座標を元に戻す (x*2, y*2)
            orig_x = pt[0] * 2 + tw // 2
            orig_y = pt[1] * 2 + th // 2
            
            is_close = False
            for p in points:
                if abs(p[0] - orig_x) < tw//2 and abs(p[1] - orig_y) < th//2:
                    is_close = True
                    break
            if not is_close:
                points.append((orig_x, orig_y))
        
        return points

if __name__ == "__main__":
    # 簡単なテスト
    core = AdvancedDigitizerCore()
    print("Core algorithm initialized.")
