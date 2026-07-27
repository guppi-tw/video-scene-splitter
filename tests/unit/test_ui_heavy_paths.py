"""
Regression tests for UI paths that can accidentally fan out heavy work.
"""
from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QDate, Qt
from PySide6.QtTest import QTest

from app.core.jobs import JobStatus, Scene, VideoJob
from app.ui.clip_list_widget import ClipListWidget
from app.ui.main_window import MainWindow
from app.ui.preview_widget import PreviewWidget
from app.ui.timeline_widget import TimelineWidget


def _app():
    return QApplication.instance() or QApplication([])


def test_timeline_replace_same_boundaries_does_not_emit():
    _app()
    widget = TimelineWidget()
    widget.set_scenes([0.0, 4.0], 10.0)
    emitted = []
    widget.boundaries_changed.connect(lambda boundaries: emitted.append(boundaries))

    widget.replace_boundaries([4.0, 0.0, 4.0])

    assert emitted == []
    widget.close()


def test_timeline_reset_is_disabled_while_detecting():
    _app()
    widget = TimelineWidget()
    widget.set_scenes([0.0, 4.0], 10.0)

    assert widget.btn_reset.isEnabled() is True
    widget.set_detecting(True)
    assert widget.btn_auto_detect.text() == "中止"
    assert widget.btn_reset.isEnabled() is False

    widget.set_detecting(False)
    assert widget.btn_reset.isEnabled() is True
    widget.close()


def test_clip_thumbnail_update_uses_scene_index_lookup(tmp_path):
    _app()
    video_path = tmp_path / "video.mp4"
    video_path.touch()
    job = VideoJob(
        id=1,
        source_path=video_path,
        status=JobStatus.REVIEW,
        scenes=[
            Scene(index=1, start_time=0.0, end_time=4.0),
            Scene(index=2, start_time=4.0, end_time=8.0),
        ],
    )
    widget = ClipListWidget()
    widget.set_job(job)
    target_row = widget._clip_rows_by_scene_index[2]
    calls = []

    class BadRow:
        @property
        def scene(self):
            raise AssertionError("update_thumbnail should not scan clip rows")

    widget._clip_rows = [BadRow()]
    target_row.set_thumbnail = lambda path: calls.append(path)

    widget.update_thumbnail(2, str(Path("thumb.jpg")))

    assert calls == ["thumb.jpg"]
    widget.close()


def test_apply_all_always_applies_selected_date_without_checkbox(tmp_path):
    _app()
    video_path = tmp_path / "video.mp4"
    video_path.touch()
    job = VideoJob(
        id=1,
        source_path=video_path,
        status=JobStatus.REVIEW,
        scenes=[
            Scene(index=1, start_time=0.0, end_time=4.0),
            Scene(index=2, start_time=4.0, end_time=8.0),
        ],
    )
    widget = ClipListWidget()
    widget.set_job(job)

    widget.event_name_edit.setText("旅行")
    widget.date_edit.setDate(QDate(2025, 2, 3))
    widget._on_apply_all()

    assert not hasattr(widget, "date_check")
    assert [scene.event_name for scene in job.scenes] == ["旅行", "旅行"]
    assert [scene.event_date for scene in job.scenes] == [
        date(2025, 2, 3),
        date(2025, 2, 3),
    ]
    widget.close()


def test_default_metadata_date_is_always_enabled(tmp_path):
    _app()
    video_path = tmp_path / "video.mp4"
    video_path.touch()
    job = VideoJob(
        id=1,
        source_path=video_path,
        status=JobStatus.REVIEW,
        scenes=[Scene(index=1, start_time=0.0, end_time=4.0)],
    )
    widget = ClipListWidget()
    widget.set_job(job)

    widget.date_edit.setDate(QDate(2025, 4, 5))
    widget._on_default_metadata_changed()

    assert job.default_event_date == date(2025, 4, 5)
    widget.close()


def test_default_metadata_date_shows_unset_when_model_has_no_date(tmp_path):
    """日付未設定を今日の日付に見せかけない"""
    _app()
    video_path = tmp_path / "video.mp4"
    video_path.touch()
    job = VideoJob(
        id=1,
        source_path=video_path,
        status=JobStatus.REVIEW,
        scenes=[Scene(index=1, start_time=0.0, end_time=4.0)],
    )
    widget = ClipListWidget()
    widget.set_job(job)

    assert widget.date_edit.text() == "未設定"
    assert widget.date_edit.optional_date() is None
    assert job.default_event_date is None

    widget.date_edit.setDate(QDate(2025, 4, 5))
    widget.btn_clear_date.click()
    QApplication.processEvents()

    assert widget.date_edit.text() == "未設定"
    assert job.default_event_date is None
    widget.close()


def test_clip_editor_controls_are_hidden_until_job_is_loaded(tmp_path):
    _app()
    widget = ClipListWidget()

    assert widget.meta_bar.isHidden() is True
    assert widget.action_bar.isHidden() is True
    assert widget.scroll_area.isHidden() is True

    video_path = tmp_path / "video.mp4"
    video_path.touch()
    job = VideoJob(
        id=1,
        source_path=video_path,
        status=JobStatus.REVIEW,
        scenes=[Scene(index=1, start_time=0.0, end_time=4.0)],
    )
    widget.set_job(job)

    assert widget.meta_bar.isHidden() is False
    assert widget.action_bar.isHidden() is False
    assert widget.scroll_area.isHidden() is False

    widget.clear()
    assert widget.meta_bar.isHidden() is True
    assert widget.action_bar.isHidden() is True
    assert widget.scroll_area.isHidden() is True
    widget.close()


def test_clip_actions_disable_irrelevant_controls_while_busy(tmp_path):
    _app()
    video_path = tmp_path / "video.mp4"
    video_path.touch()
    job = VideoJob(
        id=1,
        source_path=video_path,
        status=JobStatus.REVIEW,
        scenes=[
            Scene(index=1, start_time=0.0, end_time=4.0),
            Scene(index=2, start_time=4.0, end_time=8.0),
        ],
    )
    widget = ClipListWidget()
    widget.set_job(job)

    assert widget.btn_blank_detect.isEnabled() is True
    assert widget.btn_date_detect.isEnabled() is True
    assert widget.btn_short_merge.isEnabled() is True
    assert widget.btn_export.isEnabled() is True

    widget.set_blank_detecting(True)
    assert widget.btn_blank_detect.text() == "中止"
    assert widget.btn_blank_detect.isEnabled() is True
    assert widget.btn_date_detect.isEnabled() is False
    assert widget.btn_short_merge.isEnabled() is False
    assert widget.btn_export.isEnabled() is False
    assert all(not row.keep_check.isEnabled() for row in widget._clip_rows)
    assert all(not row.filename_edit.isEnabled() for row in widget._clip_rows)

    widget.set_blank_detecting(False)
    widget.set_date_detecting(True)
    assert widget.btn_date_detect.text() == "中止"
    assert widget.btn_date_detect.isEnabled() is True
    assert widget.btn_blank_detect.isEnabled() is False
    assert widget.btn_short_merge.isEnabled() is False
    assert widget.btn_export.isEnabled() is False

    widget.set_date_detecting(False)
    widget.set_exporting(True)
    assert widget.btn_blank_detect.isEnabled() is False
    assert widget.btn_date_detect.isEnabled() is False
    assert widget.btn_short_merge.isEnabled() is False
    assert widget.btn_export.isEnabled() is False

    widget.set_exporting(False)
    assert widget.btn_blank_detect.isEnabled() is True
    assert widget.btn_date_detect.isEnabled() is True
    assert widget.btn_short_merge.isEnabled() is True
    assert widget.btn_export.isEnabled() is True
    assert all(row.keep_check.isEnabled() for row in widget._clip_rows)
    widget.close()


def test_export_button_disables_when_no_clips_are_kept(tmp_path):
    _app()
    video_path = tmp_path / "video.mp4"
    video_path.touch()
    job = VideoJob(
        id=1,
        source_path=video_path,
        status=JobStatus.REVIEW,
        scenes=[Scene(index=1, start_time=0.0, end_time=4.0)],
    )
    widget = ClipListWidget()
    widget.set_job(job)

    assert widget.btn_export.isEnabled() is True
    job.scenes[0].keep = False
    widget.refresh_clips()
    assert widget.btn_export.isEnabled() is False
    widget.close()


def test_merge_disables_mixed_keep_or_sensitive_states(tmp_path):
    """結合で除外・要注意の意味が変わる組み合わせは許可しない"""
    _app()
    video_path = tmp_path / "video.mp4"
    video_path.touch()
    job = VideoJob(
        id=1,
        source_path=video_path,
        status=JobStatus.REVIEW,
        scenes=[
            Scene(index=1, start_time=0.0, end_time=4.0, keep=True),
            Scene(index=2, start_time=4.0, end_time=8.0, keep=False),
        ],
    )
    widget = ClipListWidget()
    widget.set_job(job)
    widget._clip_rows[0].select_check.setChecked(True)
    widget._clip_rows[1].select_check.setChecked(True)

    assert widget.btn_merge.isEnabled() is False
    assert "書き出し設定" in widget.merge_hint_label.text()

    job.scenes[1].keep = True
    job.scenes[1].is_sensitive = True
    widget.refresh_clips()
    widget._clip_rows[0].select_check.setChecked(True)
    widget._clip_rows[1].select_check.setChecked(True)

    assert widget.btn_merge.isEnabled() is False
    assert "書き出し設定" in widget.merge_hint_label.text()

    job.scenes[1].is_sensitive = False
    widget.refresh_clips()
    widget._clip_rows[0].select_check.setChecked(True)
    widget._clip_rows[1].select_check.setChecked(True)

    assert widget.btn_merge.isEnabled() is True
    widget.close()


def test_space_shortcut_does_not_override_focused_controls(tmp_path):
    """Space はチェックやボタンの標準操作を優先する"""
    _app()
    video_path = tmp_path / "video.mp4"
    video_path.touch()
    window = MainWindow()
    job = VideoJob(
        id=1,
        source_path=video_path,
        status=JobStatus.REVIEW,
        scenes=[Scene(index=1, start_time=0.0, end_time=4.0)],
    )
    window.current_job = job
    window.clip_list_widget.set_job(job)
    window.preview_widget.current_video_path = video_path
    play_calls = []
    window.preview_widget.toggle_play = lambda: play_calls.append("play")
    window.show()

    checkbox = window.clip_list_widget.keep_all_check
    checkbox.setFocus()
    before = checkbox.isChecked()
    QTest.keyClick(checkbox, Qt.Key_Space)
    QApplication.processEvents()

    assert checkbox.isChecked() is not before
    assert play_calls == []

    button = window.clip_list_widget.btn_apply_all
    clicks = []
    button.clicked.connect(lambda: clicks.append("click"))
    button.setFocus()
    QTest.keyClick(button, Qt.Key_Space)
    QApplication.processEvents()

    assert clicks == ["click"]
    assert play_calls == []
    window.close()


def test_arrow_shortcut_does_not_override_focused_slider():
    """左右キーはスライダーの標準操作を優先する"""
    _app()
    window = MainWindow()
    window.show()
    slider = window.preview_widget.volume_slider
    slider.setValue(70)
    slider.setFocus()

    QTest.keyClick(slider, Qt.Key_Right)
    QApplication.processEvents()

    assert slider.value() == 71
    window.close()


def test_media_controls_and_timeline_have_accessible_names():
    """アイコン操作とカスタムタイムラインに読み上げ可能な名前を付ける"""
    _app()
    preview = PreviewWidget()
    timeline = TimelineWidget()

    assert preview.btn_play.accessibleName()
    assert preview.btn_stop.accessibleName()
    assert preview.btn_volume.accessibleName()
    assert preview.btn_step_back.accessibleName()
    assert preview.btn_step_forward.accessibleName()
    assert timeline.timeline_bar.accessibleName()
    assert timeline.timeline_bar.focusPolicy() == Qt.StrongFocus

    preview.close()
    timeline.close()
