"""
キュー表示UIの状態表示テスト
"""
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.core.jobs import JobQueue, JobStatus, Scene, VideoJob
from app.ui.queue_widget import QueueWidget, job_status_badge, next_open_action_text


def _app():
    return QApplication.instance() or QApplication([])


def test_job_status_badge_shows_post_process_before_review():
    job = VideoJob(id=1, source_path=Path("/tmp/video.mp4"), status=JobStatus.REVIEW)
    job.scenes = [
        Scene(index=1, start_time=0.0, end_time=10.0),
        Scene(index=2, start_time=10.0, end_time=20.0),
    ]
    job.needs_post_process = True

    text, bg_color, fg_color = job_status_badge(job)

    assert text == "確認待ち / 2本"
    assert bg_color == "#654a1f"
    assert fg_color == "#ffe3a3"


def test_next_open_action_explains_auto_post_processing():
    job = VideoJob(id=1, source_path=Path("/tmp/video.mp4"), status=JobStatus.REVIEW)
    job.scenes = [Scene(index=1, start_time=0.0, end_time=10.0)]
    job.needs_post_process = True

    assert next_open_action_text(job) == (
        "開くと: 検出済みクリップを表示し、日付検出をバックグラウンドで行います"
    )


def test_queue_selection_enables_explicit_open_action(tmp_path):
    _app()
    video_path = tmp_path / "video.mp4"
    video_path.touch()
    queue = JobQueue()
    job = queue.add_file(video_path)
    job.status = JobStatus.REVIEW
    job.scenes = [Scene(index=1, start_time=0.0, end_time=10.0)]
    job.needs_post_process = True

    widget = QueueWidget(queue)
    widget.refresh()
    widget.select_job(job.id)
    opened = []
    widget.open_video.connect(lambda selected: opened.append(selected.id))

    assert widget.btn_open.isEnabled() is True
    widget.btn_open.click()
    assert opened == [job.id]
    assert widget.tree.headerItem().text(0) == "動画"
    assert widget.tree.topLevelItem(0).text(1) == "確認待ち / 1本"
    assert widget.tree.topLevelItem(0).toolTip(0) == video_path.name

    widget.close()


def test_queue_filter_shows_only_matching_work_state(tmp_path):
    _app()
    queue = JobQueue()
    for name, status in (
        ("waiting.mp4", JobStatus.WAITING),
        ("review.mp4", JobStatus.REVIEW),
        ("error.mp4", JobStatus.ERROR),
        ("done.mp4", JobStatus.DONE),
    ):
        path = tmp_path / name
        path.touch()
        job = queue.add_file(path)
        job.status = status
        if status != JobStatus.WAITING:
            job.scenes = [Scene(index=1, start_time=0.0, end_time=10.0)]

    widget = QueueWidget(queue)
    widget.refresh()
    widget.filter_combo.setCurrentIndex(widget.filter_combo.findData("error"))

    assert widget.tree.topLevelItemCount() == 1
    assert widget.tree.topLevelItem(0).text(0) == "error.mp4"
    widget.close()


def test_queue_refresh_does_not_emit_selection_side_effects(tmp_path):
    _app()
    video_path = tmp_path / "video.mp4"
    video_path.touch()
    queue = JobQueue()
    job = queue.add_file(video_path)
    job.status = JobStatus.REVIEW
    job.scenes = [Scene(index=1, start_time=0.0, end_time=10.0)]
    job.needs_post_process = True

    widget = QueueWidget(queue)
    emitted = []
    widget.job_selected.connect(lambda selected: emitted.append(selected.id))

    widget.refresh()
    widget.select_job(job.id)
    assert emitted == [job.id]

    emitted.clear()
    widget.refresh()

    assert emitted == []

    widget.close()


def test_queue_actions_follow_selection_and_waiting_jobs(tmp_path):
    _app()
    queue = JobQueue()
    widget = QueueWidget(queue)
    widget.refresh()

    assert widget.btn_remove.isEnabled() is False
    assert widget.btn_detect_all.isEnabled() is False

    waiting_path = tmp_path / "waiting.mp4"
    waiting_path.touch()
    waiting_job = queue.add_file(waiting_path)
    widget.refresh()

    assert widget.btn_detect_all.isEnabled() is True
    assert widget.btn_detect_all.text() == "一括検出 (1)"

    widget.select_job(waiting_job.id)
    assert widget.btn_remove.isEnabled() is True

    progress_requests = []
    widget.detect_all_requested.connect(lambda: progress_requests.append(True))
    widget.set_detect_all_enabled(False)
    assert widget.btn_detect_all.isEnabled() is True
    assert widget.btn_detect_all.text() == "進捗を表示"
    widget.btn_detect_all.click()
    assert progress_requests == [True]
    widget.set_detect_all_enabled(True)
    assert widget.btn_detect_all.isEnabled() is True

    waiting_job.status = JobStatus.REVIEW
    widget.refresh()
    assert widget.btn_detect_all.isEnabled() is False
    assert widget.btn_detect_all.text() == "一括検出"

    widget.close()
