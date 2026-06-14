"""
main_window.py の自動後処理パイプライン順序テスト
"""
from types import SimpleNamespace

from app.core.jobs import JobStatus, Scene, VideoJob
from app.ui.main_window import MainWindow


class _LogStub:
    def hide_progress(self):
        pass

    def set_status(self, _message):
        pass


class _ClipListStub:
    def set_blank_detecting(self, _detecting):
        pass


def _blank_finished_window(*, manual: bool, propose_merge: bool, segments: list):
    worker = object()
    calls = []

    def start_date_detection(auto):
        calls.append(("date", auto))
        return True

    window = SimpleNamespace(
        blank_detection_worker=worker,
        blank_detection_thread=None,
        log_widget=_LogStub(),
        clip_list_widget=_ClipListStub(),
        current_job=SimpleNamespace(filename="video.mp4"),
        _blank_manual=manual,
        _pending_blank_segments=segments,
        _propose_merge_after_blank=propose_merge,
        sender=lambda: worker,
    )
    window._apply_blank_segments = lambda found: calls.append(("blank", found))
    window._propose_short_scene_merge = lambda: calls.append(("merge", None))
    window._start_date_detection = start_date_detection
    window._finish_deferred_thumbnails = lambda: calls.append(("thumbnails", None))
    return window, calls


def test_auto_blank_finished_runs_blank_merge_date_in_order():
    """自動実行時は つなぎ目除外 -> 結合提案 -> 日付検出 の順に固定する"""
    segments = [(1.0, 2.0, "黒")]
    window, calls = _blank_finished_window(
        manual=False,
        propose_merge=True,
        segments=segments,
    )

    MainWindow._on_blank_detect_finished(window)

    assert calls == [("blank", segments), ("merge", None), ("date", True)]
    assert window._pending_blank_segments is None


def test_manual_blank_finished_only_shows_blank_dialog():
    """手動つなぎ目検出では、結合提案や日付検出へ連鎖しない"""
    segments = [(3.0, 4.0, "青")]
    window, calls = _blank_finished_window(
        manual=True,
        propose_merge=True,
        segments=segments,
    )

    MainWindow._on_blank_detect_finished(window)

    assert calls == [("blank", segments)]
    assert window._pending_blank_segments is None


def test_queue_clip_preview_does_not_start_post_process_pipeline(tmp_path):
    """子クリップ選択のプレビューでは、自動後処理モーダルを起動しない"""
    video_path = tmp_path / "video.mp4"
    video_path.touch()
    job = VideoJob(id=1, source_path=video_path, status=JobStatus.REVIEW)
    job.scenes = [Scene(index=1, start_time=0.0, end_time=10.0)]
    job.needs_post_process = True
    calls = []

    window = SimpleNamespace(
        current_job=None,
        _on_job_selected=lambda selected: calls.append(("selected", selected.id)),
        _on_open_video=lambda _job: calls.append(("opened", _job.id)),
        preview_widget=SimpleNamespace(
            seek_to=lambda seconds: calls.append(("seek", seconds))
        ),
    )

    MainWindow._on_queue_clip_preview(window, job, 4.5)

    assert calls == [("selected", job.id), ("seek", 4.5)]
    assert job.needs_post_process is True


def test_thumbnail_regeneration_is_deferred_until_auto_post_process_finishes():
    calls = []
    window = SimpleNamespace(
        _defer_thumbnail_regen=False,
        _thumbnail_regen_pending=False,
        _stop_thumbnail_worker=lambda: calls.append("stop"),
        current_job=object(),
    )

    MainWindow._begin_deferred_thumbnails(window)
    MainWindow._regenerate_thumbnails(window)
    window._regenerate_thumbnails = lambda: calls.append("regenerate")
    MainWindow._finish_deferred_thumbnails(window)

    assert calls == ["stop", "regenerate"]
    assert window._defer_thumbnail_regen is False
    assert window._thumbnail_regen_pending is False
