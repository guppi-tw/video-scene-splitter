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

    assert text == "後処理待ち / 2本"
    assert bg_color == "#654a1f"
    assert fg_color == "#ffe3a3"


def test_next_open_action_explains_auto_post_processing():
    job = VideoJob(id=1, source_path=Path("/tmp/video.mp4"), status=JobStatus.REVIEW)
    job.scenes = [Scene(index=1, start_time=0.0, end_time=10.0)]
    job.needs_post_process = True

    assert next_open_action_text(job) == "開くと: つなぎ目検出 -> 結合提案 -> 日付検出"


def test_queue_selection_updates_next_action_label(tmp_path):
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

    assert widget.next_action_label.text() == (
        "開くと: つなぎ目検出 -> 結合提案 -> 日付検出"
    )
    assert widget.tree.topLevelItem(0).text(1) == "後処理待ち / 1本"

    widget.close()
