from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication

from app.core.jobs import VideoJob
from app.ui.bulk_metadata_dialog import BulkMetadataDialog


def _app():
    return QApplication.instance() or QApplication([])


def test_bulk_metadata_dialog_requires_explicit_fields_and_job_selection():
    _app()
    jobs = [
        VideoJob(id=1, source_path=Path("tape-1.mp4")),
        VideoJob(id=2, source_path=Path("tape-2.mp4")),
    ]
    dialog = BulkMetadataDialog(jobs, selected_job_id=1)

    assert dialog.selected_job_ids() == [1]
    assert dialog.btn_apply.isEnabled() is False

    dialog.job_list.item(1).setCheckState(Qt.Checked)
    dialog.name_check.setChecked(True)
    dialog.name_edit.setText("運動会")
    dialog.date_check.setChecked(True)
    dialog.date_edit.setDate(QDate(1998, 10, 10))

    update = dialog.metadata_update()
    assert dialog.selected_job_ids() == [1, 2]
    assert dialog.btn_apply.isEnabled() is True
    assert update.event_name == "運動会"
    assert update.event_date == date(1998, 10, 10)
    assert update.apply_to_scenes is True
    dialog.close()
