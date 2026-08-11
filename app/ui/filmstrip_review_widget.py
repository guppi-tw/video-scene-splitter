"""動画全体を折り返して俯瞰するフィルムストリップレビュー。"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QPolygon,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.jobs import Scene, VideoJob
from app.core.time_format import format_seconds


def filmstrip_row_count(duration: float, seconds_per_row: float) -> int:
    """動画尺と1行の秒数から、少なくとも1行を返す。"""
    if duration <= 0 or seconds_per_row <= 0:
        return 1
    return max(1, math.ceil(duration / seconds_per_row))


class FilmstripCanvas(QWidget):
    """1本の時間軸を複数行に折り返して描画するキャンバス。"""

    seek_requested = Signal(float)
    edit_requested = Signal(float)

    ROW_HEIGHT = 148
    TOP_MARGIN = 10
    LEFT_GUTTER = 68
    RIGHT_MARGIN = 18
    FILM_TOP = 27
    FILM_HEIGHT = 92
    IMAGE_TOP = 39
    IMAGE_HEIGHT = 58
    STATUS_TOP = 98
    STATUS_HEIGHT = 17

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.job: Optional[VideoJob] = None
        self.duration = 0.0
        self.seconds_per_row = 60.0
        self.playhead_position = 0.0
        self.candidate_times: list[float] = []
        self._hover_position: Optional[float] = None
        self._pixmap_cache: dict[Path, QPixmap] = {}

        self.setMinimumWidth(420)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAccessibleName("折り返しフィルムタイムライン")
        self.setAccessibleDescription(
            "動画全体を複数行で表示します。クリックでシーク、"
            "ダブルクリックで通常編集へ移動します。"
        )

    def set_job(self, job: Optional[VideoJob]):
        self.job = job
        self.duration = (
            float(job.scenes[-1].end_time)
            if job is not None and job.scenes
            else 0.0
        )
        self._pixmap_cache.clear()
        self.candidate_times = (
            list(job.suggested_boundaries) if job is not None else []
        )
        self._sync_canvas_height()
        self.update()

    def refresh(self):
        """同じジョブの編集結果を再描画する。"""
        self.duration = (
            float(self.job.scenes[-1].end_time)
            if self.job is not None and self.job.scenes
            else 0.0
        )
        self._sync_canvas_height()
        self.update()

    def update_thumbnail(self, scene_index: int, path: str):
        if self.job is None:
            return
        for scene in self.job.scenes:
            if scene.index == scene_index:
                scene.thumbnail_path = Path(path)
                self._pixmap_cache.pop(Path(path), None)
                self.update()
                return

    def set_seconds_per_row(self, seconds: float):
        seconds = max(1.0, float(seconds))
        if math.isclose(seconds, self.seconds_per_row):
            return
        self.seconds_per_row = seconds
        self._sync_canvas_height()
        self.update()

    def set_candidates(self, candidates: list[float]):
        self.candidate_times = sorted({
            round(float(candidate), 3)
            for candidate in candidates
            if 0.0 < float(candidate) < self.duration
        })
        self.update()

    def set_playhead(self, position: float):
        self.playhead_position = max(0.0, min(float(position), self.duration))
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(900, self._content_height())

    def minimumSizeHint(self) -> QSize:
        return QSize(420, self._content_height())

    def _content_height(self) -> int:
        rows = filmstrip_row_count(self.duration, self.seconds_per_row)
        return self.TOP_MARGIN * 2 + rows * self.ROW_HEIGHT

    def _sync_canvas_height(self):
        self.setMinimumHeight(self._content_height())
        self.setMaximumHeight(self._content_height())
        self.updateGeometry()

    def _timeline_rect(self, row: int) -> QRect:
        top = self.TOP_MARGIN + row * self.ROW_HEIGHT
        return QRect(
            self.LEFT_GUTTER,
            top + self.FILM_TOP,
            max(1, self.width() - self.LEFT_GUTTER - self.RIGHT_MARGIN),
            self.FILM_HEIGHT,
        )

    def _row_bounds(self, row: int) -> tuple[float, float]:
        start = row * self.seconds_per_row
        return start, min(self.duration, start + self.seconds_per_row)

    def _time_to_x(self, value: float, row: int) -> int:
        rect = self._timeline_rect(row)
        row_start = row * self.seconds_per_row
        ratio = (value - row_start) / self.seconds_per_row
        return rect.left() + round(max(0.0, min(1.0, ratio)) * rect.width())

    def _point_to_time(self, point: QPoint) -> Optional[float]:
        if self.duration <= 0:
            return None
        relative_y = point.y() - self.TOP_MARGIN
        if relative_y < 0:
            return None
        row = int(relative_y // self.ROW_HEIGHT)
        if row >= filmstrip_row_count(self.duration, self.seconds_per_row):
            return None
        rect = self._timeline_rect(row)
        if not rect.adjusted(0, -8, 0, 8).contains(point):
            return None
        ratio = (point.x() - rect.left()) / max(1, rect.width())
        ratio = max(0.0, min(1.0, ratio))
        position = row * self.seconds_per_row + ratio * self.seconds_per_row
        if position > self.duration + 1e-6:
            return None
        return min(self.duration, position)

    def _scene_at(self, position: float) -> Optional[Scene]:
        if self.job is None:
            return None
        for scene in self.job.scenes:
            if scene.start_time <= position < scene.end_time:
                return scene
        return self.job.scenes[-1] if self.job.scenes else None

    def _scene_pixmap(self, scene: Scene) -> Optional[QPixmap]:
        if not scene.thumbnail_path:
            return None
        path = Path(scene.thumbnail_path)
        if not path.exists():
            return None
        cached = self._pixmap_cache.get(path)
        if cached is None:
            cached = QPixmap(str(path))
            self._pixmap_cache[path] = cached
        return cached if not cached.isNull() else None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#17191c"))

        if self.job is None or not self.job.scenes or self.duration <= 0:
            painter.setPen(QColor("#aeb4bc"))
            painter.drawText(self.rect(), Qt.AlignCenter, "レビューする動画を選択してください")
            return

        rows = filmstrip_row_count(self.duration, self.seconds_per_row)
        first_row = max(
            0,
            int((event.rect().top() - self.TOP_MARGIN) // self.ROW_HEIGHT),
        )
        last_row = min(
            rows - 1,
            int((event.rect().bottom() - self.TOP_MARGIN) // self.ROW_HEIGHT),
        )
        for row in range(first_row, last_row + 1):
            self._draw_row(painter, row)

        self._draw_focus_indicator(painter)

    def _draw_row(self, painter: QPainter, row: int):
        row_start, row_end = self._row_bounds(row)
        timeline = self._timeline_rect(row)
        row_top = self.TOP_MARGIN + row * self.ROW_HEIGHT

        painter.setPen(QColor("#d7dbe0"))
        label_font = QFont(painter.font())
        label_font.setBold(True)
        painter.setFont(label_font)
        painter.drawText(
            QRect(6, row_top + self.FILM_TOP, self.LEFT_GUTTER - 12, 22),
            Qt.AlignRight | Qt.AlignVCenter,
            format_seconds(row_start),
        )

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#090a0c"))
        painter.drawRoundedRect(timeline, 5, 5)
        self._draw_perforations(painter, timeline)

        image_band = QRect(
            timeline.left(),
            row_top + self.IMAGE_TOP,
            timeline.width(),
            self.IMAGE_HEIGHT,
        )
        painter.fillRect(image_band, QColor("#272b30"))

        for scene in self.job.scenes:
            overlap_start = max(row_start, scene.start_time)
            overlap_end = min(row_start + self.seconds_per_row, scene.end_time)
            if overlap_end <= overlap_start:
                continue
            self._draw_scene_segment(
                painter,
                row,
                row_top,
                scene,
                overlap_start,
                overlap_end,
            )

        self._draw_ruler(painter, row, row_top, row_start, row_end)
        self._draw_candidates(painter, row, row_top, row_start)
        self._draw_boundaries(painter, row, row_top, row_start)
        self._draw_playhead(painter, row, row_top, row_start)

        painter.setPen(QPen(QColor("#34383e"), 1))
        painter.drawLine(
            self.LEFT_GUTTER,
            row_top + self.ROW_HEIGHT - 1,
            self.width() - self.RIGHT_MARGIN,
            row_top + self.ROW_HEIGHT - 1,
        )

    def _draw_perforations(self, painter: QPainter, timeline: QRect):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#4b5057"))
        hole_width = 10
        gap = 9
        x = timeline.left() + 7
        while x + hole_width < timeline.right():
            painter.drawRoundedRect(QRect(x, timeline.top() + 4, hole_width, 5), 1, 1)
            painter.drawRoundedRect(QRect(x, timeline.bottom() - 8, hole_width, 5), 1, 1)
            x += hole_width + gap

    def _draw_scene_segment(
        self,
        painter: QPainter,
        row: int,
        row_top: int,
        scene: Scene,
        start: float,
        end: float,
    ):
        x1 = self._time_to_x(start, row)
        x2 = self._time_to_x(end, row)
        width = max(1, x2 - x1)
        image_rect = QRect(x1, row_top + self.IMAGE_TOP, width, self.IMAGE_HEIGHT)
        status_rect = QRect(x1, row_top + self.STATUS_TOP, width, self.STATUS_HEIGHT)

        pixmap = self._scene_pixmap(scene)
        if pixmap is not None:
            scaled = pixmap.scaled(
                image_rect.size(),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            source = QRect(
                max(0, (scaled.width() - image_rect.width()) // 2),
                max(0, (scaled.height() - image_rect.height()) // 2),
                min(image_rect.width(), scaled.width()),
                min(image_rect.height(), scaled.height()),
            )
            painter.drawPixmap(image_rect, scaled, source)
        else:
            painter.fillRect(image_rect, QColor("#30353b"))

        if scene.keep:
            status_color = QColor("#315f45") if not scene.is_sensitive else QColor("#6b5725")
            status_text = "共有注意" if scene.is_sensitive else "書き出し"
        else:
            status_color = QColor("#7b3035")
            status_text = "削除"
            painter.fillRect(image_rect, QColor(105, 24, 29, 105))

        painter.fillRect(status_rect, status_color)
        if not scene.keep:
            painter.save()
            painter.setClipRect(status_rect)
            painter.setPen(QPen(QColor("#d8797e"), 1))
            for x in range(status_rect.left() - 20, status_rect.right() + 20, 10):
                painter.drawLine(x, status_rect.bottom(), x + 18, status_rect.top())
            painter.restore()

        if width >= 44:
            painter.setPen(QColor("#ffffff"))
            small_font = QFont(painter.font())
            small_font.setPointSize(max(8, small_font.pointSize() - 1))
            small_font.setBold(True)
            painter.setFont(small_font)
            painter.drawText(status_rect.adjusted(4, 0, -3, 0), Qt.AlignVCenter, status_text)
        if width >= 58:
            painter.setPen(QColor(255, 255, 255, 215))
            painter.drawText(
                image_rect.adjusted(5, 3, -4, -3),
                Qt.AlignLeft | Qt.AlignTop,
                f"#{scene.index}",
            )

    def _draw_ruler(
        self,
        painter: QPainter,
        row: int,
        row_top: int,
        row_start: float,
        row_end: float,
    ):
        tick_step = 5.0 if self.seconds_per_row <= 60 else (10.0 if self.seconds_per_row <= 120 else 30.0)
        first_tick = math.ceil(row_start / tick_step) * tick_step
        tick = first_tick
        painter.setFont(QFont(painter.font().family(), 8))
        while tick <= row_end + 1e-6:
            x = self._time_to_x(tick, row)
            major = math.isclose(tick % (tick_step * 2), 0.0, abs_tol=1e-5)
            painter.setPen(QPen(QColor("#8c939d"), 1))
            painter.drawLine(
                x,
                row_top + self.FILM_TOP - (6 if major else 3),
                x,
                row_top + self.FILM_TOP,
            )
            if major and tick > row_start + 1e-6:
                painter.setPen(QColor("#8c939d"))
                painter.drawText(
                    QRect(x - 30, row_top + 3, 60, 17),
                    Qt.AlignCenter,
                    format_seconds(tick),
                )
            tick += tick_step

    def _draw_boundaries(self, painter: QPainter, row: int, row_top: int, row_start: float):
        row_end = row_start + self.seconds_per_row
        painter.setPen(QPen(QColor("#ffd05a"), 2, Qt.SolidLine))
        for scene in self.job.scenes[1:]:
            boundary = scene.start_time
            if not (row_start < boundary <= row_end):
                continue
            x = self._time_to_x(boundary, row)
            painter.drawLine(
                x,
                row_top + self.FILM_TOP - 3,
                x,
                row_top + self.FILM_TOP + self.FILM_HEIGHT + 3,
            )
            painter.setBrush(QColor("#ffd05a"))
            painter.setPen(Qt.NoPen)
            painter.drawPolygon(QPolygon([
                QPoint(x, row_top + self.FILM_TOP - 3),
                QPoint(x - 4, row_top + self.FILM_TOP - 9),
                QPoint(x + 4, row_top + self.FILM_TOP - 9),
            ]))

    def _draw_candidates(self, painter: QPainter, row: int, row_top: int, row_start: float):
        row_end = row_start + self.seconds_per_row
        painter.setPen(QPen(QColor("#58b8df"), 2, Qt.DashLine))
        for candidate in self.candidate_times:
            if not (row_start < candidate <= row_end):
                continue
            x = self._time_to_x(candidate, row)
            painter.drawLine(
                x,
                row_top + self.IMAGE_TOP,
                x,
                row_top + self.STATUS_TOP + self.STATUS_HEIGHT,
            )

    def _draw_playhead(self, painter: QPainter, row: int, row_top: int, row_start: float):
        row_end = row_start + self.seconds_per_row
        playhead_row = min(
            int(self.playhead_position // self.seconds_per_row),
            filmstrip_row_count(self.duration, self.seconds_per_row) - 1,
        )
        if row != playhead_row or not (row_start <= self.playhead_position <= row_end):
            return
        x = self._time_to_x(self.playhead_position, row)
        painter.setPen(QPen(QColor("#ff5d66"), 2))
        painter.drawLine(
            x,
            row_top + self.FILM_TOP - 7,
            x,
            row_top + self.FILM_TOP + self.FILM_HEIGHT + 6,
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ff5d66"))
        painter.drawPolygon(QPolygon([
            QPoint(x, row_top + self.FILM_TOP - 1),
            QPoint(x - 5, row_top + self.FILM_TOP - 8),
            QPoint(x + 5, row_top + self.FILM_TOP - 8),
        ]))

    def _draw_focus_indicator(self, painter: QPainter):
        if not self.hasFocus():
            return
        painter.setPen(QPen(QColor("#62aeea"), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.rect().adjusted(1, 1, -2, -2))

    def mouseMoveEvent(self, event: QMouseEvent):
        position = self._point_to_time(event.position().toPoint())
        self._hover_position = position
        if position is None:
            self.unsetCursor()
            self.setToolTip("")
            return
        self.setCursor(Qt.PointingHandCursor)
        scene = self._scene_at(position)
        state = "削除ゾーン" if scene is not None and not scene.keep else "書き出し対象"
        scene_label = f"シーン #{scene.index}・{state}" if scene is not None else ""
        self.setToolTip(
            f"{format_seconds(position)}  {scene_label}\n"
            "クリックでシーク／ダブルクリックで通常編集"
        )

    def leaveEvent(self, event):
        self._hover_position = None
        self.unsetCursor()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        position = self._point_to_time(event.position().toPoint())
        if position is not None:
            self.setFocus(Qt.MouseFocusReason)
            self.set_playhead(position)
            self.seek_requested.emit(position)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton:
            return super().mouseDoubleClickEvent(event)
        position = self._point_to_time(event.position().toPoint())
        if position is not None:
            self.set_playhead(position)
            self.edit_requested.emit(position)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_Left, Qt.Key_Right):
            delta = -1.0 if event.key() == Qt.Key_Left else 1.0
            position = max(0.0, min(self.duration, self.playhead_position + delta))
            self.set_playhead(position)
            self.seek_requested.emit(position)
            event.accept()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.edit_requested.emit(self.playhead_position)
            event.accept()
            return
        super().keyPressEvent(event)


class FilmstripReviewWidget(QWidget):
    """フィルムストリップの操作バーとスクロール領域。"""

    seek_requested = Signal(float)
    edit_requested = Signal(float)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.current_job: Optional[VideoJob] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        header = QFrame()
        header.setObjectName("filmstripHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 7, 10, 7)
        header_layout.setSpacing(8)

        title = QLabel("フィルムレビュー")
        title.setObjectName("filmstripTitle")
        header_layout.addWidget(title)

        self.summary_label = QLabel("動画を選択してください")
        self.summary_label.setObjectName("filmstripSummary")
        header_layout.addWidget(self.summary_label)
        header_layout.addStretch()

        row_length_label = QLabel("1行")
        header_layout.addWidget(row_length_label)
        self.row_length_combo = QComboBox()
        self.row_length_combo.setAccessibleName("フィルムレビューの1行の長さ")
        self.row_length_combo.setToolTip("1行に表示する時間の長さ")
        for label, seconds in (
            ("30秒", 30.0),
            ("1分", 60.0),
            ("2分", 120.0),
            ("5分", 300.0),
        ):
            self.row_length_combo.addItem(label, seconds)
        self.row_length_combo.setCurrentIndex(1)
        row_length_label.setBuddy(self.row_length_combo)
        header_layout.addWidget(self.row_length_combo)

        self.btn_back_to_editor = QPushButton("通常編集に戻る")
        self.btn_back_to_editor.setToolTip("通常編集へ戻り、現在位置を表示します")
        header_layout.addWidget(self.btn_back_to_editor)
        layout.addWidget(header)

        legend = QFrame()
        legend.setObjectName("filmstripLegend")
        legend_layout = QHBoxLayout(legend)
        legend_layout.setContentsMargins(10, 5, 10, 5)
        legend_layout.setSpacing(18)
        for symbol, text, color in (
            ("│", "分割位置", "#ffd05a"),
            ("┊", "未適用のカット候補", "#58b8df"),
            ("▨", "削除ゾーン", "#d8797e"),
            ("│", "現在位置", "#ff5d66"),
        ):
            item = QLabel(f"<span style='color:{color}; font-weight:700'>{symbol}</span> {text}")
            legend_layout.addWidget(item)
        legend_layout.addStretch()
        hint = QLabel("クリック: シーク　ダブルクリック: 通常編集")
        hint.setObjectName("filmstripHint")
        legend_layout.addWidget(hint)
        layout.addWidget(legend)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.canvas = FilmstripCanvas()
        self.scroll_area.setWidget(self.canvas)
        layout.addWidget(self.scroll_area, stretch=1)

        self.row_length_combo.currentIndexChanged.connect(self._on_row_length_changed)
        self.btn_back_to_editor.clicked.connect(lambda: self.edit_requested.emit(self.canvas.playhead_position))
        self.canvas.seek_requested.connect(self.seek_requested.emit)
        self.canvas.edit_requested.connect(self.edit_requested.emit)

    def set_job(self, job: Optional[VideoJob]):
        self.current_job = job
        self.canvas.set_job(job)
        self._update_summary()

    def refresh(self):
        self.canvas.refresh()
        self._update_summary()

    def update_thumbnail(self, scene_index: int, path: str):
        self.canvas.update_thumbnail(scene_index, path)

    def set_playhead(self, position: float):
        self.canvas.set_playhead(position)

    def set_candidate_times(self, candidates: list[float]):
        self.canvas.set_candidates(candidates)

    def _on_row_length_changed(self, _index: int):
        seconds = self.row_length_combo.currentData()
        if seconds is not None:
            self.canvas.set_seconds_per_row(float(seconds))

    def _update_summary(self):
        if self.current_job is None or not self.current_job.scenes:
            self.summary_label.setText("動画を選択してください")
            return
        scenes = self.current_job.scenes
        removed = sum(not scene.keep for scene in scenes)
        self.summary_label.setText(
            f"{len(scenes)}シーン・分割 {max(0, len(scenes) - 1)}か所・"
            f"削除 {removed}ゾーン"
        )
