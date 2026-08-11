"""フィルムレビュー表示の回帰テスト。"""

from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.core.jobs import JobStatus, Scene, VideoJob
from app.ui.filmstrip_review_widget import (
    FilmstripCanvas,
    FilmstripReviewWidget,
    filmstrip_row_count,
)
from app.ui.main_window import MainWindow
from app.ui.timeline_widget import TimelineWidget


def _app():
    return QApplication.instance() or QApplication([])


def _job(tmp_path: Path) -> VideoJob:
    source = tmp_path / "review.mp4"
    source.touch()
    return VideoJob(
        id=1,
        source_path=source,
        status=JobStatus.REVIEW,
        scenes=[
            Scene(index=1, start_time=0.0, end_time=25.0),
            Scene(index=2, start_time=25.0, end_time=75.0, keep=False),
            Scene(index=3, start_time=75.0, end_time=130.0),
        ],
        suggested_boundaries=[18.0, 92.0],
    )


def test_row_count_wraps_one_timeline_without_dropping_partial_row():
    assert filmstrip_row_count(0.0, 60.0) == 1
    assert filmstrip_row_count(60.0, 60.0) == 1
    assert filmstrip_row_count(60.1, 60.0) == 2
    assert filmstrip_row_count(130.0, 60.0) == 3


def test_review_summary_and_row_length_reflect_job(tmp_path):
    _app()
    widget = FilmstripReviewWidget()
    widget.set_job(_job(tmp_path))

    assert widget.summary_label.text() == "3シーン・分割 2か所・削除 1ゾーン"
    assert widget.canvas.seconds_per_row == 60.0
    assert widget.canvas.minimumHeight() == (
        widget.canvas.TOP_MARGIN * 2 + 3 * widget.canvas.ROW_HEIGHT
    )

    widget.row_length_combo.setCurrentIndex(2)

    assert widget.canvas.seconds_per_row == 120.0
    assert widget.canvas.minimumHeight() == (
        widget.canvas.TOP_MARGIN * 2 + 2 * widget.canvas.ROW_HEIGHT
    )
    widget.close()


def test_clicking_second_row_seeks_on_continuous_timeline(tmp_path):
    _app()
    canvas = FilmstripCanvas()
    canvas.set_job(_job(tmp_path))
    canvas.resize(900, canvas.minimumHeight())
    canvas.show()
    QApplication.processEvents()
    requested = []
    canvas.seek_requested.connect(requested.append)

    target_time = 90.0
    row = 1
    point = QPoint(
        canvas._time_to_x(target_time, row),
        canvas.TOP_MARGIN + row * canvas.ROW_HEIGHT + canvas.IMAGE_TOP + 5,
    )
    QTest.mouseClick(canvas, Qt.LeftButton, pos=point)

    assert requested
    assert abs(requested[-1] - target_time) < 0.1
    assert abs(canvas.playhead_position - target_time) < 0.1
    canvas.close()


def test_keyboard_can_seek_and_return_to_editor(tmp_path):
    _app()
    canvas = FilmstripCanvas()
    canvas.set_job(_job(tmp_path))
    canvas.set_playhead(60.0)
    canvas.show()
    canvas.setFocus()
    seeks = []
    edits = []
    canvas.seek_requested.connect(seeks.append)
    canvas.edit_requested.connect(edits.append)

    QTest.keyClick(canvas, Qt.Key_Right)
    QTest.keyClick(canvas, Qt.Key_Return)

    assert seeks == [61.0]
    assert edits == [61.0]
    canvas.close()


def test_timeline_only_shows_boundary_review_when_a_boundary_exists():
    _app()
    timeline = TimelineWidget()
    timeline.set_scenes([0.0], 120.0)

    assert timeline.btn_filmstrip_review.isEnabled() is True
    assert timeline.btn_review_boundary.isHidden() is True

    timeline.add_boundary(30.0)
    assert timeline.btn_review_boundary.isHidden() is False

    timeline.replace_boundaries([0.0])
    assert timeline.btn_review_boundary.isHidden() is True
    timeline.close()


def test_main_window_switches_between_editor_and_filmstrip(tmp_path):
    _app()
    window = MainWindow()
    job = _job(tmp_path)
    window.current_job = job
    window._show_editor_layout()
    window.clip_list_widget.set_job(job)
    window._update_timeline(job)
    window.timeline_widget.set_detection_preview([44.0])

    window.timeline_widget.btn_filmstrip_review.click()

    assert window.workspace_stack.currentWidget() is window.filmstrip_review_widget
    assert window.filmstrip_review_widget.canvas.candidate_times == [18.0, 44.0, 92.0]

    sought = []
    window.preview_widget.seek_to = sought.append
    window._on_filmstrip_edit_requested(81.5)

    assert sought == [81.5]
    assert window.workspace_stack.currentWidget() is window.editor_splitter
    window.close()
