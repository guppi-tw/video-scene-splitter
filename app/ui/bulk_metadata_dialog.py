"""複数動画へ同じ出力名・日付を明示的に反映する画面。"""

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from app.core.jobs import VideoJob
from app.core.metadata import BulkMetadataUpdate


_ROLE_JOB_ID = Qt.UserRole
_UNSET_DATE = QDate(1900, 1, 1)


class BulkMetadataDialog(QDialog):
    """対象と変更項目を同じ画面で確認してから反映する。"""

    def __init__(
        self,
        jobs: list[VideoJob],
        selected_job_id: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("複数動画の情報をまとめて設定")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "同じテープや行事の動画を選び、出力名と日付をまとめて設定します。"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        layout.addWidget(QLabel("対象動画"))
        self.job_list = QListWidget()
        self.job_list.setAccessibleName("一括設定する動画")
        self.job_list.setMinimumHeight(140)
        selected_job = None
        for job in jobs:
            item = QListWidgetItem(
                f"{job.filename}　({len(job.scenes)}クリップ)"
            )
            item.setData(_ROLE_JOB_ID, job.id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            checked = job.id == selected_job_id
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            self.job_list.addItem(item)
            if checked:
                selected_job = job
        layout.addWidget(self.job_list)

        name_row = QHBoxLayout()
        self.name_check = QCheckBox("出力名を変更")
        name_row.addWidget(self.name_check)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例: 1998年 運動会")
        self.name_edit.setText(selected_job.default_event_name if selected_job else "")
        self.name_edit.setEnabled(False)
        name_row.addWidget(self.name_edit, stretch=1)
        layout.addLayout(name_row)

        date_row = QHBoxLayout()
        self.date_check = QCheckBox("日付を変更")
        date_row.addWidget(self.date_check)
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setMinimumDate(_UNSET_DATE)
        self.date_edit.setSpecialValueText("未設定")
        if selected_job and selected_job.default_event_date:
            value = selected_job.default_event_date
            self.date_edit.setDate(QDate(value.year, value.month, value.day))
        else:
            self.date_edit.setDate(_UNSET_DATE)
        self.date_edit.setEnabled(False)
        date_row.addWidget(self.date_edit)
        date_row.addStretch()
        layout.addLayout(date_row)

        self.apply_to_scenes_check = QCheckBox("既存クリップにも反映")
        self.apply_to_scenes_check.setChecked(True)
        self.apply_to_scenes_check.setToolTip(
            "オフにすると動画の既定値だけを変更します"
        )
        layout.addWidget(self.apply_to_scenes_check)

        self.hint_label = QLabel("対象動画と変更する項目を選んでください")
        self.hint_label.setStyleSheet("color: #aaa;")
        layout.addWidget(self.hint_label)

        button_row = QHBoxLayout()
        button_row.addStretch()
        self.btn_cancel = QPushButton("キャンセル")
        self.btn_cancel.clicked.connect(self.reject)
        button_row.addWidget(self.btn_cancel)
        self.btn_apply = QPushButton("選択した動画へ反映")
        self.btn_apply.clicked.connect(self.accept)
        button_row.addWidget(self.btn_apply)
        layout.addLayout(button_row)

        self.job_list.itemChanged.connect(lambda _item: self._update_state())
        self.name_check.toggled.connect(self.name_edit.setEnabled)
        self.name_check.toggled.connect(lambda _checked: self._update_state())
        self.date_check.toggled.connect(self.date_edit.setEnabled)
        self.date_check.toggled.connect(lambda _checked: self._update_state())
        self._update_state()

    def selected_job_ids(self) -> list[int]:
        return [
            int(self.job_list.item(index).data(_ROLE_JOB_ID))
            for index in range(self.job_list.count())
            if self.job_list.item(index).checkState() == Qt.Checked
        ]

    def metadata_update(self) -> BulkMetadataUpdate:
        selected_date = self.date_edit.date()
        event_date = None
        if selected_date != _UNSET_DATE:
            event_date = date(
                selected_date.year(), selected_date.month(), selected_date.day()
            )
        return BulkMetadataUpdate(
            event_name=self.name_edit.text().strip(),
            event_date=event_date,
            set_event_name=self.name_check.isChecked(),
            set_event_date=self.date_check.isChecked(),
            apply_to_scenes=self.apply_to_scenes_check.isChecked(),
        )

    def _update_state(self):
        job_count = len(self.selected_job_ids())
        has_field = self.name_check.isChecked() or self.date_check.isChecked()
        enabled = job_count > 0 and has_field
        self.btn_apply.setEnabled(enabled)
        if not job_count:
            self.hint_label.setText("対象動画を1本以上選んでください")
        elif not has_field:
            self.hint_label.setText("変更する項目を選んでください")
        else:
            self.hint_label.setText(f"{job_count}本の動画へ反映します")
