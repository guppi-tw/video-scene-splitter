"""
Regression tests for UI paths that can accidentally fan out heavy work.
"""
from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PySide6.QtCore import QDate, Qt
from PySide6.QtTest import QTest

from app.core.jobs import JobQueue, JobStatus, Scene, VideoJob
from app.core.session_store import SessionStore
from app.core.media_signal_detector import build_media_signal_result
from app.ui.clip_list_widget import BlankCandidateRow, ClipListWidget
from app.ui.main_window import MainWindow
from app.ui.preview_widget import PreviewWidget
from app.ui.timeline_widget import TimelineWidget
from app.ui.workers import ExportWorker
from app.ui.merge_dialog import MergeProposalDialog


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


def test_export_preset_controls_split_and_exact_export_choice(monkeypatch, tmp_path):
    _app()
    source = tmp_path / "preset.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        scenes=[Scene(index=1, start_time=0.0, end_time=4.0)],
    )
    widget = ClipListWidget()
    widget.set_job(job)
    emitted = []
    widget.export_requested.connect(lambda *_args: emitted.append(_args))
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *_args, **_kwargs: str(tmp_path)
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.Yes
    )

    exact_index = widget.export_preset_combo.findData("exact")
    widget.export_preset_combo.setCurrentIndex(exact_index)

    assert job.export_preset == "exact"
    assert job.auto_split_enabled is True
    assert "再エンコード" in widget.export_preset_combo.toolTip()

    widget.btn_export.click()
    assert emitted[0][2] == "exact"
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


def test_export_worker_resolves_exact_boundary_preset(tmp_path):
    source = tmp_path / "exact-worker.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        scenes=[Scene(index=1, start_time=0.25, end_time=4.75)],
    )

    worker = ExportWorker(job, tmp_path, export_preset="exact")

    assert worker.exporter.auto_split is True
    assert worker.exporter.use_copy is False


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

    assert widget.finish_panel.isHidden() is True
    assert row.filename_container.isHidden() is True
    assert row.sensitive_check.isHidden() is True
    assert row.keep_check.isHidden() is False
    assert row.height() == 62

    widget.btn_toggle_finish.click()

    assert widget.output_name_label.text() == "出力名"
    assert widget.btn_clear_date.isHidden() is True
    assert row.select_check.isHidden() is True
    assert row.filename_edit.isReadOnly() is True
    assert row.filename_edit.isHidden() is True
    assert row.filename_label.isHidden() is False
    assert row.filename_label.focusPolicy() == Qt.StrongFocus
    assert row.keep_check.text() == "書き出す"
    assert row.sensitive_check.text() == "共有注意"
    assert "専用フォルダ" in row.sensitive_check.toolTip()
    assert widget.btn_postprocess.text() == "補正ツール"
    assert widget.btn_short_merge.text() == "短いシーンの結合を提案"
    assert widget.btn_merge_mode.text() == "選択して結合"
    assert widget.btn_apply_all.text() == "全クリップに上書き"
    assert widget.export_method_label.text() == "書き出し方法"
    assert widget.keep_all_check.text() == "全クリップを選択"
    assert widget.review_bar.isAncestorOf(widget.keep_all_check) is True
    assert widget.action_bar.isAncestorOf(widget.keep_all_check) is False

    widget.show()
    QApplication.processEvents()
    row.filename_label.setFocus()
    QTest.keyClick(row.filename_label, Qt.Key_F2)
    assert row.filename_edit.isHidden() is False
    assert row.filename_edit.hasFocus() is True

    widget.date_edit.setDate(QDate(2025, 4, 5))
    assert widget.btn_clear_date.isHidden() is False

    widget.btn_merge_mode.click()
    row = widget._clip_rows[0]
    assert row.select_check.isHidden() is False
    assert row.settings_widget.isHidden() is True
    widget.close()


def test_clip_editor_keeps_hour_long_time_range_visible_at_minimum_width(tmp_path):
    _app()
    source = tmp_path / "hour-long.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        scenes=[Scene(index=62, start_time=3702.0, end_time=3737.0)],
    )
    widget = ClipListWidget()
    widget.set_job(job)
    widget.resize(340, 600)
    widget.show()
    QApplication.processEvents()
    time_label = widget._clip_rows[0].time_label

    assert time_label.text() == "#62  1:01:42–1:02:17"
    assert time_label.width() >= time_label.sizeHint().width()
    widget.close()


def test_blank_candidates_are_modeless_preview_rows_in_clip_list(tmp_path):
    _app()
    source = tmp_path / "blank-review.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        scenes=[
            Scene(index=1, start_time=0.0, end_time=10.0),
            Scene(index=2, start_time=10.0, end_time=20.0),
        ],
    )
    widget = ClipListWidget()
    widget.set_job(job)
    segments = [(3.0, 4.0, "黒"), (12.0, 16.0, "青")]
    previewed = []
    confirmed = []
    widget.blank_preview_requested.connect(
        lambda start, end: previewed.append((start, end))
    )
    widget.blank_trim_confirmed.connect(confirmed.append)

    widget.show_blank_candidates(segments)
    widget.resize(340, 600)
    widget.show()
    QApplication.processEvents()

    assert widget.blank_review_bar.isHidden() is False
    assert widget.blank_review_summary.text() == "単色候補 2区間（合計 0:05）"
    assert len(widget._blank_candidate_rows) == 2
    first = widget._blank_candidate_rows[0]
    assert isinstance(first, BlankCandidateRow)
    assert first.objectName() == "blankCandidateRow"
    assert first.description_label.text() == "単色候補（黒）  0:03–0:04"
    assert first.description_label.width() >= first.description_label.sizeHint().width()
    assert widget.btn_export.isEnabled() is False
    assert widget.btn_trim_blank_candidates.text() == "選択2件をトリミング"

    first.btn_preview.click()
    assert previewed == [(3.0, 4.0)]

    widget._blank_candidate_rows[1].trim_check.setChecked(False)
    assert widget.btn_trim_blank_candidates.text() == "選択1件をトリミング"
    widget.btn_trim_blank_candidates.click()
    assert confirmed == [[segments[0]]]
    assert widget.blank_review_bar.isHidden() is True
    assert widget._blank_candidate_rows == []
    widget.close()


def test_clip_editor_guides_user_through_only_pending_review_items(tmp_path):
    _app()
    source = tmp_path / "review-guide.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        default_event_date=date(1998, 8, 12),
        scenes=[
            Scene(
                index=1,
                start_time=0.0,
                end_time=2.0,
                date_source="inferred",
            ),
            Scene(index=2, start_time=2.0, end_time=8.0),
        ],
    )
    widget = ClipListWidget()
    widget.set_job(job)
    previewed = []
    widget.clip_preview_requested.connect(previewed.append)

    assert widget.review_summary_label.text() == "確認事項 1件"
    assert "3秒未満" in widget._clip_rows[0].review_label.text()
    assert "推定日付: 1998/08/12" in widget._clip_rows[0].review_label.text()
    assert widget.btn_next_review.property("recommended") is True
    assert widget.btn_export.property("recommended") is False

    widget.btn_next_review.click()
    assert previewed == [0.0]

    widget._clip_rows[0].btn_review_done.click()
    assert widget.review_summary_label.text() == "確認事項なし"
    assert job.scenes[0].reviewed_flags == ["short_scene", "date_inferred"]
    assert widget.btn_next_review.property("recommended") is False
    assert widget.btn_export.property("recommended") is True
    widget.close()


def test_changing_default_date_reopens_a_new_missing_date_review(tmp_path):
    _app()
    source = tmp_path / "date-review.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        scenes=[Scene(index=1, start_time=0.0, end_time=8.0)],
    )
    widget = ClipListWidget()
    widget.set_job(job)

    widget._clip_rows[0].btn_review_done.click()
    assert widget.review_summary_label.text() == "確認事項なし"

    widget.date_edit.setDate(QDate(1998, 8, 12))
    widget.btn_clear_date.click()

    assert widget.review_summary_label.text() == "確認事項 1件"
    assert "日付未設定" in widget._clip_rows[0].review_label.text()
    widget.close()


def test_detected_date_can_be_checked_and_corrected_inline(tmp_path):
    _app()
    source = tmp_path / "detected-date-review.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        scenes=[
            Scene(
                index=1,
                start_time=0.0,
                end_time=8.0,
                event_date=date(1998, 8, 12),
                date_source="detected",
            )
        ],
    )
    widget = ClipListWidget()
    widget.set_job(job)
    widget.btn_toggle_finish.click()
    row = widget._clip_rows[0]

    assert row.review_label.text() == "検出日付: 1998/08/12"
    assert row.btn_edit_review_date.isHidden() is False

    row.btn_edit_review_date.click()
    assert row.date_editor_bar.isHidden() is False
    assert row.btn_edit_review_date.isHidden() is True
    row.review_date_edit.setDate(QDate(1998, 8, 13))
    row.btn_apply_review_date.click()

    assert job.scenes[0].event_date == date(1998, 8, 13)
    assert job.scenes[0].date_source == "manual"
    assert widget.review_summary_label.text() == "確認事項なし"
    widget.close()


def test_recommended_action_moves_from_detection_to_export(tmp_path):
    _app()
    source = tmp_path / "recommended-action.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        default_event_date=date(1998, 8, 12),
        scenes=[Scene(index=1, start_time=0.0, end_time=8.0)],
    )
    timeline = TimelineWidget()
    clips = ClipListWidget()

    timeline.set_scenes([0.0], 8.0)
    clips.set_job(job)

    assert timeline.btn_auto_detect.property("recommended") is True
    assert timeline.btn_auto_detect.accessibleDescription() == "おすすめの次の操作"
    assert clips.btn_export.property("recommended") is False

    timeline.set_auto_detect_enabled(False)
    assert timeline.btn_auto_detect.property("recommended") is False
    timeline.set_auto_detect_enabled(True)
    assert timeline.btn_auto_detect.property("recommended") is True

    job.scenes = [
        Scene(index=1, start_time=0.0, end_time=4.0),
        Scene(index=2, start_time=4.0, end_time=8.0),
    ]
    timeline.set_scenes([0.0, 4.0], 8.0)
    clips.refresh_clips()

    assert timeline.btn_auto_detect.property("recommended") is False
    assert clips.btn_export.property("recommended") is True
    assert clips.btn_export.accessibleDescription() == "おすすめの次の操作"
    timeline.close()
    clips.close()


def test_scene_detection_finishes_without_opening_correction_modals(tmp_path):
    _app()
    source = tmp_path / "no-modal-chain.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        scenes=[Scene(index=1, start_time=0.0, end_time=8.0)],
    )
    window = MainWindow()
    window.current_job = job
    window.clip_list_widget.set_job(job)
    window.timeline_widget.set_scenes([0.0], 8.0)
    calls = []
    window._begin_deferred_thumbnails = lambda: calls.append("defer")
    window._finish_scene_detection = lambda: calls.append("detect-finished")
    window._start_blank_detection = lambda **_kwargs: calls.append("blank")
    window._propose_short_scene_merge = lambda: calls.append("merge")
    window._start_date_detection = lambda auto: calls.append(("date", auto)) or True
    window._regenerate_thumbnails = lambda: None

    window._on_scene_detection_complete([0.0, 4.0])

    assert calls == ["detect-finished"]
    assert len(job.scenes) == 1
    assert window.timeline_widget.detection_preview_times == [4.0]
    assert window.timeline_widget.detection_panel.isHidden() is False

    window.timeline_widget.btn_detection_apply.click()

    assert len(job.scenes) == 2
    assert calls == ["detect-finished", ("date", True)]
    assert "補正ツール" in window.log_widget.log_text.toPlainText()
    window.close()


def test_media_signal_results_stay_as_non_destructive_review_candidates(tmp_path):
    _app()
    source = tmp_path / "signals.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        default_event_date=date(1998, 8, 12),
        scenes=[
            Scene(index=1, start_time=0.0, end_time=10.0),
            Scene(index=2, start_time=10.0, end_time=20.0),
        ],
    )
    result = build_media_signal_result(
        existing_boundaries=[0.0, 10.0],
        duration=20.0,
        silence_ranges=[(4.0, 6.0)],
        fade_times=[15.0],
    )
    window = MainWindow()
    window.job_queue._jobs.append(job)
    window.current_job = job
    window.clip_list_widget.set_job(job)
    window.timeline_widget.set_scenes([0.0, 10.0], 20.0)

    window._on_media_signal_complete(result)

    assert window.timeline_widget.get_boundaries() == [0.0, 10.0]
    assert window.timeline_widget.boundary_candidates == [4.0, 6.0, 15.0]
    assert "長い無音" in window.clip_list_widget._clip_rows[0].review_label.text()
    assert "フェード候補" in window.clip_list_widget._clip_rows[1].review_label.text()

    window._regenerate_thumbnails = lambda: None
    window.timeline_widget.candidate_summary_button.click()

    assert window.timeline_widget.get_boundaries() == [
        0.0,
        4.0,
        6.0,
        10.0,
        15.0,
    ]
    assert job.suggested_boundaries == []
    window.close()


def test_opening_batch_detected_video_does_not_start_modal_corrections(
    monkeypatch, tmp_path
):
    _app()
    source = tmp_path / "batch-detected.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        scenes=[
            Scene(index=1, start_time=0.0, end_time=4.0),
            Scene(index=2, start_time=4.0, end_time=8.0),
        ],
        needs_post_process=True,
    )
    monkeypatch.setattr(
        "app.ui.main_window.FFmpegRunner",
        lambda: type("Runner", (), {"get_video_duration": lambda _self, _path: 8.0})(),
    )
    window = MainWindow()
    calls = []
    window._begin_deferred_thumbnails = lambda: calls.append("defer")
    window._start_blank_detection = lambda **_kwargs: calls.append("blank")
    window._propose_short_scene_merge = lambda: calls.append("merge")
    window._start_date_detection = lambda auto: calls.append(("date", auto)) or True
    window._regenerate_thumbnails = lambda: None
    window.preview_widget.load_video = lambda _path: None

    window._on_open_video(job)

    assert calls == ["defer", ("date", True)]
    assert job.needs_post_process is False
    assert "補正ツール" in window.log_widget.log_text.toPlainText()
    window.close()


def test_merge_action_becomes_recommended_only_after_valid_selection(tmp_path):
    _app()
    source = tmp_path / "merge-recommendation.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        default_event_date=date(1998, 8, 12),
        scenes=[
            Scene(index=1, start_time=0.0, end_time=4.0),
            Scene(index=2, start_time=4.0, end_time=8.0),
        ],
    )
    widget = ClipListWidget()
    widget.set_job(job)

    assert widget.btn_export.property("recommended") is True
    widget.btn_merge_mode.click()

    assert widget.btn_export.property("recommended") is False
    assert widget.btn_merge.property("recommended") is False

    widget._clip_rows[0].select_check.click()
    widget._clip_rows[1].select_check.click()

    assert widget.btn_merge.isEnabled() is True
    assert widget.btn_merge.property("recommended") is True
    assert widget.btn_merge.accessibleDescription() == "おすすめの次の操作"
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


def test_timeline_reviews_and_nudges_nearest_boundary_inline():
    _app()
    widget = TimelineWidget()
    widget.set_scenes([0.0, 4.0, 8.0], 12.0)
    widget.set_playhead(4.2)
    requested = []
    changed = []
    widget.boundary_review_requested.connect(requested.append)
    widget.boundaries_changed.connect(changed.append)

    widget.btn_review_boundary.click()

    assert requested == [4.0]
    assert widget.boundary_review_panel.isHidden() is False
    assert "4.00秒" in widget.boundary_review_title.text()

    widget.btn_boundary_earlier.click()

    assert changed[-1] == [0.0, 3.9, 8.0]
    assert requested[-1] == 3.9
    widget.close()


def test_timeline_keeps_signal_candidates_separate_until_user_applies_them():
    _app()
    widget = TimelineWidget()
    widget.set_scenes([0.0, 10.0], 20.0)
    changed = []
    widget.boundaries_changed.connect(changed.append)

    widget.set_boundary_candidates([4.0, 6.0])

    assert widget.candidate_summary_button.text() == "解析候補 2件を追加"
    assert widget.candidate_summary_button.isHidden() is False
    assert widget.candidate_summary_button.isEnabled() is True
    assert widget.get_boundaries() == [0.0, 10.0]

    widget.candidate_summary_button.click()

    assert changed[-1] == [0.0, 4.0, 6.0, 10.0]
    assert widget.candidate_summary_button.isHidden() is True
    assert widget.candidate_summary_button.isEnabled() is False
    widget.close()


def test_timeline_reset_is_disabled_while_detecting():
    _app()
    widget = TimelineWidget()
    widget.set_scenes([0.0, 4.0], 10.0)

    assert widget.btn_reset.isEnabled() is True
    assert widget.btn_auto_detect.text() == "シーンを検出して分割"
    widget.set_detecting(True)
    assert widget.btn_auto_detect.text() == "検出を中止"
    assert widget.btn_reset.isEnabled() is False
    assert widget.btn_blank_trim.isEnabled() is False

    widget.set_detecting(False)
    assert widget.btn_auto_detect.text() == "シーンを検出して分割"
    assert widget.btn_reset.isEnabled() is True
    assert widget.btn_blank_trim.isEnabled() is True
    widget.close()


def test_timeline_exposes_separate_scene_detection_and_solid_color_actions():
    _app()
    widget = TimelineWidget()
    widget.set_scenes([0.0], 12.0)
    trim_requests = []
    trim_cancel_requests = []
    widget.blank_trim_requested.connect(lambda: trim_requests.append(True))
    widget.blank_trim_cancel_requested.connect(
        lambda: trim_cancel_requests.append(True)
    )

    assert widget.btn_auto_detect.text() == "シーンを検出して分割"
    assert widget.btn_blank_trim.text() == "単色区間をトリミング"
    assert widget.btn_auto_detect.isEnabled() is True
    assert widget.btn_blank_trim.isEnabled() is True

    widget.btn_blank_trim.click()
    assert trim_requests == [True]

    widget.set_blank_trimming(True)
    assert widget.btn_blank_trim.text() == "単色区間の検出を中止"
    assert widget.btn_blank_trim.isEnabled() is True
    assert widget.btn_auto_detect.isEnabled() is False
    assert widget.btn_reset.isEnabled() is False

    widget.btn_blank_trim.click()
    assert trim_cancel_requests == [True]

    widget.set_blank_trimming(False)
    assert widget.btn_blank_trim.text() == "単色区間をトリミング"
    assert widget.btn_auto_detect.isEnabled() is True
    assert widget.btn_reset.isEnabled() is True
    widget.close()


def test_timeline_keeps_advanced_controls_in_disclosure_menus():
    _app()
    widget = TimelineWidget()

    menu_labels = [action.text() for action in widget.btn_more.menu().actions()]

    assert widget.btn_more.text() == "…"
    assert widget.settings_action.text() == "シーン検出設定を開く"
    assert "操作方法" in menu_labels
    assert widget.btn_reset.text() == "境界をすべて削除"
    assert widget.threshold_spin.isVisible() is False
    assert widget.min_scene_spin.isVisible() is False
    widget.close()


def test_scene_detection_preview_supports_tuning_navigation_and_apply():
    _app()
    widget = TimelineWidget()
    widget.set_scenes([0.0], 12.0)
    detect_requests = []
    seeks = []
    comparisons = []
    changed = []
    applied = []
    widget.auto_detect_requested.connect(lambda: detect_requests.append(True))
    widget.seek_requested.connect(seeks.append)
    widget.boundary_review_requested.connect(comparisons.append)
    widget.boundaries_changed.connect(changed.append)
    widget.scene_detection_preview_applied.connect(applied.append)

    widget.btn_auto_detect.click()
    assert widget.detection_panel.isHidden() is False
    assert widget.primary_actions_panel.isHidden() is True
    assert detect_requests == [True]

    widget.set_detection_preview([0.0, 4.0, 8.0, 12.0])
    assert widget.detection_preview_times == [4.0, 8.0]
    assert widget.timeline_bar.detection_preview_times == [4.0, 8.0]
    assert "反映後 3クリップ" in widget.detection_status_label.text()
    assert widget.btn_detection_apply.isEnabled() is True

    widget.btn_detection_next.click()
    assert seeks == [8.0]
    widget.btn_detection_compare.click()
    assert comparisons == [8.0]

    widget.threshold_spin.setValue(2.5)
    assert "設定が変わりました" in widget.detection_status_label.text()
    assert widget.btn_detection_apply.isEnabled() is False

    widget.btn_detection_run.click()
    assert detect_requests == [True, True]
    widget.set_detection_preview([0.0, 3.0, 6.0, 9.0])
    assert widget.btn_detection_apply.isEnabled() is True

    widget.btn_detection_apply.click()
    assert changed[-1] == [0.0, 3.0, 6.0, 9.0]
    assert applied == [[3.0, 6.0, 9.0]]
    assert widget.detection_preview_times == []
    assert widget.detection_panel.isHidden() is True
    assert widget.btn_auto_detect.isHidden() is False
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


def test_merge_proposal_keeps_secondary_explanations_collapsed():
    _app()
    merge = MergeProposalDialog([0.0, 1.0, 8.0], 10.0)

    assert merge.btn_skip.text() == "結合しない"
    assert not hasattr(merge, "intro_label")
    merge.close()


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
    assert job.scenes[0].date_source == "detected"

    window._shortcut_undo()
    assert job.scenes[0].event_date is None
    window.close()


def test_date_detection_results_open_inline_review_without_completion_modal(
    monkeypatch, tmp_path
):
    _app()
    source = tmp_path / "ocr-review.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        scenes=[Scene(index=1, start_time=0.0, end_time=8.0)],
    )
    window = MainWindow()
    window.current_job = job
    window.clip_list_widget.set_job(job)
    window.timeline_widget.set_scenes([0.0], 8.0)
    window._date_detect_auto = False
    modal_calls = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *_args, **_kwargs: modal_calls.append(True),
    )

    window._on_date_detect_complete({"full": {1: date(1998, 8, 12)}, "ym": {}})

    assert modal_calls == []
    assert window.clip_list_widget.review_summary_label.text() == "確認事項 1件"
    assert "検出日付: 1998/08/12" in (
        window.clip_list_widget._clip_rows[0].review_label.text()
    )
    assert "確認事項" in window.log_widget.log_text.toPlainText()
    window.close()


def test_inline_date_correction_participates_in_undo(tmp_path):
    _app()
    source = tmp_path / "date-correction-undo.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        scenes=[
            Scene(
                index=1,
                start_time=0.0,
                end_time=8.0,
                event_date=date(1998, 8, 12),
                date_source="detected",
            )
        ],
    )
    window = MainWindow()
    window.current_job = job
    window.clip_list_widget.set_job(job)
    window.timeline_widget.set_scenes([0.0], 8.0)
    row = window.clip_list_widget._clip_rows[0]
    row.btn_edit_review_date.click()
    row.review_date_edit.setDate(QDate(1998, 8, 13))
    row.btn_apply_review_date.click()

    window._shortcut_undo()

    assert job.scenes[0].event_date == date(1998, 8, 12)
    assert job.scenes[0].date_source == "detected"
    window.close()


def test_rerunning_date_detection_reopens_an_unresolved_missing_date(tmp_path):
    _app()
    source = tmp_path / "still-undated.mp4"
    source.touch()
    job = VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        scenes=[
            Scene(
                index=1,
                start_time=0.0,
                end_time=8.0,
                reviewed_flags=["date_missing"],
            )
        ],
    )
    window = MainWindow()
    window.current_job = job
    window.clip_list_widget.set_job(job)
    window.timeline_widget.set_scenes([0.0], 8.0)
    assert window.clip_list_widget.review_summary_label.text() == "確認事項なし"

    window._on_date_detect_complete({"full": {}, "ym": {}})

    assert window.clip_list_widget.review_summary_label.text() == "確認事項 1件"
    assert "日付未設定" in window.clip_list_widget._clip_rows[0].review_label.text()
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

    assert widget.workflow_bar.isHidden() is True
    assert widget.finish_panel.isHidden() is True
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

    assert widget.workflow_bar.isHidden() is False
    assert widget.finish_panel.isHidden() is True
    assert widget.scroll_area.isHidden() is False
    assert widget.btn_toggle_finish.text() == "仕上げ・書き出し"

    widget.btn_toggle_finish.click()
    assert widget.finish_panel.isHidden() is False
    assert widget.btn_toggle_finish.text() == "仕上げを閉じる"

    widget.clear()
    assert widget.workflow_bar.isHidden() is True
    assert widget.finish_panel.isHidden() is True
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

    assert widget.btn_date_detect.isEnabled() is True
    assert widget.btn_signal_analyze.isEnabled() is True
    assert widget.btn_short_merge.isEnabled() is True
    assert widget.btn_export.isEnabled() is True

    widget.set_blank_detecting(True)
    assert widget.btn_postprocess.isEnabled() is False
    assert widget.btn_date_detect.isEnabled() is False
    assert widget.btn_short_merge.isEnabled() is False
    assert widget.btn_export.isEnabled() is False
    assert all(not row.keep_check.isEnabled() for row in widget._clip_rows)
    assert all(not row.filename_edit.isEnabled() for row in widget._clip_rows)

    widget.set_blank_detecting(False)
    widget.set_media_signal_analyzing(True)
    assert widget.btn_signal_analyze.text() == "音声・フェード解析を中止"
    assert widget.btn_signal_analyze.isEnabled() is True
    assert widget.btn_date_detect.isEnabled() is False
    widget.set_media_signal_analyzing(False)

    widget.set_date_detecting(True)
    assert widget.btn_date_detect.text() == "日付検出を中止"
    assert widget.btn_date_detect.isEnabled() is True
    assert widget.btn_short_merge.isEnabled() is False
    assert widget.btn_export.isEnabled() is False

    widget.set_date_detecting(False)
    widget.set_exporting(True)
    assert widget.btn_date_detect.isEnabled() is False
    assert widget.btn_short_merge.isEnabled() is False
    assert widget.btn_export.isEnabled() is True
    assert widget.btn_export.text() == "書き出しを中止"

    widget.set_exporting(False)
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


def test_preview_widget_plays_only_the_requested_candidate_range():
    _app()
    preview = PreviewWidget()
    calls = []
    preview.seek_to = lambda seconds: calls.append(("seek", seconds))
    preview.play = lambda: calls.append(("play",))
    preview.pause = lambda: calls.append(("pause",))

    preview.play_range(3.0, 4.0)

    assert calls == [("seek", 3.0), ("play",)]
    assert preview._preview_end_ms == 4000

    preview._on_position_changed(3999)
    assert calls == [("seek", 3.0), ("play",)]
    preview._on_position_changed(4000)
    assert calls[-1] == ("pause",)
    assert preview._preview_end_ms is None
    preview.close()


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
