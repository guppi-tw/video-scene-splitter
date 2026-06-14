"""
タイムラインウィジェット - シーン境界の視覚的表示と調整
"""
from typing import Optional, List
from dataclasses import dataclass

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QToolTip, QMenu, QDoubleSpinBox
)
from PySide6.QtCore import Qt, Signal, QRect, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QMouseEvent, QFont

from app.core.scene_detector import SceneDetectionSettings
from app.core.time_format import format_seconds


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
    
    MARKER_WIDTH = 8  # マーカーのドラッグ可能な幅
    MIN_SCENE_DURATION = 1.0  # 最小シーン長（秒）
    
    def __init__(self):
        super().__init__()
        self.duration: float = 0.0
        self.boundaries: List[BoundaryMarker] = []
        self.playhead_position: float = 0.0
        
        self._dragging_index: Optional[int] = None
        self._hover_index: Optional[int] = None
        
        self.setMinimumHeight(50)
        self.setMaximumHeight(60)
        self.setMinimumWidth(120)
        self.setMouseTracking(True)
        self.setCursor(Qt.ArrowCursor)
        
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

    def __init__(self):
        super().__init__()
        self.duration: float = 0.0
        self.scene_start_times: List[float] = []
        self._detecting = False
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
        
        header_layout.addStretch()

        # 検出設定: 閾値（感度）
        label_threshold = QLabel("感度:")
        label_threshold.setStyleSheet("color: #aaa; font-size: 11px;")
        header_layout.addWidget(label_threshold)

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
        header_layout.addWidget(self.threshold_spin)

        # 検出設定: 最小シーン長（秒）
        label_min_len = QLabel("最小シーン長:")
        label_min_len.setStyleSheet("color: #aaa; font-size: 11px;")
        header_layout.addWidget(label_min_len)

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
        header_layout.addWidget(self.min_scene_spin)

        # 自動検出ボタン（検出中は「中止」ボタンになる）
        self.btn_auto_detect = QPushButton("自動検出")
        self.btn_auto_detect.setToolTip("映像の変化から分割候補を自動追加します")
        self.btn_auto_detect.clicked.connect(self._on_auto_detect_clicked)
        self.btn_auto_detect.setEnabled(False)
        header_layout.addWidget(self.btn_auto_detect)

        # リセットボタン
        self.btn_reset = QPushButton("リセット")
        self.btn_reset.setToolTip("全ての境界をクリアして元に戻す")
        self.btn_reset.clicked.connect(self._on_reset)
        self.btn_reset.setEnabled(False)
        header_layout.addWidget(self.btn_reset)
        
        layout.addLayout(header_layout)
        
        # タイムラインバー
        self.timeline_bar = TimelineBar()
        self.timeline_bar.boundary_moved.connect(self._on_boundary_moved)
        self.timeline_bar.boundary_added.connect(self._on_boundary_added)
        self.timeline_bar.boundary_removed.connect(self._on_boundary_removed)
        self.timeline_bar.position_clicked.connect(self._on_position_clicked)
        layout.addWidget(self.timeline_bar)
        
        # 説明
        help_label = QLabel(
            "Space: 再生/停止  S: 分割  左右: コマ送り  Ctrl+Z: 戻す  |  "
            "ドラッグ: 境界調整  右クリック: 追加/削除  クリック: シーク"
        )
        help_label.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(help_label)
    
    def set_scenes(self, scene_start_times: List[float], duration: float):
        """シーン情報を設定"""
        self.duration = duration
        self.scene_start_times = scene_start_times.copy()

        self.timeline_bar.set_duration(duration)
        self.timeline_bar.set_boundaries(scene_start_times)

        self.btn_reset.setEnabled(True)
        self.btn_auto_detect.setEnabled(True)

    def clear(self):
        """タイムラインを空にする"""
        self.duration = 0.0
        self.scene_start_times = []
        self.timeline_bar.set_duration(0.0)
        self.timeline_bar.set_boundaries([])
        self.timeline_bar.set_playhead(0.0)
        self.btn_reset.setEnabled(False)
        self.btn_auto_detect.setEnabled(False)

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
        self._emit_changes()

    def set_auto_detect_enabled(self, enabled: bool):
        """自動検出ボタンの有効状態を設定"""
        self.btn_auto_detect.setEnabled(enabled and self.duration > 0)

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
        # 検出中は設定変更を受け付けない
        self.threshold_spin.setEnabled(not detecting)
        self.min_scene_spin.setEnabled(not detecting)

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
            self._emit_changes()
    
    def _on_reset(self):
        """全ての境界をクリアして動画全体を1シーンに戻す"""
        if self.duration <= 0:
            return
        self.replace_boundaries([0.0])
    
    def _on_position_clicked(self, time: float):
        """タイムライン上でクリックされた"""
        self.seek_requested.emit(time)
    
    def _emit_changes(self):
        """変更をシグナルで通知"""
        self.boundaries_changed.emit(self.get_boundaries())
