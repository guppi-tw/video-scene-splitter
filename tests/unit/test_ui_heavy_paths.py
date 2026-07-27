"""
Regression tests for UI paths that can accidentally fan out heavy work.
"""
from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QApplication, QFileDialog
from PySide6.QtCore import QDate, Qt
from PySide6.QtTest import QTest

from app.core.jobs import JobQueue, JobStatus, Scene, VideoJob
from app.core.session_store import SessionStore
from app.ui.clip_list_widget import ClipListWidget
from app.ui.main_window import MainWindow
from app.ui.preview_widget import PreviewWidget
from app.ui.timeline_widget import TimelineWidget
from app.ui.workers import ExportWorker
from app.ui.merge_dialog import MergeProposalDialog
from app.ui.blank_dialog import BlankCutDialog


def _app():
    return QApplication.instance() or QApplication([])


def test_adding_video_autosaves_and_next_window_restores_queue(monkeypatch, tmp_path):
    _app()
    source = tmp_path / "restore-me.mp4"
    source.touch()
    store = SessionStore(tmp_path / "session.json")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *_args, **_kwargs: ([str(source)], "MP4 Files (*.mp4)"),
    )

    window = MainWindow(session_store=store, autosave_interval_ms=1)
    window.queue_widget.action_add_file.trigger()
    QTest.qWait(50)

    assert store.load().job_queue.get_all_jobs()[0].source_path == source
    window.close()

    restored_window = MainWindow(session_store=store, autosave_interval_ms=1)
    assert restored_window.job_queue.get_all_jobs()[0].source_path == source
    assert restored_window.queue_widget.tree.topLevelItemCount() == 1
    restored_window.close()


def test_saved_current_job_reopens_in_editor(monkeypatch, tmp_path):
    _app()
    source = tmp_path / "current.mp4"
    source.touch()
    queue = JobQueue()
    job = queue.add_file(source)
    job.status = JobStatus.REVIEW
    job.scenes = [Scene(index=1, start_time=0.0, end_time=4.0)]
    store = SessionStore(tmp_path / "session.json")
    store.save(queue, current_job_id=job.id)
    monkeypatch.setattr(MainWindow, "_regenerate_thumbnails", lambda _self: None)
    monkeypatch.setattr(PreviewWidget, "load_video", lambda _self, _path: None)

    window = MainWindow(session_store=store)

    assert window.current_job is not None
    assert window.current_job.id == job.id
    assert window.center_stack.currentWidget() is window.editor_center
    assert window.clip_list_widget.current_job is window.current_job
    window.close()


def test_keep_change_can_be_undone_and_redone(tmp_path):
    _app()
    source = tmp_path / "history.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        scenes=[Scene(index=1, start_time=0.0, end_time=4.0, keep=True)],
    )
    window = MainWindow()
    window.current_job = job
    window.clip_list_widget.set_job(job)
    window.timeline_widget.set_scenes([0.0], 4.0)
    window.show()

    window.clip_list_widget._clip_rows[0].keep_check.click()
    assert job.scenes[0].keep is False

    window._shortcut_undo()
    assert job.scenes[0].keep is True

    window._shortcut_redo()
    assert job.scenes[0].keep is False
    window.close()


def test_export_button_becomes_cancel_action_while_exporting(tmp_path):
    _app()
    source = tmp_path / "export.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        scenes=[
            Scene(index=1, start_time=0.0, end_time=4.0),
            Scene(index=2, start_time=4.0, end_time=8.0),
        ],
    )
    widget = ClipListWidget()
    widget.set_job(job)
    cancelled = []
    widget.export_cancel_requested.connect(lambda: cancelled.append(True))

    widget.set_exporting(True)

    assert widget.btn_export.text() == "書き出しを中止"
    assert widget.btn_export.isEnabled() is True
    widget.btn_export.click()
    assert cancelled == [True]
    widget.close()


def test_export_worker_freezes_editable_job_state_at_start(tmp_path):
    source = tmp_path / "snapshot.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        default_event_name="開始時",
        scenes=[
            Scene(
                index=1,
                start_time=0.0,
                end_time=4.0,
                keep=True,
                filename_override="開始時",
            )
        ],
    )

    worker = ExportWorker(job, tmp_path)
    job.default_event_name = "編集中"
    job.scenes[0].keep = False
    job.scenes[0].filename_override = "編集中"

    assert worker.export_job.default_event_name == "開始時"
    assert worker.export_job.scenes[0].keep is True
    assert worker.export_job.scenes[0].filename_override == "開始時"


def test_clip_editor_hides_low_frequency_controls_until_needed(tmp_path):
    _app()
    source = tmp_path / "compact.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        scenes=[
            Scene(index=1, start_time=0.0, end_time=4.0),
            Scene(index=2, start_time=4.0, end_time=8.0),
        ],
    )
    widget = ClipListWidget()
    widget.set_job(job)
    row = widget._clip_rows[0]

    assert widget.output_name_label.text() == "出力名"
    assert widget.btn_clear_date.isHidden() is True
    assert row.select_check.isHidden() is True
    assert row.filename_edit.isReadOnly() is True
    assert row.filename_edit.isHidden() is True
    assert row.filename_label.isHidden() is False
    assert row.filename_label.focusPolicy() == Qt.StrongFocus
    assert row.keep_check.text() == "書き出す"
    assert row.sensitive_check.text() == "別フォルダ"
    assert widget.btn_postprocess.text() == "自動補正"

    widget.show()
    QApplication.processEvents()
    row.filename_label.setFocus()
    QTest.keyClick(row.filename_label, Qt.Key_F2)
    assert row.filename_edit.isHidden() is False
    assert row.filename_edit.hasFocus() is True

    widget.date_edit.setDate(QDate(2025, 4, 5))
    assert widget.btn_clear_date.isHidden() is False

    widget.btn_merge_mode.click()
    assert row.select_check.isHidden() is False
    assert row.settings_widget.isHidden() is True
    widget.close()


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


def test_timeline_keeps_advanced_controls_in_disclosure_menus():
    _app()
    widget = TimelineWidget()

    assert widget.btn_settings.text() == "設定"
    assert widget.btn_help.text() == "操作方法"
    assert widget.btn_reset.text() == "境界をすべて削除"
    assert widget.threshold_spin.isVisible() is False
    assert widget.min_scene_spin.isVisible() is False
    widget.close()


def test_log_details_are_disclosed_from_compact_status_row():
    _app()
    window = MainWindow()

    assert not hasattr(window, "btn_toggle_log")
    assert window.log_widget.status_label.isVisible() is False
    assert window.log_widget.log_text.isHidden() is True

    window.show()
    window.log_widget.btn_toggle_details.click()
    assert window.log_widget.log_text.isHidden() is False
    window.close()


def test_empty_state_uses_central_drop_zone_and_hides_editor_panes(tmp_path):
    _app()
    window = MainWindow()

    assert window.center_stack.currentWidget() is window.drop_zone
    assert window.clip_list_widget.isHidden() is True

    source = tmp_path / "ready.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        scenes=[Scene(index=1, start_time=0.0, end_time=4.0)],
    )
    window._on_job_selected(job)

    assert window.center_stack.currentWidget() is window.editor_center
    assert window.clip_list_widget.isHidden() is False
    window.close()


def test_proposal_dialogs_keep_secondary_explanations_collapsed():
    _app()
    merge = MergeProposalDialog([0.0, 1.0, 8.0], 10.0)
    blank = BlankCutDialog([(1.0, 2.0, "黒"), (4.0, 5.0, "青")])

    assert merge.btn_skip.text() == "キャンセル"
    assert not hasattr(merge, "intro_label")
    assert blank.detail_label.isHidden() is True
    assert blank.btn_toggle_detail.text() == "2区間を確認"

    blank.btn_toggle_detail.click()
    assert blank.detail_label.isHidden() is False
    merge.close()
    blank.close()


def test_editor_layout_remains_usable_at_compact_desktop_size(tmp_path):
    _app()
    source = tmp_path / "responsive.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        scenes=[
            Scene(index=1, start_time=0.0, end_time=4.0),
            Scene(index=2, start_time=4.0, end_time=8.0),
        ],
    )
    window = MainWindow()
    window.current_job = job
    window._show_editor_layout()
    window.clip_list_widget.set_job(job)
    window.timeline_widget.set_scenes([0.0, 4.0], 8.0)
    window.resize(960, 640)
    window.show()
    QApplication.processEvents()

    assert window.minimumWidth() <= 960
    assert window.minimumHeight() <= 640
    assert window.clip_list_widget.width() >= 340
    assert window.preview_widget.video_widget.width() >= 260
    window.close()


def test_metadata_filename_and_sensitive_edits_share_undo_history(tmp_path):
    _app()
    source = tmp_path / "metadata-history.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        scenes=[Scene(index=1, start_time=0.0, end_time=4.0)],
    )
    window = MainWindow()
    window.current_job = job
    window.clip_list_widget.set_job(job)

    window.clip_list_widget.event_name_edit.setText("旅行")
    window.clip_list_widget._on_default_metadata_changed()
    row = window.clip_list_widget._clip_rows[0]
    row.filename_edit.setReadOnly(False)
    row.filename_edit.setText("海辺")
    row._on_filename_changed()
    row.sensitive_check.click()

    assert job.default_event_name == "旅行"
    assert job.scenes[0].filename_override == "海辺"
    assert job.scenes[0].is_sensitive is True

    window._shortcut_undo()
    assert job.scenes[0].is_sensitive is False
    window._shortcut_undo()
    assert job.scenes[0].filename_override is None
    window._shortcut_undo()
    assert job.default_event_name == ""
    window.close()


def test_boundary_edit_can_be_undone_and_redone_with_scene_state(tmp_path):
    _app()
    source = tmp_path / "boundary-history.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        scenes=[Scene(index=1, start_time=0.0, end_time=8.0, is_sensitive=True)],
    )
    window = MainWindow()
    window.current_job = job
    window.clip_list_widget.set_job(job)
    window.timeline_widget.set_scenes([0.0], 8.0)
    window._last_boundaries = [0.0]
    window._regenerate_thumbnails = lambda: None

    window.timeline_widget.add_boundary(4.0)
    assert len(job.scenes) == 2
    assert all(scene.is_sensitive for scene in job.scenes)

    window._shortcut_undo()
    assert len(job.scenes) == 1
    assert job.scenes[0].is_sensitive is True

    window._shortcut_redo()
    assert len(job.scenes) == 2
    assert all(scene.is_sensitive for scene in job.scenes)
    window.close()


def test_detected_dates_can_be_undone(tmp_path):
    _app()
    source = tmp_path / "ocr-history.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        scenes=[Scene(index=1, start_time=0.0, end_time=4.0)],
    )
    window = MainWindow()
    window.current_job = job
    window.clip_list_widget.set_job(job)
    window.timeline_widget.set_scenes([0.0], 4.0)
    window._date_detect_auto = True

    window._on_date_detect_complete({"full": {1: date(1998, 8, 12)}, "ym": {}})
    assert job.scenes[0].event_date == date(1998, 8, 12)

    window._shortcut_undo()
    assert job.scenes[0].event_date is None
    window.close()


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
    assert widget.btn_blank_detect.text() == "つなぎ目検出を中止"
    assert widget.btn_blank_detect.isEnabled() is True
    assert widget.btn_date_detect.isEnabled() is False
    assert widget.btn_short_merge.isEnabled() is False
    assert widget.btn_export.isEnabled() is False
    assert all(not row.keep_check.isEnabled() for row in widget._clip_rows)
    assert all(not row.filename_edit.isEnabled() for row in widget._clip_rows)

    widget.set_blank_detecting(False)
    widget.set_date_detecting(True)
    assert widget.btn_date_detect.text() == "日付検出を中止"
    assert widget.btn_date_detect.isEnabled() is True
    assert widget.btn_blank_detect.isEnabled() is False
    assert widget.btn_short_merge.isEnabled() is False
    assert widget.btn_export.isEnabled() is False

    widget.set_date_detecting(False)
    widget.set_exporting(True)
    assert widget.btn_blank_detect.isEnabled() is False
    assert widget.btn_date_detect.isEnabled() is False
    assert widget.btn_short_merge.isEnabled() is False
    assert widget.btn_export.isEnabled() is True
    assert widget.btn_export.text() == "書き出しを中止"

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
