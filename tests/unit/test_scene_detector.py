import sys
import types
from pathlib import Path

from app.core.scene_detector import (
    SceneDetectionSettings,
    absorb_short_scenes,
    detect_scene_boundaries,
    merge_boundaries,
    scene_list_to_boundaries,
)


class FakeTimecode:
    def __init__(self, seconds):
        self.seconds = seconds

    def get_seconds(self):
        return self.seconds


def test_scene_list_to_boundaries_skips_start_and_end():
    scene_list = [
        (FakeTimecode(0.0), FakeTimecode(10.0)),
        (FakeTimecode(10.0), FakeTimecode(20.0)),
        (FakeTimecode(99.5), FakeTimecode(100.0)),
    ]

    boundaries = scene_list_to_boundaries(
        scene_list,
        duration=100.0,
        min_boundary_gap_seconds=1.0,
    )

    assert boundaries == [0.0, 10.0]


def test_merge_boundaries_keeps_existing_and_skips_near_duplicates():
    merged = merge_boundaries(
        existing=[0.0, 10.0],
        detected=[10.1, 20.0, 99.0],
        duration=60.0,
        tolerance_seconds=0.25,
    )

    assert merged == [0.0, 10.0, 20.0]


def test_absorb_short_scenes_merges_consecutive_short_scenes():
    # 10-12, 12-13.5, 13.5-15 が細切れ。まず短い同士がまとまり、
    # 最終的に min(3.0) を満たすまで統合される
    boundaries = [0.0, 10.0, 12.0, 13.5, 15.0, 30.0]

    result = absorb_short_scenes(boundaries, duration=60.0, min_scene_duration=3.0)

    assert result[0] == 0.0
    assert all(
        b2 - b1 >= 3.0
        for b1, b2 in zip(result, result[1:] + [60.0])
    )
    # 長いシーンの境界は維持される
    assert 10.0 in result
    assert 30.0 in result


def test_absorb_short_scenes_short_first_scene_merges_forward():
    # 先頭シーン(0-1秒)は次のシーンと統合される
    result = absorb_short_scenes([0.0, 1.0, 20.0], duration=40.0, min_scene_duration=3.0)

    assert result == [0.0, 20.0]


def test_absorb_short_scenes_short_last_scene_merges_backward():
    # 末尾シーン(39-40秒)は前のシーンと統合される
    result = absorb_short_scenes([0.0, 20.0, 39.0], duration=40.0, min_scene_duration=3.0)

    assert result == [0.0, 20.0]


def test_absorb_short_scenes_disabled_when_zero():
    boundaries = [0.0, 0.5, 1.0]

    result = absorb_short_scenes(boundaries, duration=10.0, min_scene_duration=0.0)

    assert result == [0.0, 0.5, 1.0]


def test_absorb_short_scenes_collapses_to_single_scene_when_all_short():
    result = absorb_short_scenes([0.0, 1.0, 2.0], duration=3.0, min_scene_duration=10.0)

    assert result == [0.0]


def _install_fake_scenedetect(monkeypatch, frame_count=10):
    """フレームごとに detector.process_frame を呼ぶ偽の scenedetect を注入する"""
    fake = types.ModuleType("scenedetect")

    class _BaseDetector:
        def __init__(self, **kwargs):
            pass

        def process_frame(self, frame_num, frame_img):
            return []

    class _FakeDuration:
        def __init__(self, frames):
            self._frames = frames

        def get_frames(self):
            return self._frames

    class _FakeVideo:
        def __init__(self, frames):
            self.duration = _FakeDuration(frames)

    def open_video(path):
        return _FakeVideo(frame_count)

    class SceneManager:
        def __init__(self):
            self._detectors = []

        def add_detector(self, detector):
            self._detectors.append(detector)

        def detect_scenes(self, video=None, **kwargs):
            for i in range(frame_count):
                for detector in self._detectors:
                    detector.process_frame(i, None)
            return frame_count

        def get_scene_list(self, **kwargs):
            return []

    fake.AdaptiveDetector = _BaseDetector
    fake.ContentDetector = _BaseDetector
    fake.SceneManager = SceneManager
    fake.open_video = open_video
    monkeypatch.setitem(sys.modules, "scenedetect", fake)


def test_detect_scene_boundaries_returns_boundaries_without_cancel(monkeypatch):
    _install_fake_scenedetect(monkeypatch)

    boundaries = detect_scene_boundaries(
        Path("dummy.mp4"),
        duration=100.0,
        cancel_callback=lambda: False,
    )

    assert boundaries == [0.0]


def test_detect_scene_boundaries_reports_progress(monkeypatch):
    _install_fake_scenedetect(monkeypatch, frame_count=200)
    percents = []

    boundaries = detect_scene_boundaries(
        Path("dummy.mp4"),
        duration=100.0,
        progress_callback=percents.append,
    )

    assert boundaries == [0.0]
    # 進捗は0から単調増加し、1%刻みで重複なく報告される
    assert percents[0] == 0
    assert percents[-1] == 99
    assert percents == sorted(set(percents))


def test_detect_scene_boundaries_aborts_on_cancel(monkeypatch):
    _install_fake_scenedetect(monkeypatch, frame_count=1000)
    calls = {"count": 0}

    def cancel_after_three():
        calls["count"] += 1
        return calls["count"] > 3

    boundaries = detect_scene_boundaries(
        Path("dummy.mp4"),
        duration=100.0,
        cancel_callback=cancel_after_three,
    )

    # キャンセルでNoneが返り、全フレームを処理せず早期に打ち切られる
    assert boundaries is None
    assert calls["count"] < 1000


def test_absorb_short_scenes_respects_protected_boundaries():
    # 12-13.5 が短いが、その境界(12.0, 13.5)を保護したので統合されない
    boundaries = [0.0, 10.0, 12.0, 13.5, 30.0]

    result = absorb_short_scenes(
        boundaries, duration=60.0, min_scene_duration=3.0,
        protected_times=[12.0, 13.5],
    )

    assert 12.0 in result
    assert 13.5 in result


def test_absorb_short_scenes_protected_does_not_pull_neighbours_across():
    # 短い保護シーン(10-11)を挟んでも、隣の短い破片同士のみが処理され、
    # 保護境界(10.0, 11.0)は残る
    boundaries = [0.0, 10.0, 11.0, 12.0, 30.0]

    result = absorb_short_scenes(
        boundaries, duration=60.0, min_scene_duration=3.0,
        protected_times=[10.0, 11.0],
    )

    assert 10.0 in result
    assert 11.0 in result
