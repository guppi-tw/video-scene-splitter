"""
クリップ一覧ウィジェット - 手動編集用
"""
from datetime import date
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QScrollArea, QFrame, QDateEdit,
    QFileDialog, QMessageBox, QSizePolicy, QMenu, QStackedLayout, QComboBox
)
from PySide6.QtCore import Qt, Signal, QDate, QEvent
from PySide6.QtGui import QMouseEvent, QPixmap

from app.core.jobs import VideoJob, Scene, Clip, JobStatus
from app.core.export_presets import EXPORT_PRESETS, get_export_preset
from app.core.review import (
    DATE_REVIEW_CODES,
    acknowledge_review_issues,
    clear_date_review_acknowledgements,
    pending_review_count,
    pending_review_issues,
)
from app.core.time_format import format_seconds
from app.ui.style_helpers import set_recommended_action


class ClickableLabel(QLabel):
    """クリックを通知するQLabel"""

    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class OptionalDateEdit(QDateEdit):
    """未設定を明示できる日付入力"""

    UNSET_DATE = QDate(1900, 1, 1)

    def __init__(self):
        super().__init__()
        self.setMinimumDate(self.UNSET_DATE)
        self.setSpecialValueText("未設定")
        self.setDate(self.UNSET_DATE)
        self.setToolTip("既定の日付を選択します")
        self.setAccessibleName("既定の日付")

    def set_optional_date(self, value: Optional[date]):
        if value is None:
            self.setDate(self.UNSET_DATE)
        else:
            self.setDate(QDate(value.year, value.month, value.day))

    def optional_date(self) -> Optional[date]:
        selected = self.date()
        if selected == self.UNSET_DATE:
            return None
        return date(selected.year(), selected.month(), selected.day())

    def mousePressEvent(self, event: QMouseEvent):
        # 未設定からカレンダーを開くと1900年へ飛ばないよう今日を起点にする。
        if self.date() == self.UNSET_DATE:
            self.setDate(QDate.currentDate())
        super().mousePressEvent(event)


class ClipRow(QFrame):
    """クリップ1行分の表示"""

    keep_changed = Signal(int, bool)  # scene_index, keep
    sensitive_changed = Signal(int, bool)  # scene_index, is_sensitive
    filename_changed = Signal(int, str)  # scene_index, filename
    preview_requested = Signal(float)  # start_time
    selection_changed = Signal(int, bool)  # scene_index, selected
    review_acknowledged = Signal(int)  # scene_index
    date_changed = Signal(int, object)  # scene_index, date | None
    edit_started = Signal()

    def __init__(self, scene: Scene, job: VideoJob):
        super().__init__()
        self.scene = scene
        self.job = job
        self._pending_issues = pending_review_issues(job, scene)
        self._has_date_issue = any(
            issue.code in DATE_REVIEW_CODES
            for issue in self._pending_issues
        )
        self._editing_enabled = True
        self._finish_mode = True
        self.setFrameShape(QFrame.StyledPanel)
        self.setFixedHeight(
            112 if self._has_date_issue else (88 if self._pending_issues else 70)
        )
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(f"シーン {scene.index}")
        self._setup_ui()
        self._update_style()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(8)

        # 結合対象の選択チェックボックス
        self.select_check = QCheckBox()
        self.select_check.setAccessibleName(
            f"シーン {self.scene.index} を結合対象に選択"
        )
        self.select_check.setToolTip(
            "結合対象として選択\n連続するシーンを選んで「選択を結合」を押すと1つにまとまります"
        )
        self.select_check.stateChanged.connect(self._on_select_changed)
        self.select_check.hide()
        layout.addWidget(self.select_check)

        # サムネイル
        self.thumb_label = ClickableLabel()
        self.thumb_label.setFixedSize(88, 50)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet("background-color: #333; border: 1px solid #555;")
        self.thumb_label.setCursor(Qt.PointingHandCursor)
        self.thumb_label.setAccessibleName(
            f"シーン {self.scene.index} を先頭からプレビュー"
        )
        self.thumb_label.clicked.connect(
            lambda: self.preview_requested.emit(self.scene.start_time)
        )
        if self.scene.thumbnail_path and Path(self.scene.thumbnail_path).exists():
            self._set_thumbnail(self.scene.thumbnail_path)
        else:
            self.thumb_label.setText("画像なし")
        layout.addWidget(self.thumb_label)

        # 情報エリア
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        # クリップ番号 + 時間範囲 + 判定された日付
        time_text = (
            f"#{self.scene.index}  "
            f"{self._format_time(self.scene.start_time)}–"
            f"{self._format_time(self.scene.end_time)}"
        )
        self.time_label = QLabel(time_text)
        self.time_label.setStyleSheet("font-size: 11px; color: #ccc;")
        self.time_label.setMinimumWidth(80)
        self.time_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        info_layout.addWidget(self.time_label)

        # 生成名は通常テキスト表示。ダブルクリック時だけ入力欄へ切り替える。
        self.filename_container = QWidget()
        self.filename_stack = QStackedLayout(self.filename_container)
        self.filename_stack.setContentsMargins(0, 0, 0, 0)
        self.filename_edit = QLineEdit()
        self.filename_edit.setMinimumWidth(80)
        self.auto_name = self.job.get_clip_filename(Clip(
            index=self.scene.index,
            start_time=self.scene.start_time,
            end_time=self.scene.end_time,
            event_name=self.scene.event_name or self.job.default_event_name or '',
            event_date=self.scene.event_date or self.job.default_event_date,
        ))
        current_name = self.scene.filename_override or self.auto_name
        self.filename_label = QLabel(current_name)
        self.filename_label.setMinimumWidth(80)
        self.filename_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.filename_label.setStyleSheet(
            "QLabel { color: #b8b8b8; padding: 3px 4px; }"
            "QLabel:focus { border: 1px solid #4f9ddf; border-radius: 2px; }"
        )
        self.filename_label.setToolTip(
            f"{current_name}\nダブルクリックまたはF2でファイル名を変更"
        )
        self.filename_label.setAccessibleName(
            f"シーン {self.scene.index} の出力ファイル名"
        )
        self.filename_label.setFocusPolicy(Qt.StrongFocus)
        self.filename_label.installEventFilter(self)
        self.filename_edit.setText(current_name)
        self.filename_edit.setCursorPosition(0)
        self.filename_edit.setReadOnly(True)
        self.filename_edit.setToolTip(
            f"{self.scene.filename_override or self.auto_name}\n"
            "ダブルクリックまたはF2でファイル名を変更"
        )
        self.filename_edit.setAccessibleName(f"シーン {self.scene.index} の出力ファイル名")
        self.filename_edit.installEventFilter(self)
        self.filename_edit.editingFinished.connect(self._on_filename_changed)
        self.filename_stack.addWidget(self.filename_label)
        self.filename_stack.addWidget(self.filename_edit)
        self.filename_stack.setCurrentWidget(self.filename_label)
        info_layout.addWidget(self.filename_container)

        review_line = QHBoxLayout()
        review_line.setContentsMargins(0, 0, 0, 0)
        review_line.setSpacing(5)
        self.review_label = QLabel()
        self.review_label.setStyleSheet("font-size: 10px; color: #ffd27a;")
        self.review_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        if self._pending_issues:
            review_text = "・".join(issue.label for issue in self._pending_issues)
            self.review_label.setText(review_text)
            self.review_label.setToolTip(review_text)
        else:
            self.review_label.hide()
        review_line.addWidget(self.review_label, stretch=1)

        self.btn_edit_review_date = QPushButton("日付を修正")
        self.btn_edit_review_date.setToolTip(
            "映像の日付表示と照合し、このクリップの日付を修正します"
        )
        self.btn_edit_review_date.setAccessibleName(
            f"シーン {self.scene.index} の日付を修正"
        )
        self.btn_edit_review_date.setVisible(self._has_date_issue)
        self.btn_edit_review_date.clicked.connect(self._show_date_editor)
        info_layout.addLayout(review_line)

        self.date_editor_bar = QWidget()
        date_editor_layout = QHBoxLayout(self.date_editor_bar)
        date_editor_layout.setContentsMargins(0, 0, 0, 0)
        date_editor_layout.setSpacing(5)
        date_editor_layout.addWidget(QLabel("正しい日付"))
        self.review_date_edit = OptionalDateEdit()
        self.review_date_edit.setCalendarPopup(True)
        _name, effective_date = self.job.get_scene_metadata(self.scene.index)
        self.review_date_edit.set_optional_date(effective_date)
        self.review_date_edit.setAccessibleName(
            f"シーン {self.scene.index} の正しい日付"
        )
        self.review_date_edit.setToolTip("映像と照合した正しい日付を選択します")
        date_editor_layout.addWidget(self.review_date_edit)
        self.btn_apply_review_date = QPushButton("反映")
        self.btn_apply_review_date.clicked.connect(self._apply_review_date)
        date_editor_layout.addWidget(self.btn_apply_review_date)
        self.btn_cancel_review_date = QPushButton("閉じる")
        self.btn_cancel_review_date.clicked.connect(self._hide_date_editor)
        date_editor_layout.addWidget(self.btn_cancel_review_date)
        info_layout.addWidget(self.date_editor_bar)
        self.date_editor_bar.hide()

        layout.addLayout(info_layout, stretch=1)

        # 書き出し / 共有注意 を縦に並べてコンパクトに
        self.settings_widget = QWidget()
        check_layout = QVBoxLayout(self.settings_widget)
        check_layout.setContentsMargins(0, 0, 0, 0)
        check_layout.setSpacing(2)

        self.keep_check = QCheckBox("書き出す")
        self.keep_check.setMinimumWidth(72)
        self.keep_check.setChecked(self.scene.keep)
        self.keep_check.stateChanged.connect(self._on_keep_changed)
        check_layout.addWidget(self.keep_check)

        # クラウド共有時に注意が必要なクリップのチェックボックス
        self.sensitive_check = QCheckBox("共有注意")
        self.sensitive_check.setMinimumWidth(72)
        self.sensitive_check.setToolTip(
            "クラウド共有前に確認できるよう、専用フォルダへ分けて書き出します"
        )
        self.sensitive_check.setAccessibleName(
            "共有注意として専用フォルダへ分けて書き出す"
        )
        self.sensitive_check.setChecked(self.scene.is_sensitive)
        self.sensitive_check.setEnabled(self.scene.keep)
        self.sensitive_check.stateChanged.connect(self._on_sensitive_changed)
        check_layout.addWidget(self.sensitive_check)

        self.btn_review_done = QPushButton("確認済み")
        self.btn_review_done.setToolTip("表示中の確認事項を確認済みにします")
        self.btn_review_done.setAccessibleName(
            f"シーン {self.scene.index} の確認事項を確認済みにする"
        )
        self.btn_review_done.setVisible(bool(self._pending_issues))
        self.btn_review_done.clicked.connect(
            lambda: self.review_acknowledged.emit(self.scene.index)
        )
        check_layout.addWidget(self.btn_review_done)
        check_layout.addWidget(self.btn_edit_review_date)

        layout.addWidget(self.settings_widget)

    def _set_thumbnail(self, path):
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            self.thumb_label.setPixmap(
                pixmap.scaled(88, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

    def eventFilter(self, watched, event):
        activates_label = (
            event.type() == QEvent.MouseButtonDblClick
            or (
                event.type() == QEvent.KeyPress
                and event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_F2)
            )
        )
        if (
            watched is self.filename_label
            and activates_label
            and self._editing_enabled
            and self.scene.keep
        ):
            self._begin_filename_edit()
            return True
        return super().eventFilter(watched, event)

    def _begin_filename_edit(self):
        self.filename_edit.setReadOnly(False)
        self.filename_stack.setCurrentWidget(self.filename_edit)
        self.filename_edit.setFocus()
        self.filename_edit.selectAll()

    def set_thumbnail(self, path: str):
        self._set_thumbnail(path)

    def _on_keep_changed(self, state):
        keep = state == Qt.Checked.value
        if keep == self.scene.keep:
            return
        self.edit_started.emit()
        self.scene.keep = keep
        self._update_style()
        self.filename_edit.setEnabled(keep)
        self.filename_label.setEnabled(keep)
        self.sensitive_check.setEnabled(keep)
        self.keep_changed.emit(self.scene.index, keep)

    def _on_sensitive_changed(self, state):
        is_sensitive = state == Qt.Checked.value
        if is_sensitive == self.scene.is_sensitive:
            return
        self.edit_started.emit()
        self.scene.is_sensitive = is_sensitive
        self._update_style()
        self.sensitive_changed.emit(self.scene.index, is_sensitive)

    def _on_filename_changed(self):
        text = self.filename_edit.text().strip()
        override = text if text and text != self.auto_name else None
        if override == self.scene.filename_override:
            self.filename_edit.setText(override or self.auto_name)
            self.filename_edit.setCursorPosition(0)
            self.filename_edit.setReadOnly(True)
            self.filename_stack.setCurrentWidget(self.filename_label)
            return
        self.edit_started.emit()
        self.scene.filename_override = override
        self.filename_edit.setText(override or self.auto_name)
        self.filename_edit.setCursorPosition(0)
        self.filename_label.setText(override or self.auto_name)
        self.filename_label.setToolTip(
            f"{override or self.auto_name}\n"
            "ダブルクリックまたはF2でファイル名を変更"
        )
        self.filename_edit.setToolTip(
            f"{override or self.auto_name}\n"
            "ダブルクリックまたはF2でファイル名を変更"
        )
        self.filename_edit.setReadOnly(True)
        self.filename_changed.emit(self.scene.index, text)
        self.filename_stack.setCurrentWidget(self.filename_label)

    def _on_select_changed(self, state):
        self.selection_changed.emit(self.scene.index, state == Qt.Checked.value)

    def _show_date_editor(self):
        if not self._finish_mode:
            return
        _name, effective_date = self.job.get_scene_metadata(self.scene.index)
        self.review_date_edit.set_optional_date(effective_date)
        self.btn_edit_review_date.hide()
        self.date_editor_bar.show()
        self.setFixedHeight(140)
        self.review_date_edit.setFocus(Qt.OtherFocusReason)

    def _hide_date_editor(self):
        self.date_editor_bar.hide()
        self.btn_edit_review_date.setVisible(
            self._finish_mode and self._has_date_issue
        )
        self._sync_row_height()

    def _apply_review_date(self):
        selected_date = self.review_date_edit.optional_date()
        if (
            self.scene.event_date == selected_date
            and self.scene.date_source == ("manual" if selected_date else None)
        ):
            self._hide_date_editor()
            return
        self.edit_started.emit()
        self.scene.event_date = selected_date
        self.scene.date_source = "manual" if selected_date is not None else None
        clear_date_review_acknowledgements(self.scene)
        self.date_changed.emit(self.scene.index, selected_date)

    def is_selected(self) -> bool:
        return self.select_check.isChecked()

    def set_editing_enabled(self, enabled: bool):
        """処理中は行内の編集操作もまとめて無効にする"""
        self._editing_enabled = enabled
        self.select_check.setEnabled(enabled)
        self.keep_check.setEnabled(enabled)
        self.filename_edit.setEnabled(enabled and self.scene.keep)
        self.filename_label.setEnabled(enabled and self.scene.keep)
        self.filename_edit.setReadOnly(True)
        self.filename_stack.setCurrentWidget(self.filename_label)
        self.sensitive_check.setEnabled(enabled and self.scene.keep)
        self.btn_review_done.setEnabled(enabled)
        self.btn_edit_review_date.setEnabled(enabled)
        self.review_date_edit.setEnabled(enabled)
        self.btn_apply_review_date.setEnabled(enabled)
        self.btn_cancel_review_date.setEnabled(enabled)

    def set_finish_mode(self, enabled: bool):
        """分割中は、出力時にしか使わない行内設定を隠す。"""
        self._finish_mode = bool(enabled)
        self.filename_container.setVisible(self._finish_mode)
        self.review_label.setVisible(
            self._finish_mode and bool(self._pending_issues)
        )
        self.sensitive_check.setVisible(self._finish_mode)
        self.btn_review_done.setVisible(
            self._finish_mode and bool(self._pending_issues)
        )
        self.btn_edit_review_date.setVisible(
            self._finish_mode and self._has_date_issue
        )
        if not self._finish_mode:
            self.date_editor_bar.hide()
        self._sync_row_height()

    def _sync_row_height(self):
        if not self._finish_mode:
            self.setFixedHeight(62)
        elif not self.date_editor_bar.isHidden():
            self.setFixedHeight(140)
        else:
            self.setFixedHeight(
                112 if self._has_date_issue else (88 if self._pending_issues else 70)
            )

    def set_merge_mode(self, enabled: bool):
        self.select_check.setVisible(enabled)
        self.settings_widget.setVisible(not enabled)
        if not enabled:
            self.select_check.setChecked(False)

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

    export_requested = Signal(object, object, str)  # VideoJob, output_dir, preset_id
    export_cancel_requested = Signal()
    clip_preview_requested = Signal(float)  # start_time
    merge_requested = Signal(list)  # 結合対象のシーン番号リスト（昇順・連続）
    short_merge_requested = Signal()  # 短いシーンの結合提案を手動で出す
    blank_detect_requested = Signal()
    blank_detect_cancel_requested = Signal()
    date_detect_requested = Signal()
    date_detect_cancel_requested = Signal()
    media_signal_requested = Signal()
    media_signal_cancel_requested = Signal()
    edit_started = Signal()
    job_changed = Signal()

    def __init__(self):
        super().__init__()
        self.current_job: Optional[VideoJob] = None
        self._clip_rows: list[ClipRow] = []
        self._clip_rows_by_scene_index: dict[int, ClipRow] = {}
        self._exporting = False
        self._export_cancelling = False
        self._merge_mode = False
        self._finish_expanded = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # 分割中に必要な一覧だけを常設し、仕上げ設定は必要時に開く。
        self.workflow_bar = QFrame()
        self.workflow_bar.setObjectName("clipWorkflowBar")
        self.workflow_bar.setStyleSheet(
            "QFrame#clipWorkflowBar { background-color: #242424; "
            "border: 1px solid #3a3a3a; border-radius: 4px; }"
        )
        workflow_layout = QHBoxLayout(self.workflow_bar)
        workflow_layout.setContentsMargins(8, 5, 8, 5)
        workflow_layout.setSpacing(6)
        self.clip_summary_label = QLabel("クリップ")
        self.clip_summary_label.setStyleSheet("font-weight: bold;")
        workflow_layout.addWidget(self.clip_summary_label)
        workflow_layout.addStretch()
        self.finish_summary_label = QLabel()
        self.finish_summary_label.setStyleSheet("color: #ffd27a;")
        workflow_layout.addWidget(self.finish_summary_label)
        self.btn_toggle_finish = QPushButton("仕上げ・書き出し")
        self.btn_toggle_finish.setCheckable(True)
        self.btn_toggle_finish.setAccessibleName("仕上げと書き出しの設定を表示")
        self.btn_toggle_finish.setToolTip(
            "出力名、日付、補正、結合、確認、書き出しを表示します"
        )
        self.btn_toggle_finish.toggled.connect(self._set_finish_expanded)
        workflow_layout.addWidget(self.btn_toggle_finish)
        layout.addWidget(self.workflow_bar)

        self.finish_panel = QWidget()
        finish_layout = QVBoxLayout(self.finish_panel)
        finish_layout.setContentsMargins(0, 0, 0, 0)
        finish_layout.setSpacing(5)

        # メタデータバー
        self.meta_bar = QFrame()
        self.meta_bar.setObjectName("clipMetaBar")
        self.meta_bar.setStyleSheet(
            "QFrame#clipMetaBar { background-color: #242424; "
            "border: 1px solid #3a3a3a; border-radius: 4px; }"
        )
        meta_layout = QVBoxLayout(self.meta_bar)
        meta_layout.setContentsMargins(8, 5, 8, 5)
        meta_layout.setSpacing(4)

        name_layout = QHBoxLayout()
        name_layout.setSpacing(6)
        self.output_name_label = QLabel("出力名")
        name_layout.addWidget(self.output_name_label)
        self.event_name_edit = QLineEdit()
        self.event_name_edit.setMinimumWidth(90)
        self.event_name_edit.setPlaceholderText("未指定なら元の動画名")
        self.event_name_edit.setAccessibleName("出力名")
        self.event_name_edit.editingFinished.connect(self._on_default_metadata_changed)
        self.output_name_label.setBuddy(self.event_name_edit)
        name_layout.addWidget(self.event_name_edit, stretch=1)

        self.btn_apply_all = QPushButton("全クリップに上書き")
        self.btn_apply_all.setToolTip(
            "出力名と日付で、全クリップの個別設定を上書きします"
        )
        self.btn_apply_all.clicked.connect(self._on_apply_all)
        name_layout.addWidget(self.btn_apply_all)
        meta_layout.addLayout(name_layout)

        date_layout = QHBoxLayout()
        date_layout.setSpacing(6)
        self.date_label = QLabel("日付")
        date_layout.addWidget(self.date_label)
        self.date_edit = OptionalDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.dateChanged.connect(self._on_default_metadata_changed)
        self.date_edit.dateChanged.connect(self._sync_date_clear)
        self.date_label.setBuddy(self.date_edit)
        date_layout.addWidget(self.date_edit)
        self.btn_clear_date = QPushButton("クリア")
        self.btn_clear_date.setFixedWidth(52)
        self.btn_clear_date.setToolTip("日付をクリア")
        self.btn_clear_date.setAccessibleName("日付をクリア")
        self.btn_clear_date.clicked.connect(
            lambda: self.date_edit.set_optional_date(None)
        )
        date_layout.addWidget(self.btn_clear_date)
        date_layout.addStretch()
        meta_layout.addLayout(date_layout)

        finish_layout.addWidget(self.meta_bar)

        # 操作バー
        self.action_bar = QFrame()
        self.action_bar.setObjectName("clipActionBar")
        self.action_bar.setStyleSheet(
            "QFrame#clipActionBar { background-color: #202020; "
            "border: 1px solid #333; border-radius: 4px; }"
        )
        action_layout = QVBoxLayout(self.action_bar)
        action_layout.setContentsMargins(8, 5, 8, 5)
        action_layout.setSpacing(4)

        self._blank_detecting = False
        self.btn_postprocess = QPushButton("補正ツール")
        post_menu = QMenu(self.btn_postprocess)
        self.btn_blank_detect = post_menu.addAction("つなぎ目を検出")
        self.btn_blank_detect.setToolTip("単色（青/黒/白）のつなぎ目を検出して除外提案を出します")
        self.btn_blank_detect.setEnabled(False)
        self.btn_blank_detect.triggered.connect(self._on_blank_detect_clicked)

        self.btn_short_merge = post_menu.addAction("短いシーンの結合を提案")
        self.btn_short_merge.setToolTip(
            "短いシーンを自動で見つけ、まとめる候補を提案します"
        )
        self.btn_short_merge.setEnabled(False)
        self.btn_short_merge.triggered.connect(
            lambda _checked=False: self.short_merge_requested.emit()
        )

        self._signal_analyzing = False
        self.btn_signal_analyze = post_menu.addAction("音声・フェードを解析")
        self.btn_signal_analyze.setToolTip(
            "長い無音と映像のフェードを調べ、未適用の境界候補として表示します"
        )
        self.btn_signal_analyze.setEnabled(False)
        self.btn_signal_analyze.triggered.connect(self._on_signal_analyze_clicked)

        self._date_detecting = False
        self.btn_date_detect = post_menu.addAction("日付を検出")
        self.btn_date_detect.setToolTip(
            "映像に焼き込まれた日付スタンプ（昔のビデオカメラの日付表示など）を\n"
            "OCRで読み取り、各クリップの日付候補として確認事項へ追加します"
        )
        self.btn_date_detect.setEnabled(False)
        self.btn_date_detect.triggered.connect(self._on_date_detect_clicked)
        self.btn_postprocess.setMenu(post_menu)

        post_layout = QHBoxLayout()
        post_layout.setSpacing(6)
        post_layout.addWidget(self.btn_postprocess)
        self.btn_merge_mode = QPushButton("選択して結合")
        self.btn_merge_mode.setCheckable(True)
        self.btn_merge_mode.clicked.connect(self._toggle_merge_mode)
        post_layout.addWidget(self.btn_merge_mode)
        post_layout.addStretch()
        action_layout.addLayout(post_layout)

        self.merge_hint_label = QLabel("チェックで結合対象を選択")
        self.merge_hint_label.setStyleSheet("color: #aaa; font-size: 10px;")
        self.btn_merge = QPushButton("選択を結合")
        self.btn_merge.setToolTip("選択した連続するシーンを1つのクリップにまとめます")
        self.btn_merge.setEnabled(False)
        self.btn_merge.clicked.connect(self._on_merge)

        self.merge_bar = QFrame()
        merge_layout = QHBoxLayout(self.merge_bar)
        merge_layout.setContentsMargins(0, 0, 0, 0)
        merge_layout.setSpacing(6)
        merge_layout.addWidget(self.merge_hint_label, stretch=1)
        merge_layout.addWidget(self.btn_merge)
        action_layout.addWidget(self.merge_bar)
        self.merge_bar.hide()

        self.export_preset_combo = QComboBox()
        self.export_preset_combo.setAccessibleName("書き出し方法")
        for preset in EXPORT_PRESETS:
            self.export_preset_combo.addItem(preset.label, preset.id)
            index = self.export_preset_combo.count() - 1
            self.export_preset_combo.setItemData(index, preset.description, Qt.ToolTipRole)
        self.export_preset_combo.currentIndexChanged.connect(
            self._on_export_preset_changed
        )
        self._sync_export_preset_tooltip()

        self.keep_all_check = QCheckBox("全クリップを選択")
        self.keep_all_check.setChecked(True)
        self.keep_all_check.setToolTip("全クリップの書き出し対象を一括切り替え")
        self.keep_all_check.setAccessibleName(
            "全クリップを書き出し対象として一括選択"
        )
        self.keep_all_check.stateChanged.connect(self._on_keep_all_toggled)

        self.btn_export = QPushButton("書き出し")
        self.btn_export.clicked.connect(self._on_export)

        export_layout = QHBoxLayout()
        export_layout.setSpacing(6)
        self.export_method_label = QLabel("書き出し方法")
        self.export_method_label.setBuddy(self.export_preset_combo)
        export_layout.addWidget(self.export_method_label)
        export_layout.addWidget(self.export_preset_combo)
        export_layout.addStretch()
        export_layout.addWidget(self.btn_export)
        action_layout.addLayout(export_layout)

        finish_layout.addWidget(self.action_bar)

        self.review_bar = QFrame()
        self.review_bar.setObjectName("reviewBar")
        self.review_bar.setStyleSheet(
            "QFrame#reviewBar { background-color: #30291d; "
            "border: 1px solid #66522e; border-radius: 4px; }"
        )
        review_layout = QVBoxLayout(self.review_bar)
        review_layout.setContentsMargins(8, 5, 8, 5)
        review_layout.setSpacing(3)
        review_primary_layout = QHBoxLayout()
        review_primary_layout.setSpacing(6)
        self.review_summary_label = QLabel("確認事項なし")
        self.review_summary_label.setStyleSheet("font-weight: bold; color: #ffd27a;")
        review_primary_layout.addWidget(self.review_summary_label)
        review_primary_layout.addStretch()
        self.btn_next_review = QPushButton("次を確認")
        self.btn_next_review.setToolTip("次の未確認クリップへ移動します")
        self.btn_next_review.clicked.connect(self._on_next_review)
        review_primary_layout.addWidget(self.btn_next_review)
        review_layout.addLayout(review_primary_layout)

        review_filter_layout = QHBoxLayout()
        review_filter_layout.setSpacing(6)
        review_filter_layout.addWidget(self.keep_all_check)
        review_filter_layout.addStretch()
        self.review_only_check = QCheckBox("未確認のみ")
        self.review_only_check.setToolTip("確認が必要なクリップだけを表示します")
        self.review_only_check.toggled.connect(lambda _checked: self.refresh_clips())
        review_filter_layout.addWidget(self.review_only_check)
        review_layout.addLayout(review_filter_layout)
        finish_layout.insertWidget(0, self.review_bar)
        layout.addWidget(self.finish_panel)

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
        self._set_editor_visible(False)
        self._review_cursor = 0

    def _sync_date_clear(self, *_args):
        self.btn_clear_date.setVisible(self.date_edit.optional_date() is not None)

    def _set_editor_visible(self, visible: bool):
        self.workflow_bar.setVisible(visible)
        self.finish_panel.setVisible(visible and self._finish_expanded)
        self.scroll_area.setVisible(visible)

    def _set_finish_expanded(self, expanded: bool):
        expanded = bool(expanded and self.current_job is not None)
        if not expanded and self._merge_mode:
            self._toggle_merge_mode(False)
        self._finish_expanded = expanded
        self.btn_toggle_finish.blockSignals(True)
        self.btn_toggle_finish.setChecked(expanded)
        self.btn_toggle_finish.blockSignals(False)
        self.btn_toggle_finish.setText(
            "仕上げを閉じる" if expanded else "仕上げ・書き出し"
        )
        self.btn_toggle_finish.setAccessibleName(
            "仕上げと書き出しの設定を閉じる"
            if expanded
            else "仕上げと書き出しの設定を表示"
        )
        self.finish_panel.setVisible(expanded)
        for row in self._clip_rows:
            row.set_finish_mode(expanded)

    def _is_busy(self) -> bool:
        return (
            self._blank_detecting
            or self._date_detecting
            or self._signal_analyzing
            or self._exporting
        )

    def _has_editable_job(self) -> bool:
        return self.current_job is not None and bool(self.current_job.scenes)

    def _update_action_state(self):
        has_job = self._has_editable_job()
        busy = self._is_busy()
        kept = any(scene.keep for scene in self.current_job.scenes) if has_job else False
        scene_count = len(self.current_job.scenes) if has_job else 0
        review_count = pending_review_count(self.current_job) if has_job else 0

        self.event_name_edit.setEnabled(has_job and not busy)
        self.date_edit.setEnabled(has_job and not busy)
        self.btn_clear_date.setEnabled(has_job and not busy)
        self.btn_apply_all.setEnabled(has_job and not busy)
        self.export_preset_combo.setEnabled(has_job and not busy)
        self.keep_all_check.setEnabled(has_job and not busy)
        self.btn_merge_mode.setEnabled(has_job and scene_count > 1 and not busy)
        self.btn_postprocess.setEnabled(
            has_job
            and (
                not busy
                or self._blank_detecting
                or self._date_detecting
                or self._signal_analyzing
            )
        )
        if self._exporting:
            self.btn_export.setEnabled(not self._export_cancelling)
        else:
            self.btn_export.setEnabled(has_job and kept and not busy)
        set_recommended_action(
            self.btn_export,
            has_job
            and scene_count > 1
            and review_count == 0
            and kept
            and not busy
            and not self._merge_mode
            and self.current_job.status == JobStatus.REVIEW,
        )
        self.btn_next_review.setEnabled(review_count > 0 and not busy)
        set_recommended_action(
            self.btn_next_review,
            has_job
            and scene_count > 1
            and review_count > 0
            and not busy
            and not self._merge_mode,
        )
        self.btn_short_merge.setEnabled(has_job and scene_count > 1 and not busy)

        if self._blank_detecting:
            self.btn_blank_detect.setEnabled(True)
            self.btn_date_detect.setEnabled(False)
            self.btn_signal_analyze.setEnabled(False)
        elif self._date_detecting:
            self.btn_blank_detect.setEnabled(False)
            self.btn_date_detect.setEnabled(True)
            self.btn_signal_analyze.setEnabled(False)
        elif self._signal_analyzing:
            self.btn_blank_detect.setEnabled(False)
            self.btn_date_detect.setEnabled(False)
            self.btn_signal_analyze.setEnabled(True)
        else:
            self.btn_blank_detect.setEnabled(has_job and not busy)
            self.btn_date_detect.setEnabled(has_job and not busy)
            self.btn_signal_analyze.setEnabled(has_job and not busy)

        for row in self._clip_rows:
            row.set_editing_enabled(has_job and not busy)

        self._update_merge_button()

    def set_job(self, job: VideoJob):
        """ジョブを設定してクリップ一覧を構築"""
        keep_finish_open = self.current_job is job and self._finish_expanded
        self.current_job = job
        self._merge_mode = False
        self.btn_merge_mode.setChecked(False)
        self.btn_merge_mode.setText("選択して結合")
        self.merge_bar.hide()
        self._set_editor_visible(True)
        self._set_finish_expanded(keep_finish_open)

        # 前のジョブのメタデータ入力を引きずらないようリセット
        self.event_name_edit.blockSignals(True)
        self.date_edit.blockSignals(True)
        self.event_name_edit.setText(job.default_event_name or "")
        self.date_edit.set_optional_date(job.default_event_date)
        self.export_preset_combo.blockSignals(True)
        preset_index = self.export_preset_combo.findData(job.export_preset)
        if preset_index < 0:
            preset_index = self.export_preset_combo.findData(
                "share_fast" if job.auto_split_enabled else "archive_fast"
            )
        self.export_preset_combo.setCurrentIndex(max(0, preset_index))
        self.export_preset_combo.blockSignals(False)
        self._sync_export_preset_tooltip()
        self.event_name_edit.blockSignals(False)
        self.date_edit.blockSignals(False)
        self._sync_date_clear()

        self.refresh_clips()
        self._update_action_state()

    def clear(self):
        """クリップ一覧を空にする"""
        self.current_job = None
        self._exporting = False
        self._merge_mode = False
        self._finish_expanded = False
        self.btn_merge_mode.setChecked(False)
        self.merge_bar.hide()
        self._set_editor_visible(False)
        self._set_finish_expanded(False)
        for row in self._clip_rows:
            row.setParent(None)
            row.deleteLater()
        self._clip_rows.clear()
        self._clip_rows_by_scene_index.clear()
        self.event_name_edit.blockSignals(True)
        self.date_edit.blockSignals(True)
        self.event_name_edit.clear()
        self.date_edit.set_optional_date(None)
        self.event_name_edit.blockSignals(False)
        self.date_edit.blockSignals(False)
        self._sync_date_clear()
        self._review_cursor = 0
        self._update_action_state()

    def refresh_clips(self):
        """クリップ行を再構築"""
        if not self.current_job:
            return

        # 既存行をクリア
        for row in self._clip_rows:
            row.setParent(None)
            row.deleteLater()
        self._clip_rows.clear()
        self._clip_rows_by_scene_index.clear()

        # stretchを除去して再追加
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        # クリップ行を作成。絞り込みは表示だけに作用し、データは変更しない。
        scenes = self.current_job.scenes
        if self.review_only_check.isChecked():
            scenes = [
                scene for scene in scenes
                if pending_review_issues(self.current_job, scene)
            ]
        for scene in scenes:
            row = ClipRow(scene, self.current_job)
            row.preview_requested.connect(self.clip_preview_requested.emit)
            row.edit_started.connect(self.edit_started.emit)
            row.keep_changed.connect(self._on_individual_keep_changed)
            row.sensitive_changed.connect(self._on_individual_setting_changed)
            row.filename_changed.connect(self._on_individual_setting_changed)
            row.date_changed.connect(self._on_individual_date_changed)
            row.selection_changed.connect(self._on_selection_changed)
            row.review_acknowledged.connect(self._on_review_acknowledged)
            row.set_merge_mode(self._merge_mode)
            row.set_finish_mode(self._finish_expanded)
            self._clip_rows.append(row)
            self._clip_rows_by_scene_index[scene.index] = row
            self.scroll_layout.addWidget(row)

        self.scroll_layout.addStretch()
        self._sync_keep_all_check()
        self._refresh_review_state()
        self._update_action_state()

    def _refresh_review_state(self):
        if not self.current_job:
            self.review_summary_label.setText("確認事項なし")
            self.clip_summary_label.setText("クリップ")
            self.finish_summary_label.clear()
            self.btn_next_review.setEnabled(False)
            self.review_only_check.setEnabled(False)
            return
        count = pending_review_count(self.current_job)
        removed = sum(not scene.keep for scene in self.current_job.scenes)
        summary = f"クリップ {len(self.current_job.scenes)}"
        if removed:
            summary += f"・削除 {removed}"
        self.clip_summary_label.setText(summary)
        self.finish_summary_label.setText(f"確認 {count}" if count else "")
        self.review_summary_label.setText(
            f"確認事項 {count}件" if count else "確認事項なし"
        )
        self.review_only_check.setEnabled(count > 0 or self.review_only_check.isChecked())

    def _on_next_review(self):
        if not self.current_job:
            return
        pending = [
            scene for scene in self.current_job.scenes
            if pending_review_issues(self.current_job, scene)
        ]
        if not pending:
            return
        scene = pending[self._review_cursor % len(pending)]
        self._review_cursor += 1
        row = self._clip_rows_by_scene_index.get(scene.index)
        if row:
            self.scroll_area.ensureWidgetVisible(row, 0, 12)
            row.setFocus(Qt.OtherFocusReason)
        self.clip_preview_requested.emit(scene.start_time)

    def _on_review_acknowledged(self, scene_index: int):
        if not self.current_job:
            return
        scene = next(
            (scene for scene in self.current_job.scenes if scene.index == scene_index),
            None,
        )
        if scene is None or not pending_review_issues(self.current_job, scene):
            return
        self.edit_started.emit()
        acknowledge_review_issues(self.current_job, scene)
        self.refresh_clips()
        self.job_changed.emit()

    def _toggle_merge_mode(self, enabled: bool):
        self._merge_mode = enabled
        self.btn_merge_mode.setText("結合を終了" if enabled else "選択して結合")
        self.merge_bar.setVisible(enabled)
        for row in self._clip_rows:
            row.set_merge_mode(enabled)
        self._update_action_state()

    def update_thumbnail(self, scene_index: int, path: str):
        """特定クリップのサムネイルを更新"""
        row = self._clip_rows_by_scene_index.get(scene_index)
        if row:
            row.set_thumbnail(path)

    def _on_default_metadata_changed(self):
        """デフォルトメタデータが変更された"""
        if not self.current_job:
            return
        name = self.event_name_edit.text().strip()
        event_date = self.date_edit.optional_date()
        if (
            name == self.current_job.default_event_name
            and event_date == self.current_job.default_event_date
        ):
            return
        self.edit_started.emit()
        date_changed = event_date != self.current_job.default_event_date
        self.current_job.default_event_name = name
        self.current_job.default_event_date = event_date
        if date_changed:
            for scene in self.current_job.scenes:
                clear_date_review_acknowledgements(scene)
        self.refresh_clips()
        self.job_changed.emit()

    def _on_apply_all(self):
        """メタデータを全クリップに適用"""
        if not self.current_job:
            return

        name = self.event_name_edit.text().strip() or None
        event_date = self.date_edit.optional_date()
        if all(
            scene.event_name == name and scene.event_date == event_date
            for scene in self.current_job.scenes
        ):
            return
        self.edit_started.emit()

        for scene in self.current_job.scenes:
            scene.event_name = name
            scene.event_date = event_date
            scene.date_source = "manual" if event_date is not None else None
            clear_date_review_acknowledgements(scene)

        self.refresh_clips()
        self._update_action_state()
        self.job_changed.emit()

    def _on_individual_keep_changed(self, scene_index: int, keep: bool):
        """個別クリップのKeep変更時に全体チェックボックスを同期"""
        self._sync_keep_all_check()
        self._update_action_state()
        self.job_changed.emit()

    def _on_individual_setting_changed(self, *_args):
        self._update_action_state()
        self.job_changed.emit()

    def _on_individual_date_changed(self, *_args):
        self.refresh_clips()
        self.job_changed.emit()

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
        set_recommended_action(self.btn_merge, False)

        if not selected:
            self.merge_hint_label.setText("チェックで結合対象を選択")
            self.btn_merge.setEnabled(False)
            return

        if self._is_busy():
            self.merge_hint_label.setText("検出中は結合できません")
            self.btn_merge.setEnabled(False)
            return

        contiguous = selected[-1] - selected[0] + 1 == len(selected)
        if len(selected) < 2:
            self.merge_hint_label.setText("1件選択中（2件以上で結合できます）")
            self.btn_merge.setEnabled(False)
        elif not contiguous:
            self.merge_hint_label.setText("連続するシーンのみ結合できます")
            self.btn_merge.setEnabled(False)
        elif not self._selected_scenes_are_merge_compatible(selected):
            self.merge_hint_label.setText("書き出し設定が異なるシーンは結合できません")
            self.btn_merge.setEnabled(False)
        else:
            self.merge_hint_label.setText(
                f"#{selected[0]}〜#{selected[-1]} の {len(selected)}件を結合"
            )
            self.btn_merge.setEnabled(True)
            set_recommended_action(self.btn_merge, self._merge_mode)

    def _selected_scenes_are_merge_compatible(self, indexes: list[int]) -> bool:
        """結合で公開可否や出力メタデータが暗黙に変わらないか確認する"""
        if not self.current_job:
            return False
        scenes_by_index = {scene.index: scene for scene in self.current_job.scenes}
        keys = set()
        for index in indexes:
            scene = scenes_by_index.get(index)
            if scene is None:
                return False
            event_name, event_date = self.current_job.get_scene_metadata(index)
            keys.add(
                (
                    scene.keep,
                    scene.is_sensitive,
                    event_name,
                    event_date,
                    scene.filename_override,
                )
            )
        return len(keys) == 1

    def _on_merge(self):
        """選択シーンの結合をリクエスト"""
        selected = self._selected_scene_indexes()
        if len(selected) < 2:
            return
        if selected[-1] - selected[0] + 1 != len(selected):
            return
        if not self._selected_scenes_are_merge_compatible(selected):
            return
        self.merge_requested.emit(selected)
        self.btn_merge_mode.setChecked(False)
        self._toggle_merge_mode(False)

    def _on_blank_detect_clicked(self):
        if self._blank_detecting:
            self.blank_detect_cancel_requested.emit()
        else:
            self.blank_detect_requested.emit()

    def set_blank_detecting(self, detecting: bool):
        """つなぎ目検出中の表示状態を切り替える（検出中はボタンが「中止」になる）"""
        self._blank_detecting = detecting
        if detecting:
            self.btn_blank_detect.setText("つなぎ目検出を中止")
            self.btn_blank_detect.setToolTip("つなぎ目検出を中止します")
        else:
            self.btn_blank_detect.setText("つなぎ目を検出")
            self.btn_blank_detect.setToolTip(
                "単色（青/黒/白）のつなぎ目を検出して除外提案を出します"
            )
        self._update_action_state()

    def _on_date_detect_clicked(self):
        if self._date_detecting:
            self.date_detect_cancel_requested.emit()
        else:
            self.date_detect_requested.emit()

    def set_date_detecting(self, detecting: bool):
        """日付検出中の表示状態を切り替える（検出中はボタンが「中止」になる）"""
        self._date_detecting = detecting
        if detecting:
            self.btn_date_detect.setText("日付検出を中止")
            self.btn_date_detect.setToolTip("日付検出を中止します")
        else:
            self.btn_date_detect.setText("日付を検出")
            self.btn_date_detect.setToolTip(
                "映像に焼き込まれた日付スタンプ（昔のビデオカメラの日付表示など）を\n"
                "OCRで読み取り、各クリップの日付候補として確認事項へ追加します"
            )
        self._update_action_state()

    def _on_signal_analyze_clicked(self):
        if self._signal_analyzing:
            self.media_signal_cancel_requested.emit()
        else:
            self.media_signal_requested.emit()

    def set_media_signal_analyzing(self, analyzing: bool):
        self._signal_analyzing = analyzing
        if analyzing:
            self.btn_signal_analyze.setText("音声・フェード解析を中止")
            self.btn_signal_analyze.setToolTip("音声・フェード解析を中止します")
        else:
            self.btn_signal_analyze.setText("音声・フェードを解析")
            self.btn_signal_analyze.setToolTip(
                "長い無音と映像のフェードを調べ、未適用の境界候補として表示します"
            )
        self._update_action_state()

    def set_exporting(self, exporting: bool):
        """書き出し中は編集・後処理系の操作を止める"""
        self._exporting = exporting
        self._export_cancelling = False
        if exporting:
            self._set_finish_expanded(True)
        self.btn_export.setText("書き出しを中止" if exporting else "書き出し")
        self._update_action_state()

    def set_export_cancelling(self):
        self._export_cancelling = True
        self.btn_export.setText("中止しています…")
        self._update_action_state()

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
        if all(scene.keep == keep for scene in self.current_job.scenes):
            return
        self.edit_started.emit()
        for scene in self.current_job.scenes:
            scene.keep = keep
        self.refresh_clips()
        self._update_action_state()
        self.job_changed.emit()

    def _sync_export_preset_tooltip(self):
        preset = get_export_preset(self.export_preset_combo.currentData())
        self.export_preset_combo.setToolTip(preset.description)

    def _on_export_preset_changed(self, _index: int):
        if not self.current_job:
            self._sync_export_preset_tooltip()
            return
        preset = get_export_preset(self.export_preset_combo.currentData())
        self._sync_export_preset_tooltip()
        if (
            self.current_job.export_preset == preset.id
            and self.current_job.auto_split_enabled == preset.auto_split
        ):
            return
        self.edit_started.emit()
        self.current_job.export_preset = preset.id
        self.current_job.auto_split_enabled = preset.auto_split
        self.job_changed.emit()

    def _on_export(self):
        """書き出し"""
        if self._exporting:
            self.export_cancel_requested.emit()
            return
        if not self.current_job:
            return

        kept = [s for s in self.current_job.scenes if s.keep]
        if not kept:
            QMessageBox.warning(self, "警告", "書き出し対象のクリップがありません")
            return
        sensitive_count = sum(1 for s in kept if s.is_sensitive)
        preset = get_export_preset(self.export_preset_combo.currentData())

        output_dir = QFileDialog.getExistingDirectory(self, "出力先フォルダを選択")
        if not output_dir:
            return

        reply = QMessageBox.question(
            self,
            "書き出し確認",
            f"書き出し対象: {len(kept)}個\n"
            f"共有注意として分ける: {sensitive_count}個\n"
            f"書き出し方法: {preset.label}\n"
            f"出力先: {output_dir}\n\n"
            f"共有注意クリップは専用フォルダへ分けて出力されます。\n"
            f"書き出しを開始しますか？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.current_job.output_dir = Path(output_dir)
            self.export_requested.emit(
                self.current_job,
                Path(output_dir),
                preset.id,
            )
