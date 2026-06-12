import sys
import types
from pathlib import Path

from app.core.scene_detector import (
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


def _install_fake_scenedetect(monkeypatch, frame_count=10):
    """フレームごとに detector.process_frame を呼ぶ偽の scenedetect を注入する"""
    fake = types.ModuleType("scenedetect")

    class _BaseDetector:
        def __init__(self, **kwargs):
            pass

        def process_frame(self, frame_num, frame_img):
            return []

    def detect(video_path, detector):
        for i in range(frame_count):
            detector.process_frame(i, None)
        return []

    fake.AdaptiveDetector = _BaseDetector
    fake.ContentDetector = _BaseDetector
    fake.detect = detect
    monkeypatch.setitem(sys.modules, "scenedetect", fake)


def test_detect_scene_boundaries_returns_boundaries_without_cancel(monkeypatch):
    _install_fake_scenedetect(monkeypatch)

    boundaries = detect_scene_boundaries(
        Path("dummy.mp4"),
        duration=100.0,
        cancel_callback=lambda: False,
    )

    assert boundaries == [0.0]


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
