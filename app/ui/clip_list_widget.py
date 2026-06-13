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

from app.core.jobs import VideoJob, Scene, Clip
from app.core.time_format import format_seconds


class ClickableLabel(QLabel):
    """クリックを通知するQLabel"""

    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ClipRow(QFrame):
    """クリップ1行分の表示"""

    keep_changed = Signal(int, bool)  # scene_index, keep
    sensitive_changed = Signal(int, bool)  # scene_index, is_sensitive
    filename_changed = Signal(int, str)  # scene_index, filename
    preview_requested = Signal(float)  # start_time
    selection_changed = Signal(int, bool)  # scene_index, selected

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

        # 結合対象の選択チェックボックス
        self.select_check = QCheckBox()
        self.select_check.setToolTip(
            "結合対象として選択\n連続するシーンを選んで「選択を結合」を押すと1つにまとまります"
        )
        self.select_check.stateChanged.connect(self._on_select_changed)
        layout.addWidget(self.select_check)

        # サムネイル
        self.thumb_label = ClickableLabel()
        self.thumb_label.setFixedSize(120, 68)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet("background-color: #333; border: 1px solid #555;")
        self.thumb_label.setCursor(Qt.PointingHandCursor)
        self.thumb_label.clicked.connect(
            lambda: self.preview_requested.emit(self.scene.start_time)
        )
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
        auto_name = self.job.get_clip_filename(Clip(
            index=self.scene.index,
            start_time=self.scene.start_time,
            end_time=self.scene.end_time,
            event_name=self.scene.event_name or self.job.default_event_name or '',
            event_date=self.scene.event_date or self.job.default_event_date,
        ))
        self.filename_edit.setPlaceholderText(auto_name)
        if self.scene.filename_override:
            self.filename_edit.setText(self.scene.filename_override)
        self.filename_edit.editingFinished.connect(self._on_filename_changed)
        info_layout.addWidget(self.filename_edit)

        layout.addLayout(info_layout, stretch=1)

        # Keep / 要注意 を縦に並べてコンパクトに
        check_layout = QVBoxLayout()
        check_layout.setSpacing(2)

        # Keep/Dropチェックボックス
        self.keep_check = QCheckBox("Keep")
        self.keep_check.setChecked(self.scene.keep)
        self.keep_check.stateChanged.connect(self._on_keep_changed)
        check_layout.addWidget(self.keep_check)

        # 要注意チェックボックス
        self.sensitive_check = QCheckBox("要注意")
        self.sensitive_check.setToolTip("クラウド共有前に確認したいクリップを別フォルダへ書き出します")
        self.sensitive_check.setChecked(self.scene.is_sensitive)
        self.sensitive_check.setEnabled(self.scene.keep)
        self.sensitive_check.stateChanged.connect(self._on_sensitive_changed)
        check_layout.addWidget(self.sensitive_check)

        layout.addLayout(check_layout)

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
        self.sensitive_check.setEnabled(keep)
        self.keep_changed.emit(self.scene.index, keep)

    def _on_sensitive_changed(self, state):
        is_sensitive = state == Qt.Checked.value
        self.scene.is_sensitive = is_sensitive
        self._update_style()
        self.sensitive_changed.emit(self.scene.index, is_sensitive)

    def _on_filename_changed(self):
        text = self.filename_edit.text().strip()
        self.scene.filename_override = text if text else None
        self.filename_changed.emit(self.scene.index, text)

    def _on_select_changed(self, state):
        self.selection_changed.emit(self.scene.index, state == Qt.Checked.value)

    def is_selected(self) -> bool:
        return self.select_check.isChecked()

    def _update_style(self):
        if self.scene.keep and self.scene.is_sensitive:
            self.setStyleSheet("ClipRow { background-color: #3a3320; }")
        elif self.scene.keep:
            self.setStyleSheet("ClipRow { background-color: #2a3a2a; }")
        else:
            self.setStyleSheet("ClipRow { background-color: #3a2a2a; }")

    @staticmethod
    def _format_time(seconds: float) -> str:
        return format_seconds(seconds)


class ClipListWidget(QWidget):
    """クリップ一覧 + メタデータ + 書き出しコントロール"""

    export_requested = Signal(object, object, bool)  # VideoJob, output_dir, auto_split
    clip_preview_requested = Signal(float)  # start_time
    merge_requested = Signal(list)  # 結合対象のシーン番号リスト（昇順・連続）
    short_merge_requested = Signal()  # 短いシーンの結合提案を手動で出す
    date_detect_requested = Signal()
    date_detect_cancel_requested = Signal()

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
        self.event_name_edit.setPlaceholderText("出力ファイル名（未指定なら元ファイル名）")
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

        # 結合バー
        merge_layout = QHBoxLayout()
        self.merge_hint_label = QLabel("チェックで結合対象を選択")
        self.merge_hint_label.setStyleSheet("color: #888; font-size: 10px;")
        merge_layout.addWidget(self.merge_hint_label)
        merge_layout.addStretch()

        self.btn_short_merge = QPushButton("短いシーンを結合")
        self.btn_short_merge.setToolTip("短いシーンをまとめる結合提案をもう一度出します")
        self.btn_short_merge.setEnabled(False)
        self.btn_short_merge.clicked.connect(self.short_merge_requested.emit)
        merge_layout.addWidget(self.btn_short_merge)

        self._date_detecting = False
        self.btn_date_detect = QPushButton("日付検出")
        self.btn_date_detect.setToolTip(
            "映像に焼き込まれた日付スタンプ（昔のビデオカメラの日付表示など）を\n"
            "OCRで読み取り、各クリップの日付に設定します"
        )
        self.btn_date_detect.setEnabled(False)
        self.btn_date_detect.clicked.connect(self._on_date_detect_clicked)
        merge_layout.addWidget(self.btn_date_detect)

        self.btn_merge = QPushButton("選択を結合")
        self.btn_merge.setToolTip("選択した連続するシーンを1つのクリップにまとめます")
        self.btn_merge.setEnabled(False)
        self.btn_merge.clicked.connect(self._on_merge)
        merge_layout.addWidget(self.btn_merge)

        layout.addLayout(merge_layout)

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

        # 前のジョブのメタデータ入力を引きずらないようリセット
        self.event_name_edit.blockSignals(True)
        self.date_edit.blockSignals(True)
        self.date_check.blockSignals(True)
        self.event_name_edit.setText(job.default_event_name or "")
        if job.default_event_date:
            d = job.default_event_date
            self.date_edit.setDate(QDate(d.year, d.month, d.day))
            self.date_check.setChecked(True)
        else:
            self.date_check.setChecked(False)
        self.event_name_edit.blockSignals(False)
        self.date_edit.blockSignals(False)
        self.date_check.blockSignals(False)

        if not self._date_detecting:
            self.btn_date_detect.setEnabled(True)
        self.btn_short_merge.setEnabled(True)
        self.refresh_clips()

    def clear(self):
        """クリップ一覧を空にする"""
        self.current_job = None
        self.btn_date_detect.setEnabled(False)
        self.btn_short_merge.setEnabled(False)
        for row in self._clip_rows:
            row.setParent(None)
            row.deleteLater()
        self._clip_rows.clear()
        self.event_name_edit.blockSignals(True)
        self.date_check.blockSignals(True)
        self.event_name_edit.clear()
        self.date_check.setChecked(False)
        self.event_name_edit.blockSignals(False)
        self.date_check.blockSignals(False)

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
            row.selection_changed.connect(self._on_selection_changed)
            self._clip_rows.append(row)
            self.scroll_layout.addWidget(row)

        self.scroll_layout.addStretch()
        self._sync_keep_all_check()
        self._update_merge_button()

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

    def _selected_scene_indexes(self) -> list[int]:
        """選択中のシーン番号を昇順で返す"""
        return sorted(
            row.scene.index for row in self._clip_rows if row.is_selected()
        )

    def _on_selection_changed(self, scene_index: int, selected: bool):
        """結合対象の選択が変更された"""
        self._update_merge_button()

    def _update_merge_button(self):
        """選択状態に応じて結合ボタンとヒントを更新"""
        selected = self._selected_scene_indexes()

        if not selected:
            self.merge_hint_label.setText("チェックで結合対象を選択")
            self.btn_merge.setEnabled(False)
            return

        contiguous = selected[-1] - selected[0] + 1 == len(selected)
        if len(selected) < 2:
            self.merge_hint_label.setText("1件選択中（2件以上で結合できます）")
            self.btn_merge.setEnabled(False)
        elif not contiguous:
            self.merge_hint_label.setText("連続するシーンのみ結合できます")
            self.btn_merge.setEnabled(False)
        else:
            self.merge_hint_label.setText(
                f"#{selected[0]}〜#{selected[-1]} の {len(selected)}件を結合"
            )
            self.btn_merge.setEnabled(True)

    def _on_merge(self):
        """選択シーンの結合をリクエスト"""
        selected = self._selected_scene_indexes()
        if len(selected) < 2:
            return
        if selected[-1] - selected[0] + 1 != len(selected):
            return
        self.merge_requested.emit(selected)

    def _on_date_detect_clicked(self):
        if self._date_detecting:
            self.date_detect_cancel_requested.emit()
        else:
            self.date_detect_requested.emit()

    def set_date_detecting(self, detecting: bool):
        """日付検出中の表示状態を切り替える（検出中はボタンが「中止」になる）"""
        self._date_detecting = detecting
        if detecting:
            self.btn_date_detect.setText("中止")
            self.btn_date_detect.setToolTip("日付検出を中止します")
            self.btn_date_detect.setEnabled(True)
        else:
            self.btn_date_detect.setText("日付検出")
            self.btn_date_detect.setToolTip(
                "映像に焼き込まれた日付スタンプ（昔のビデオカメラの日付表示など）を\n"
                "OCRで読み取り、各クリップの日付に設定します"
            )
            self.btn_date_detect.setEnabled(self.current_job is not None)

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
        sensitive_count = sum(1 for s in kept if s.is_sensitive)

        output_dir = QFileDialog.getExistingDirectory(self, "出力先フォルダを選択")
        if not output_dir:
            return

        reply = QMessageBox.question(
            self,
            "書き出し確認",
            f"Keepクリップ: {len(kept)}個\n"
            f"要注意クリップ: {sensitive_count}個\n"
            f"出力先: {output_dir}\n\n"
            f"要注意クリップは sensitive フォルダへ分けて出力されます。\n"
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
