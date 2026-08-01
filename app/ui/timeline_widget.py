"""
タイムラインウィジェット - シーン境界の視覚的表示と調整
"""
from typing import Optional, List
from dataclasses import dataclass

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QToolTip, QMenu, QDoubleSpinBox, QFormLayout,
    QWidgetAction, QMessageBox, QFrame,
)
from PySide6.QtCore import Qt, Signal, QRect, QPoint
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QMouseEvent, QFont, QPixmap,
)

from app.core.scene_detector import SceneDetectionSettings
from app.core.time_format import format_seconds
from app.ui.style_helpers import set_recommended_action


def _same_times(left: List[float], right: List[float], tolerance: float = 1e-6) -> bool:
    if len(left) != len(right):
        return False
    return all(abs(a - b) <= tolerance for a, b in zip(left, right))


@dataclass
class BoundaryMarker:
    """境界マーカー"""
    time: float  # 秒
    index: int   # シーンインデックス（この境界の後のシーン）
    

class TimelineBar(QWidget):
    """タイムラインバー - 境界線の表示とドラッグ"""
    
    # シグナル
    boundary_moved = Signal(int, float)  # index, new_time
    boundary_added = Signal(float)  # time
    boundary_removed = Signal(int)  # index
    position_clicked = Signal(float)  # time（クリックした位置）
    boundary_review_requested = Signal(float)
    
    MARKER_WIDTH = 8  # マーカーのドラッグ可能な幅
    MIN_SCENE_DURATION = 1.0  # 最小シーン長（秒）
    
    def __init__(self):
        super().__init__()
        self.duration: float = 0.0
        self.boundaries: List[BoundaryMarker] = []
        self.candidate_times: List[float] = []
        self.playhead_position: float = 0.0
        
        self._dragging_index: Optional[int] = None
        self._hover_index: Optional[int] = None
        
        self.setMinimumHeight(50)
        self.setMaximumHeight(60)
        self.setMinimumWidth(120)
        self.setMouseTracking(True)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("シーン境界タイムライン")
        self.setAccessibleDescription(
            "クリックでシーク、右クリックで境界の追加または削除、"
            "境界をドラッグして位置を調整します"
        )
        
        # 色設定
        self.color_background = QColor("#2a2a2a")
        self.color_scene_even = QColor("#4a7c59")
        self.color_scene_odd = QColor("#5a8c69")
        self.color_boundary = QColor("#ffcc00")
        self.color_boundary_hover = QColor("#ff9900")
        self.color_playhead = QColor("#ff3333")
        self.color_text = QColor("#ffffff")
    
    def set_duration(self, duration: float):
        """動画の長さを設定"""
        self.duration = duration
        self.update()
    
    def set_boundaries(self, boundaries: List[float]):
        """境界時刻のリストを設定（シーン開始時刻のリスト）"""
        self.boundaries = []
        for i, time in enumerate(boundaries):
            if time > 0:  # 0秒は境界として表示しない
                self.boundaries.append(BoundaryMarker(time=time, index=i))
        self.update()
    
    def set_playhead(self, position: float):
        """再生位置を設定"""
        self.playhead_position = position
        self.update()

    def set_candidates(self, candidates: List[float]):
        self.candidate_times = list(candidates)
        self.update()
    
    def _time_to_x(self, time: float) -> int:
        """時刻をX座標に変換"""
        if self.duration <= 0:
            return 0
        margin = 10
        available_width = max(1, self.width() - 2 * margin)
        return margin + int((time / self.duration) * available_width)

    def _x_to_time(self, x: int) -> float:
        """X座標を時刻に変換"""
        if self.duration <= 0:
            return 0
        margin = 10
        available_width = max(1, self.width() - 2 * margin)
        x_clamped = max(margin, min(x, self.width() - margin))
        return ((x_clamped - margin) / available_width) * self.duration
    
    def _get_boundary_at(self, x: int) -> Optional[int]:
        """指定X座標にある境界のインデックスを取得"""
        for i, marker in enumerate(self.boundaries):
            marker_x = self._time_to_x(marker.time)
            if abs(x - marker_x) <= self.MARKER_WIDTH:
                return i
        return None
    
    def paintEvent(self, event):
        """描画"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        width = self.width()
        height = self.height()
        margin = 10
        bar_height = 30
        bar_top = 10
        
        # 背景
        painter.fillRect(self.rect(), self.color_background)
        
        if self.duration <= 0:
            painter.setPen(self.color_text)
            painter.drawText(self.rect(), Qt.AlignCenter, "動画を読み込んでください")
            self._draw_focus_indicator(painter)
            return
        
        # シーン領域を描画
        scene_times = [0.0] + [m.time for m in self.boundaries] + [self.duration]
        label_font = QFont()
        label_font.setPointSize(10)
        label_font.setBold(True)
        for i in range(len(scene_times) - 1):
            start_x = self._time_to_x(scene_times[i])
            end_x = self._time_to_x(scene_times[i + 1])

            color = self.color_scene_even if i % 2 == 0 else self.color_scene_odd
            painter.fillRect(start_x, bar_top, end_x - start_x, bar_height, color)

            # シーン番号ラベル
            seg_width = end_x - start_x
            label = str(i + 1)
            painter.setFont(label_font)
            fm = painter.fontMetrics()
            text_w = fm.horizontalAdvance(label)
            if seg_width > text_w + 4:
                painter.setPen(QColor("#ffffff"))
                cx = start_x + (seg_width - text_w) // 2
                cy = bar_top + (bar_height + fm.ascent() - fm.descent()) // 2
                painter.drawText(cx, cy, label)
        
        # 未適用の解析候補は点線で表示し、確定済み境界と区別する。
        candidate_pen = QPen(QColor("#55bde6"), 2, Qt.DashLine)
        painter.setPen(candidate_pen)
        for time in self.candidate_times:
            x = self._time_to_x(time)
            painter.drawLine(x, bar_top, x, bar_top + bar_height)
            painter.setBrush(QBrush(QColor("#55bde6")))
            painter.drawEllipse(QPoint(x, bar_top + bar_height // 2), 3, 3)

        # 境界線を描画
        for i, marker in enumerate(self.boundaries):
            x = self._time_to_x(marker.time)
            
            # ホバー中または選択中は色を変える
            if i == self._hover_index or i == self._dragging_index:
                pen = QPen(self.color_boundary_hover, 3)
            else:
                pen = QPen(self.color_boundary, 2)
            
            painter.setPen(pen)
            painter.drawLine(x, bar_top - 5, x, bar_top + bar_height + 5)
            
            # ハンドル（三角形）
            painter.setBrush(QBrush(pen.color()))
            triangle = [
                QPoint(x - 5, bar_top - 5),
                QPoint(x + 5, bar_top - 5),
                QPoint(x, bar_top + 2)
            ]
            painter.drawPolygon(triangle)
        
        # 再生位置（プレイヘッド）
        playhead_x = self._time_to_x(self.playhead_position)
        painter.setPen(QPen(self.color_playhead, 2))
        painter.drawLine(playhead_x, bar_top, playhead_x, bar_top + bar_height)
        
        # 時間ラベル
        painter.setPen(self.color_text)
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        
        # 開始時刻
        painter.drawText(margin, height - 5, "0:00")
        
        # 終了時刻
        end_text = self._format_time(self.duration)
        text_width = painter.fontMetrics().horizontalAdvance(end_text)
        painter.drawText(width - margin - text_width, height - 5, end_text)
        
        # 現在位置
        current_text = self._format_time(self.playhead_position)
        painter.drawText(playhead_x - 20, height - 5, current_text)
        self._draw_focus_indicator(painter)

    def _draw_focus_indicator(self, painter: QPainter):
        if not self.hasFocus():
            return
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("#4da3ff"), 2))
        painter.drawRect(self.rect().adjusted(1, 1, -2, -2))

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()
    
    @staticmethod
    def _format_time(seconds: float) -> str:
        """秒を MM:SS 形式に変換"""
        return format_seconds(seconds)

    def mousePressEvent(self, event: QMouseEvent):
        """マウス押下"""
        if event.button() == Qt.LeftButton:
            x = event.position().x()
            boundary_idx = self._get_boundary_at(int(x))
            
            if boundary_idx is not None:
                # 境界をドラッグ開始
                self._dragging_index = boundary_idx
                self.setCursor(Qt.SizeHorCursor)
            else:
                # クリック位置に移動
                time = self._x_to_time(int(x))
                self.position_clicked.emit(time)
        
        elif event.button() == Qt.RightButton:
            # 右クリックメニュー
            self._show_context_menu(event.position().toPoint())
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """マウス移動"""
        x = int(event.position().x())
        
        if self._dragging_index is not None:
            # ドラッグ中
            new_time = self._x_to_time(x)
            
            # 前後の境界との距離を確保
            prev_time = 0.0
            next_time = self.duration
            
            if self._dragging_index > 0:
                prev_time = self.boundaries[self._dragging_index - 1].time
            if self._dragging_index < len(self.boundaries) - 1:
                next_time = self.boundaries[self._dragging_index + 1].time
            
            # 最小シーン長を確保
            new_time = max(prev_time + self.MIN_SCENE_DURATION, new_time)
            new_time = min(next_time - self.MIN_SCENE_DURATION, new_time)
            
            self.boundaries[self._dragging_index].time = new_time
            self.update()
        else:
            # ホバー判定
            boundary_idx = self._get_boundary_at(x)
            if boundary_idx != self._hover_index:
                self._hover_index = boundary_idx
                if boundary_idx is not None:
                    self.setCursor(Qt.SizeHorCursor)
                    # ツールチップ表示
                    time = self.boundaries[boundary_idx].time
                    QToolTip.showText(
                        event.globalPosition().toPoint(),
                        f"境界 {boundary_idx + 1}: {self._format_time(time)}\n"
                        f"ドラッグで移動 / 右クリックで削除"
                    )
                else:
                    self.setCursor(Qt.ArrowCursor)
                self.update()
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        """マウス解放"""
        if event.button() == Qt.LeftButton and self._dragging_index is not None:
            # ドラッグ完了 - シグナル発行
            marker = self.boundaries[self._dragging_index]
            self.boundary_moved.emit(marker.index, marker.time)
            self._dragging_index = None
            self.setCursor(Qt.ArrowCursor)
    
    def leaveEvent(self, event):
        """マウスがウィジェットから出た"""
        self._hover_index = None
        self.update()
    
    def _show_context_menu(self, pos: QPoint):
        """コンテキストメニューを表示"""
        menu = QMenu(self)
        
        x = pos.x()
        boundary_idx = self._get_boundary_at(x)
        
        if boundary_idx is not None:
            # 境界上で右クリック
            action_review = menu.addAction("境界の前後を比較")
            action_review.triggered.connect(
                lambda: self.boundary_review_requested.emit(
                    self.boundaries[boundary_idx].time
                )
            )
            menu.addSeparator()
            action_delete = menu.addAction("この境界を削除")
            action_delete.triggered.connect(
                lambda: self._on_delete_boundary(boundary_idx)
            )
        else:
            # 空白部分で右クリック
            time = self._x_to_time(x)
            action_add = menu.addAction(f"ここに境界を追加 ({self._format_time(time)})")
            action_add.triggered.connect(
                lambda: self.boundary_added.emit(time)
            )
        
        menu.exec(self.mapToGlobal(pos))
    
    def _on_delete_boundary(self, idx: int):
        """境界を削除"""
        if 0 <= idx < len(self.boundaries):
            marker = self.boundaries[idx]
            self.boundary_removed.emit(marker.index)


class TimelineWidget(QWidget):
    """タイムラインウィジェット（バー + コントロール）"""
    
    # シグナル
    boundaries_changed = Signal(list)  # 新しい境界時刻リスト
    seek_requested = Signal(float)  # シーク要求（秒）
    auto_detect_requested = Signal()
    auto_detect_cancel_requested = Signal()
    boundary_review_requested = Signal(float)
    boundary_candidates_applied = Signal(list)

    def __init__(self):
        super().__init__()
        self.duration: float = 0.0
        self.scene_start_times: List[float] = []
        self.boundary_candidates: List[float] = []
        self._detecting = False
        self._reviewed_boundary_time: Optional[float] = None
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # ヘッダー
        header_layout = QHBoxLayout()
        
        self.label_title = QLabel("タイムライン")
        self.label_title.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(self.label_title)

        self.candidate_summary_button = QPushButton()
        self.candidate_summary_button.setFlat(True)
        self.candidate_summary_button.setStyleSheet(
            "QPushButton { color: #72c8ea; font-weight: bold; "
            "border: 0; padding: 2px 4px; }"
            "QPushButton:hover { text-decoration: underline; }"
            "QPushButton:disabled { color: #777; }"
        )
        self.candidate_summary_button.setAccessibleName(
            "未適用の境界候補を追加"
        )
        self.candidate_summary_button.setToolTip(
            "音声・フェード解析の候補をタイムラインへ追加します"
        )
        self.candidate_summary_button.clicked.connect(self._on_apply_candidates)
        self.candidate_summary_button.hide()
        header_layout.addWidget(self.candidate_summary_button)
        
        header_layout.addStretch()

        # 検出設定は低頻度のため、常設せずメニュー内にまとめる。
        settings_panel = QWidget()
        settings_layout = QFormLayout(settings_panel)
        settings_layout.setContentsMargins(10, 8, 10, 8)
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.5, 10.0)
        self.threshold_spin.setSingleStep(0.5)
        self.threshold_spin.setValue(3.0)
        self.threshold_spin.setDecimals(1)
        self.threshold_spin.setFixedWidth(60)
        self.threshold_spin.setToolTip(
            "シーン検出の閾値（デフォルト: 3.0）\n"
            "小さくすると敏感になり分割が増え、大きくすると分割が減ります"
        )
        self.min_scene_spin = QDoubleSpinBox()
        self.min_scene_spin.setRange(0.0, 60.0)
        self.min_scene_spin.setSingleStep(0.5)
        self.min_scene_spin.setValue(2.0)
        self.min_scene_spin.setDecimals(1)
        self.min_scene_spin.setSuffix(" 秒")
        self.min_scene_spin.setFixedWidth(75)
        self.min_scene_spin.setToolTip(
            "これより短いシーンは検出時に隣のシーンへ統合されます\n"
            "細切れのクリップが大量にできる場合は値を大きくしてください（0で無効）"
        )
        settings_layout.addRow("感度", self.threshold_spin)
        settings_layout.addRow("最小シーン長", self.min_scene_spin)

        # 自動検出ボタン（検出中は「中止」ボタンになる）
        self.btn_auto_detect = QPushButton("自動検出")
        self.btn_auto_detect.setToolTip("映像の変化から分割候補を自動追加します")
        self.btn_auto_detect.clicked.connect(self._on_auto_detect_clicked)
        self.btn_auto_detect.setEnabled(False)
        header_layout.addWidget(self.btn_auto_detect)

        # 低頻度操作は1つのオーバーフローメニューへまとめる。
        self.btn_more = QPushButton("…")
        self.btn_more.setFixedWidth(38)
        self.btn_more.setStyleSheet(
            "QPushButton::menu-indicator { image: none; width: 0px; }"
        )
        self.btn_more.setAccessibleName("タイムラインのその他の操作")
        self.btn_more.setToolTip("検出設定、操作方法、境界のリセット")
        more_menu = QMenu(self.btn_more)
        more_menu.addSection("検出設定")
        self.settings_action = QWidgetAction(more_menu)
        self.settings_action.setText("検出設定")
        self.settings_action.setToolTip("シーン検出の感度と最小シーン長")
        self.settings_action.setDefaultWidget(settings_panel)
        more_menu.addAction(self.settings_action)

        self.btn_review_boundary = QPushButton("境界確認")
        self.btn_review_boundary.setToolTip(
            "再生位置に最も近い境界の直前・直後を並べて確認します"
        )
        self.btn_review_boundary.clicked.connect(self._review_nearest_boundary)
        self.btn_review_boundary.setEnabled(False)
        header_layout.addWidget(self.btn_review_boundary)

        help_menu = more_menu.addMenu("操作方法")
        for text in (
            "Space　再生／一時停止",
            "S　現在位置で分割",
            "← / →　選択した幅で移動",
            "Undo　直前の編集を戻す",
            "タイムラインをドラッグ　境界を調整",
            "右クリック　境界を追加／削除",
        ):
            action = help_menu.addAction(text)
            action.setEnabled(False)
        more_menu.addSeparator()
        self.btn_reset = more_menu.addAction("境界をすべて削除")
        self.btn_reset.setToolTip("動画全体を1つのクリップへ戻します")
        self.btn_reset.triggered.connect(self._on_reset)
        self.btn_reset.setEnabled(False)
        self.btn_more.setMenu(more_menu)
        header_layout.addWidget(self.btn_more)
        
        layout.addLayout(header_layout)
        
        # タイムラインバー
        self.timeline_bar = TimelineBar()
        self.timeline_bar.boundary_moved.connect(self._on_boundary_moved)
        self.timeline_bar.boundary_added.connect(self._on_boundary_added)
        self.timeline_bar.boundary_removed.connect(self._on_boundary_removed)
        self.timeline_bar.position_clicked.connect(self._on_position_clicked)
        self.timeline_bar.boundary_review_requested.connect(
            self._open_boundary_review
        )
        layout.addWidget(self.timeline_bar)

        # 境界確認は明示的に開いたときだけ現れるインラインパネル。
        self.boundary_review_panel = QFrame()
        self.boundary_review_panel.setObjectName("boundaryReviewPanel")
        self.boundary_review_panel.setStyleSheet(
            "QFrame#boundaryReviewPanel { background-color: #20252a; "
            "border: 1px solid #3d596d; border-radius: 4px; }"
        )
        review_layout = QVBoxLayout(self.boundary_review_panel)
        review_layout.setContentsMargins(8, 6, 8, 6)
        review_layout.setSpacing(5)

        review_header = QHBoxLayout()
        self.boundary_review_title = QLabel("境界")
        self.boundary_review_title.setStyleSheet("font-weight: bold;")
        review_header.addWidget(self.boundary_review_title)
        self.boundary_review_status = QLabel("")
        self.boundary_review_status.setStyleSheet("color: #aaa;")
        review_header.addWidget(self.boundary_review_status)
        review_header.addStretch()
        self.btn_close_boundary_review = QPushButton("閉じる")
        self.btn_close_boundary_review.clicked.connect(
            self.boundary_review_panel.hide
        )
        review_header.addWidget(self.btn_close_boundary_review)
        review_layout.addLayout(review_header)

        images_layout = QHBoxLayout()
        images_layout.setSpacing(8)
        self.boundary_before_label = QLabel("境界前")
        self.boundary_after_label = QLabel("境界後")
        for label, caption in (
            (self.boundary_before_label, "境界前 −0.25秒"),
            (self.boundary_after_label, "境界後 ＋0.25秒"),
        ):
            label.setFixedSize(160, 90)
            label.setAlignment(Qt.AlignCenter)
            label.setText(caption)
            label.setStyleSheet("background-color: #161616; border: 1px solid #444;")
            label.setAccessibleName(caption)
            column = QWidget()
            column_layout = QVBoxLayout(column)
            column_layout.setContentsMargins(0, 0, 0, 0)
            column_layout.setSpacing(3)
            caption_label = QLabel(caption)
            caption_label.setAlignment(Qt.AlignCenter)
            caption_label.setStyleSheet("color: #bbb; font-size: 10px;")
            column_layout.addWidget(caption_label)
            column_layout.addWidget(label, alignment=Qt.AlignCenter)
            images_layout.addWidget(column, stretch=1)
        review_layout.addLayout(images_layout)

        controls = QHBoxLayout()
        controls.addStretch()
        self.btn_boundary_earlier = QPushButton("−0.1秒")
        self.btn_boundary_earlier.setToolTip("境界を0.1秒前へ移動")
        self.btn_boundary_earlier.clicked.connect(
            lambda: self._nudge_reviewed_boundary(-0.1)
        )
        controls.addWidget(self.btn_boundary_earlier)
        self.btn_boundary_later = QPushButton("＋0.1秒")
        self.btn_boundary_later.setToolTip("境界を0.1秒後へ移動")
        self.btn_boundary_later.clicked.connect(
            lambda: self._nudge_reviewed_boundary(0.1)
        )
        controls.addWidget(self.btn_boundary_later)
        review_layout.addLayout(controls)
        layout.addWidget(self.boundary_review_panel)
        self.boundary_review_panel.hide()
        
    
    def set_scenes(self, scene_start_times: List[float], duration: float):
        """シーン情報を設定"""
        self.duration = duration
        self.scene_start_times = scene_start_times.copy()
        self._reviewed_boundary_time = None
        self.boundary_review_panel.hide()

        self.timeline_bar.set_duration(duration)
        self.timeline_bar.set_boundaries(scene_start_times)
        self.timeline_bar.set_candidates(self.boundary_candidates)

        self.btn_reset.setEnabled(True)
        self.btn_auto_detect.setEnabled(True)
        self.settings_action.setEnabled(True)
        self.btn_review_boundary.setEnabled(len(self.scene_start_times) > 1)
        self._sync_recommended_action()

    def clear(self):
        """タイムラインを空にする"""
        self.duration = 0.0
        self.scene_start_times = []
        self.timeline_bar.set_duration(0.0)
        self.timeline_bar.set_boundaries([])
        self.set_boundary_candidates([])
        self.timeline_bar.set_playhead(0.0)
        self.btn_reset.setEnabled(False)
        self.btn_auto_detect.setEnabled(False)
        self.settings_action.setEnabled(False)
        self.btn_review_boundary.setEnabled(False)
        self.boundary_review_panel.hide()
        self._reviewed_boundary_time = None
        self._sync_recommended_action()

    def add_boundary(self, time: float):
        """境界を追加する（公開API）"""
        self._on_boundary_added(time)

    def replace_boundaries(self, scene_start_times: List[float]):
        """境界時刻をまとめて置き換える"""
        if self.duration <= 0:
            return

        normalized = sorted({
            max(0.0, min(float(time), self.duration))
            for time in scene_start_times
        })
        if not normalized or normalized[0] != 0.0:
            normalized.insert(0, 0.0)

        if _same_times(normalized, self.scene_start_times):
            return

        self.scene_start_times = normalized
        self.timeline_bar.set_boundaries(normalized)
        self.btn_reset.setEnabled(True)
        self.btn_review_boundary.setEnabled(len(self.scene_start_times) > 1)
        self._sync_recommended_action()
        self._emit_changes()

    def set_boundary_candidates(self, candidates: List[float]):
        """解析で見つかった未適用候補を確定境界とは別に表示する。"""
        normalized = sorted({
            round(float(time), 3)
            for time in candidates
            if 0.0 < float(time) < self.duration
        })
        self.boundary_candidates = normalized
        self.timeline_bar.set_candidates(normalized)
        if normalized:
            self.candidate_summary_button.setText(
                f"候補 {len(normalized)}件を追加"
            )
            self.candidate_summary_button.setEnabled(not self._detecting)
            self.candidate_summary_button.show()
        else:
            self.candidate_summary_button.hide()
            self.candidate_summary_button.setEnabled(False)

    def set_auto_detect_enabled(self, enabled: bool):
        """自動検出ボタンの有効状態を設定"""
        self.btn_auto_detect.setEnabled(enabled and self.duration > 0)
        self._sync_recommended_action()

    def set_detecting(self, detecting: bool):
        """検出中の表示状態を切り替える（検出中はボタンが「中止」になる）"""
        self._detecting = detecting
        if detecting:
            self.btn_auto_detect.setText("中止")
            self.btn_auto_detect.setToolTip("シーン自動検出を中止します")
            self.btn_auto_detect.setEnabled(True)
        else:
            self.btn_auto_detect.setText("自動検出")
            self.btn_auto_detect.setToolTip("映像の変化から分割候補を自動追加します")
            self.btn_auto_detect.setEnabled(self.duration > 0)
        self.btn_reset.setEnabled(self.duration > 0 and not detecting)
        # 検出中は設定変更を受け付けない
        self.threshold_spin.setEnabled(not detecting)
        self.min_scene_spin.setEnabled(not detecting)
        self.settings_action.setEnabled(self.duration > 0 and not detecting)
        self.btn_review_boundary.setEnabled(
            len(self.scene_start_times) > 1 and not detecting
        )
        self.candidate_summary_button.setEnabled(
            bool(self.boundary_candidates) and not detecting
        )
        self._sync_recommended_action()

    def _sync_recommended_action(self):
        set_recommended_action(
            self.btn_auto_detect,
            self.duration > 0
            and len(self.scene_start_times) <= 1
            and not self._detecting
            and self.btn_auto_detect.isEnabled(),
        )

    def _on_auto_detect_clicked(self):
        if self._detecting:
            self.auto_detect_cancel_requested.emit()
        else:
            self.auto_detect_requested.emit()

    def get_detection_settings(self) -> SceneDetectionSettings:
        """UIの値からシーン検出設定を構築"""
        return SceneDetectionSettings(
            adaptive_threshold=self.threshold_spin.value(),
            min_scene_duration_seconds=self.min_scene_spin.value(),
        )
    
    def set_playhead(self, position: float):
        """再生位置を更新"""
        self.timeline_bar.set_playhead(position)
    
    def get_boundaries(self) -> List[float]:
        """現在の境界時刻リストを取得"""
        return [0.0] + [m.time for m in self.timeline_bar.boundaries]
    
    def _on_boundary_moved(self, index: int, new_time: float):
        """境界が移動された"""
        # scene_start_timesを更新
        if 0 < index < len(self.scene_start_times):
            self.scene_start_times[index] = new_time
        self._emit_changes()
    
    def _on_boundary_added(self, time: float):
        """境界が追加された"""
        # 既存境界とほぼ同じ位置への二重追加を防ぐ
        if any(abs(time - t) < 0.05 for t in self.scene_start_times):
            return

        # 適切な位置に挿入
        new_times = self.scene_start_times.copy()
        
        # 挿入位置を探す
        insert_idx = 0
        for i, t in enumerate(new_times):
            if t < time:
                insert_idx = i + 1
            else:
                break
        
        new_times.insert(insert_idx, time)
        self.scene_start_times = new_times
        
        self.timeline_bar.set_boundaries(new_times)
        self._emit_changes()
    
    def _on_boundary_removed(self, index: int):
        """境界が削除された"""
        if 0 < index < len(self.scene_start_times):
            del self.scene_start_times[index]
            self.timeline_bar.set_boundaries(self.scene_start_times)
            self.btn_review_boundary.setEnabled(len(self.scene_start_times) > 1)
            self.boundary_review_panel.hide()
            self._emit_changes()
    
    def _on_reset(self):
        """全ての境界をクリアして動画全体を1シーンに戻す"""
        if self.duration <= 0:
            return
        if len(self.scene_start_times) > 1:
            reply = QMessageBox.question(
                self,
                "境界をすべて削除",
                f"{len(self.scene_start_times)}個のクリップを1つに戻しますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        self.replace_boundaries([0.0])

    def _on_apply_candidates(self):
        if not self.boundary_candidates:
            return
        candidates = list(self.boundary_candidates)
        self.replace_boundaries(self.scene_start_times + candidates)
        self.set_boundary_candidates([])
        self.boundary_candidates_applied.emit(candidates)
    
    def _on_position_clicked(self, time: float):
        """タイムライン上でクリックされた"""
        self.seek_requested.emit(time)

    def _review_nearest_boundary(self):
        boundaries = self.scene_start_times[1:]
        if not boundaries:
            return
        nearest = min(
            boundaries,
            key=lambda boundary: abs(boundary - self.timeline_bar.playhead_position),
        )
        self._open_boundary_review(nearest)

    def _open_boundary_review(self, boundary_time: float):
        self._reviewed_boundary_time = float(boundary_time)
        self.boundary_review_title.setText(f"境界 {boundary_time:.2f}秒")
        self.boundary_review_status.setText("画像を準備中…")
        self.boundary_before_label.setPixmap(QPixmap())
        self.boundary_after_label.setPixmap(QPixmap())
        self.boundary_before_label.setText("境界前 −0.25秒")
        self.boundary_after_label.setText("境界後 ＋0.25秒")
        self.boundary_review_panel.show()
        self.boundary_review_requested.emit(float(boundary_time))

    def show_boundary_preview(
        self,
        boundary_time: float,
        before_path: str,
        after_path: str,
    ) -> None:
        """生成済みの境界前後画像をインラインパネルへ表示する。"""
        if (
            self._reviewed_boundary_time is None
            or abs(self._reviewed_boundary_time - boundary_time) > 0.001
        ):
            return
        loaded = 0
        for label, path in (
            (self.boundary_before_label, before_path),
            (self.boundary_after_label, after_path),
        ):
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                label.setPixmap(
                    pixmap.scaled(
                        label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                )
                loaded += 1
        self.boundary_review_status.setText(
            "前後を比較" if loaded == 2 else "画像を表示できませんでした"
        )

    def _nudge_reviewed_boundary(self, delta: float):
        if self._reviewed_boundary_time is None or len(self.scene_start_times) < 2:
            return
        index = min(
            range(1, len(self.scene_start_times)),
            key=lambda i: abs(self.scene_start_times[i] - self._reviewed_boundary_time),
        )
        previous = self.scene_start_times[index - 1]
        following = (
            self.scene_start_times[index + 1]
            if index + 1 < len(self.scene_start_times)
            else self.duration
        )
        new_time = round(
            max(previous + TimelineBar.MIN_SCENE_DURATION, min(
                following - TimelineBar.MIN_SCENE_DURATION,
                self.scene_start_times[index] + delta,
            )),
            3,
        )
        if abs(new_time - self.scene_start_times[index]) <= 1e-6:
            return
        self.scene_start_times[index] = new_time
        self.timeline_bar.set_boundaries(self.scene_start_times)
        self._emit_changes()
        self._open_boundary_review(new_time)
    
    def _emit_changes(self):
        """変更をシグナルで通知"""
        self._sync_recommended_action()
        self.boundaries_changed.emit(self.get_boundaries())
