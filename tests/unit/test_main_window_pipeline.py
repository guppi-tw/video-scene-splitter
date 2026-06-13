"""
main_window.py の自動後処理パイプライン順序テスト
"""
from types import SimpleNamespace

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
    window._start_date_detection = lambda auto: calls.append(("date", auto))
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
