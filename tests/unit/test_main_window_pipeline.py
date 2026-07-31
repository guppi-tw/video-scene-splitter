"""
main_window.py の自動後処理パイプライン順序テスト
"""
from datetime import date
from types import SimpleNamespace

from app.core.jobs import JobStatus, Scene, VideoJob
from app.ui import main_window as main_window_module
from app.ui.main_window import MainWindow, _boundaries_equal
from PySide6.QtWidgets import QMessageBox


class _LogStub:
    def hide_progress(self):
        pass

    def set_status(self, _message):
        pass


class _ClipListStub:
    def set_blank_detecting(self, _detecting):
        pass


def _blank_finished_window(*, segments: list):
    worker = object()
    calls = []

    window = SimpleNamespace(
        blank_detection_worker=worker,
        blank_detection_thread=None,
        log_widget=_LogStub(),
        clip_list_widget=_ClipListStub(),
        current_job=SimpleNamespace(filename="video.mp4"),
        _pending_blank_segments=segments,
        sender=lambda: worker,
    )
    window._apply_blank_segments = lambda found: calls.append(("blank", found))
    return window, calls


def test_manual_blank_finished_only_shows_blank_dialog():
    """つなぎ目検出は、選んだ補正以外のモーダルへ連鎖しない"""
    segments = [(3.0, 4.0, "青")]
    window, calls = _blank_finished_window(segments=segments)

    MainWindow._on_blank_detect_finished(window)

    assert calls == [("blank", segments)]
    assert window._pending_blank_segments is None


def test_queue_clip_preview_does_not_start_post_process_pipeline(tmp_path):
    """子クリップ選択のプレビューではバックグラウンド処理を起動しない"""
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


def test_same_job_selection_does_not_reload_or_regenerate_thumbnails(tmp_path):
    video_path = tmp_path / "video.mp4"
    video_path.touch()
    job = VideoJob(id=1, source_path=video_path, status=JobStatus.REVIEW)
    calls = []
    window = SimpleNamespace(
        current_job=job,
        clip_list_widget=SimpleNamespace(set_job=lambda _job: calls.append("set_job")),
        preview_widget=SimpleNamespace(load_video=lambda _path: calls.append("load")),
        _update_timeline=lambda _job: calls.append("timeline"),
        _undo_stack=[],
        _last_boundaries=[],
        _regenerate_thumbnails=lambda: calls.append("thumbs"),
    )

    MainWindow._on_job_selected(window, job)

    assert calls == []


def test_boundaries_changed_noops_when_boundaries_are_unchanged():
    calls = []
    job = SimpleNamespace(
        scenes=[SimpleNamespace(start_time=0.0, end_time=10.0)],
        rebuild_scenes_from_boundaries=lambda *_args: calls.append("rebuild"),
    )
    window = SimpleNamespace(
        current_job=job,
        _last_boundaries=[0.0],
        _undo_stack=[],
        clip_list_widget=SimpleNamespace(refresh_clips=lambda: calls.append("refresh")),
        _regenerate_thumbnails=lambda: calls.append("thumbs"),
        log_widget=SimpleNamespace(append_log=lambda _message: calls.append("log")),
    )

    MainWindow._on_boundaries_changed(window, [0.0])

    assert calls == []
    assert _boundaries_equal([0.0, 1.0], [0.0, 1.0])


def test_remove_job_requires_confirmation(monkeypatch, tmp_path):
    """誤操作でキューと編集内容を即時削除しない"""
    video_path = tmp_path / "video.mp4"
    video_path.touch()
    queue = main_window_module.JobQueue()
    job = queue.add_file(video_path)
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.No,
    )
    window = SimpleNamespace(
        export_thread=None,
        export_worker=None,
        job_queue=queue,
    )

    MainWindow._on_remove_job(window, job.id)

    assert queue.get_job_by_id(job.id) is job


def test_auto_merge_protects_output_setting_boundaries(tmp_path):
    """短いシーンの自動結合で日付や要注意の境界を越えない"""
    video_path = tmp_path / "video.mp4"
    video_path.touch()
    job = VideoJob(
        id=1,
        source_path=video_path,
        status=JobStatus.REVIEW,
        scenes=[
            Scene(
                index=1,
                start_time=0.0,
                end_time=4.0,
                event_date=date(2024, 8, 1),
            ),
            Scene(
                index=2,
                start_time=4.0,
                end_time=8.0,
                event_date=date(2024, 8, 2),
            ),
            Scene(
                index=3,
                start_time=8.0,
                end_time=12.0,
                event_date=date(2024, 8, 2),
                is_sensitive=True,
            ),
        ],
    )
    window = SimpleNamespace(current_job=job)

    protected = MainWindow._protected_boundaries_from_clip_state(window)

    assert protected == [4.0, 8.0]


def test_detect_all_start_builds_batch_worker_without_open_video_state(monkeypatch, tmp_path):
    video_path = tmp_path / "video.mp4"
    video_path.touch()
    job = VideoJob(id=1, source_path=video_path, status=JobStatus.WAITING)
    calls = []

    class SignalStub:
        def connect(self, _slot):
            calls.append("connect")

    class FakeThread:
        def __init__(self):
            self.started = SignalStub()

        def start(self):
            calls.append("thread_start")

    class FakeWorker:
        def __init__(self, jobs, settings):
            calls.append(("worker", [j.id for j in jobs], settings))
            self.progress = SignalStub()
            self.progress_percent = SignalStub()
            self.video_done = SignalStub()
            self.error = SignalStub()
            self.finished = SignalStub()

        def moveToThread(self, _thread):
            calls.append("move_worker")

        def run(self):
            pass

    class FakeBatchProgressDialog:
        def __init__(self, total, _parent):
            calls.append(("dialog", total))
            self.cancel_requested = SignalStub()

        def show(self):
            calls.append("dialog_show")

    monkeypatch.setattr(main_window_module, "QThread", FakeThread)
    monkeypatch.setattr(
        main_window_module, "BatchSceneDetectionWorker", FakeWorker
    )
    monkeypatch.setattr(
        main_window_module, "BatchProgressDialog", FakeBatchProgressDialog
    )

    window = SimpleNamespace(
        batch_detection_thread=None,
        batch_detection_worker=None,
        batch_progress_dialog=None,
        job_queue=SimpleNamespace(get_all_jobs=lambda: [job]),
        timeline_widget=SimpleNamespace(get_detection_settings=lambda: "settings"),
        log_widget=SimpleNamespace(
            clear_log=lambda: calls.append("clear_log"),
            set_status=lambda message: calls.append(("status", message)),
            append_log=lambda message: calls.append(("log", message)),
        ),
        queue_widget=SimpleNamespace(
            set_detect_all_enabled=lambda enabled: calls.append(("detect_all", enabled))
        ),
        _on_batch_detect_progress=lambda _message: None,
        _on_batch_detect_percent=lambda _percent: None,
        _on_batch_video_done=lambda _job_id, _scene_count: None,
        _on_batch_detect_error=lambda _message: None,
        _on_batch_detect_finished=lambda: None,
        _on_batch_detect_cancel=lambda: None,
    )

    MainWindow._on_detect_all_requested(window)

    assert ("worker", [1], "settings") in calls
    assert "thread_start" in calls


def test_detect_all_button_reopens_running_progress_without_warning(monkeypatch):
    calls = []

    class RunningThread:
        def isRunning(self):
            return True

    dialog = SimpleNamespace(
        show=lambda: calls.append("show"),
        raise_=lambda: calls.append("raise"),
        activateWindow=lambda: calls.append("activate"),
    )
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "warning",
        lambda *_args, **_kwargs: calls.append("warning"),
    )
    window = SimpleNamespace(
        batch_detection_thread=RunningThread(),
        batch_progress_dialog=dialog,
    )

    MainWindow._on_detect_all_requested(window)

    assert calls == ["show", "raise", "activate"]
