"""
クリップ一覧ウィジェット - 手動編集用
"""
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QScrollArea, QFrame, QDateEdit,
    QFileDialog, QMessageBox, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QDate
from PySide6.QtGui import QPixmap

from app.core.jobs import VideoJob, Scene


class ClipRow(QFrame):
    """クリップ1行分の表示"""

    keep_changed = Signal(int, bool)  # scene_index, keep
    filename_changed = Signal(int, str)  # scene_index, filename
    preview_requested = Signal(float)  # start_time

    def __init__(self, scene: Scene, job: VideoJob):
        super().__init__()
        self.scene = scene
        self.job = job
        self.setFrameShape(QFrame.StyledPanel)
        self.setFixedHeight(80)
        self._setup_ui()
        self._update_style()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(8)

        # サムネイル
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(120, 68)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet("background-color: #333; border: 1px solid #555;")
        self.thumb_label.setCursor(Qt.PointingHandCursor)
        self.thumb_label.mousePressEvent = lambda e: self.preview_requested.emit(self.scene.start_time)
        if self.scene.thumbnail_path and Path(self.scene.thumbnail_path).exists():
            self._set_thumbnail(self.scene.thumbnail_path)
        else:
            self.thumb_label.setText("No Image")
        layout.addWidget(self.thumb_label)

        # 情報エリア
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        # クリップ番号 + 時間範囲
        time_text = (
            f"#{self.scene.index}  "
            f"{self._format_time(self.scene.start_time)} - "
            f"{self._format_time(self.scene.end_time)}  "
            f"({self._format_time(self.scene.duration)})"
        )
        self.time_label = QLabel(time_text)
        self.time_label.setStyleSheet("font-size: 11px; color: #ccc;")
        info_layout.addWidget(self.time_label)

        # ファイル名入力
        self.filename_edit = QLineEdit()
        auto_name = self.job.get_clip_filename(
            type('_', (), {
                'filename_override': None,
                'event_name': self.scene.event_name or self.job.default_event_name or '',
                'event_date': self.scene.event_date or self.job.default_event_date,
                'index': self.scene.index
            })()
        )
        self.filename_edit.setPlaceholderText(auto_name)
        if self.scene.filename_override:
            self.filename_edit.setText(self.scene.filename_override)
        self.filename_edit.editingFinished.connect(self._on_filename_changed)
        info_layout.addWidget(self.filename_edit)

        layout.addLayout(info_layout, stretch=1)

        # Keep/Dropチェックボックス
        self.keep_check = QCheckBox("Keep")
        self.keep_check.setChecked(self.scene.keep)
        self.keep_check.stateChanged.connect(self._on_keep_changed)
        layout.addWidget(self.keep_check)

    def _set_thumbnail(self, path):
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            self.thumb_label.setPixmap(
                pixmap.scaled(120, 68, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

    def set_thumbnail(self, path: str):
        self._set_thumbnail(path)

    def _on_keep_changed(self, state):
        keep = state == Qt.Checked.value
        self.scene.keep = keep
        self._update_style()
        self.filename_edit.setEnabled(keep)
        self.keep_changed.emit(self.scene.index, keep)

    def _on_filename_changed(self):
        text = self.filename_edit.text().strip()
        self.scene.filename_override = text if text else None
        self.filename_changed.emit(self.scene.index, text)

    def _update_style(self):
        if self.scene.keep:
            self.setStyleSheet("ClipRow { background-color: #2a3a2a; }")
        else:
            self.setStyleSheet("ClipRow { background-color: #3a2a2a; }")

    @staticmethod
    def _format_time(seconds: float) -> str:
        total_sec = int(seconds)
        m, s = divmod(total_sec, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"


class ClipListWidget(QWidget):
    """クリップ一覧 + メタデータ + 書き出しコントロール"""

    export_requested = Signal(object, object, bool)  # VideoJob, output_dir, auto_split
    clip_preview_requested = Signal(float)  # start_time

    def __init__(self):
        super().__init__()
        self.current_job: Optional[VideoJob] = None
        self._clip_rows: list[ClipRow] = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # メタデータバー
        meta_layout = QHBoxLayout()

        meta_layout.addWidget(QLabel("ファイル名:"))
        self.event_name_edit = QLineEdit()
        self.event_name_edit.setPlaceholderText("出力ファイルのベース名")
        self.event_name_edit.editingFinished.connect(self._on_default_metadata_changed)
        meta_layout.addWidget(self.event_name_edit, stretch=1)

        meta_layout.addWidget(QLabel("日付:"))
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        self.date_check = QCheckBox()
        self.date_check.setChecked(False)
        self.date_check.setToolTip("日付を有効化")
        self.date_check.stateChanged.connect(self._on_default_metadata_changed)
        self.date_edit.dateChanged.connect(self._on_default_metadata_changed)
        meta_layout.addWidget(self.date_check)
        meta_layout.addWidget(self.date_edit)

        self.btn_apply_all = QPushButton("全体に適用")
        self.btn_apply_all.setToolTip("ファイル名と日付を全クリップに適用")
        self.btn_apply_all.clicked.connect(self._on_apply_all)
        meta_layout.addWidget(self.btn_apply_all)

        layout.addLayout(meta_layout)

        # スクロール可能なクリップリスト
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setSpacing(3)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.addStretch()

        self.scroll_area.setWidget(self.scroll_content)
        layout.addWidget(self.scroll_area, stretch=1)

        # 下部: エクスポートコントロール
        export_layout = QHBoxLayout()

        self.auto_split_check = QCheckBox("9:55で自動分割")
        self.auto_split_check.setChecked(True)
        self.auto_split_check.setToolTip("595秒超のクリップを自動分割")
        export_layout.addWidget(self.auto_split_check)

        export_layout.addStretch()

        self.keep_all_check = QCheckBox("全てKeep")
        self.keep_all_check.setChecked(True)
        self.keep_all_check.setToolTip("全クリップの Keep/Drop を一括切り替え")
        self.keep_all_check.stateChanged.connect(self._on_keep_all_toggled)
        export_layout.addWidget(self.keep_all_check)

        self.btn_export = QPushButton("書き出し")
        self.btn_export.setObjectName("btn_export")
        self.btn_export.clicked.connect(self._on_export)
        export_layout.addWidget(self.btn_export)

        layout.addLayout(export_layout)

    def set_job(self, job: VideoJob):
        """ジョブを設定してクリップ一覧を構築"""
        self.current_job = job
        if job.default_event_name:
            self.event_name_edit.setText(job.default_event_name)
        self.refresh_clips()

    def refresh_clips(self):
        """クリップ行を再構築"""
        if not self.current_job:
            return

        # 既存行をクリア
        for row in self._clip_rows:
            row.setParent(None)
            row.deleteLater()
        self._clip_rows.clear()

        # stretchを除去して再追加
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        # クリップ行を作成
        for scene in self.current_job.scenes:
            row = ClipRow(scene, self.current_job)
            row.preview_requested.connect(self.clip_preview_requested.emit)
            row.keep_changed.connect(self._on_individual_keep_changed)
            self._clip_rows.append(row)
            self.scroll_layout.addWidget(row)

        self.scroll_layout.addStretch()
        self._sync_keep_all_check()

    def update_thumbnail(self, scene_index: int, path: str):
        """特定クリップのサムネイルを更新"""
        for row in self._clip_rows:
            if row.scene.index == scene_index:
                row.set_thumbnail(path)
                break

    def _on_default_metadata_changed(self):
        """デフォルトメタデータが変更された"""
        if not self.current_job:
            return
        self.current_job.default_event_name = self.event_name_edit.text().strip()
        if self.date_check.isChecked():
            from datetime import date
            qdate = self.date_edit.date()
            self.current_job.default_event_date = date(qdate.year(), qdate.month(), qdate.day())
        else:
            self.current_job.default_event_date = None

    def _on_apply_all(self):
        """メタデータを全クリップに適用"""
        if not self.current_job:
            return

        name = self.event_name_edit.text().strip() or None
        event_date = None
        if self.date_check.isChecked():
            from datetime import date
            qdate = self.date_edit.date()
            event_date = date(qdate.year(), qdate.month(), qdate.day())

        for scene in self.current_job.scenes:
            scene.event_name = name
            scene.event_date = event_date

        self.refresh_clips()

    def _on_individual_keep_changed(self, scene_index: int, keep: bool):
        """個別クリップのKeep変更時に全体チェックボックスを同期"""
        self._sync_keep_all_check()

    def _sync_keep_all_check(self):
        """全クリップのKeep状態に応じてチェックボックスを更新"""
        if not self.current_job or not self.current_job.scenes:
            return
        # シグナルをブロックして無限ループ防止
        self.keep_all_check.blockSignals(True)
        all_kept = all(s.keep for s in self.current_job.scenes)
        self.keep_all_check.setChecked(all_kept)
        self.keep_all_check.blockSignals(False)

    def _on_keep_all_toggled(self, state):
        if not self.current_job:
            return
        keep = state == Qt.Checked.value
        for scene in self.current_job.scenes:
            scene.keep = keep
        self.refresh_clips()

    def _on_export(self):
        """書き出し"""
        if not self.current_job:
            return

        kept = [s for s in self.current_job.scenes if s.keep]
        if not kept:
            QMessageBox.warning(self, "警告", "Keep対象のクリップがありません")
            return

        output_dir = QFileDialog.getExistingDirectory(self, "出力先フォルダを選択")
        if not output_dir:
            return

        reply = QMessageBox.question(
            self,
            "書き出し確認",
            f"Keepクリップ: {len(kept)}個\n"
            f"出力先: {output_dir}\n\n"
            f"書き出しを開始しますか？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.current_job.output_dir = Path(output_dir)
            self.export_requested.emit(
                self.current_job,
                Path(output_dir),
                self.auto_split_check.isChecked()
            )
