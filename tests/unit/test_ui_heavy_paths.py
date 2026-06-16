"""
Regression tests for UI paths that can accidentally fan out heavy work.
"""
from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QDate

from app.core.jobs import JobStatus, Scene, VideoJob
from app.ui.clip_list_widget import ClipListWidget
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
    job = VideoJob(id=1, source_path=video_path, status=JobStatus.REVIEW)
    widget = ClipListWidget()
    widget.set_job(job)

    widget.date_edit.setDate(QDate(2025, 4, 5))
    widget._on_default_metadata_changed()

    assert job.default_event_date == date(2025, 4, 5)
    widget.close()
