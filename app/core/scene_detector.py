"""
Automatic scene boundary detection.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional


@dataclass
class SceneDetectionSettings:
    """Settings for PySceneDetect-backed boundary detection."""
    detector: str = "adaptive"
    adaptive_threshold: float = 3.0
    content_threshold: float = 27.0
    min_scene_len_frames: int = 30
    min_boundary_gap_seconds: float = 1.0
    # 検出後、これより短いシーンは隣のシーンに統合される（0で無効）
    min_scene_duration_seconds: float = 0.0


class SceneDetectionDependencyError(RuntimeError):
    """Raised when the optional scene detection dependency is unavailable."""


class SceneDetectionCancelled(Exception):
    """Raised internally to abort detection when the caller cancels."""


def _timecode_seconds(value) -> float:
    if hasattr(value, "get_seconds"):
        return float(value.get_seconds())
    return float(value)


def scene_list_to_boundaries(
    scene_list: Iterable[tuple[object, object]],
    duration: Optional[float] = None,
    min_boundary_gap_seconds: float = 1.0,
) -> list[float]:
    """Convert PySceneDetect scene tuples to timeline boundary start times."""
    boundaries = [0.0]

    for start_time, _ in scene_list:
        start_seconds = _timecode_seconds(start_time)
        if start_seconds <= min_boundary_gap_seconds:
            continue
        if duration is not None and start_seconds >= duration - min_boundary_gap_seconds:
            continue
        boundaries.append(start_seconds)

    return _dedupe_sorted_boundaries(boundaries)


def absorb_short_scenes(
    boundaries: Iterable[float],
    duration: float,
    min_scene_duration: float,
    protected_times: Iterable[float] = (),
) -> list[float]:
    """min_scene_duration秒未満のシーンを隣のシーンに統合した境界リストを返す。

    最も短いシーンから順に、隣接するシーンのうち短い方へ統合していく。
    細切れシーンが連続している場合も、まずそれら同士がまとまるため
    長いシーンが不必要に侵食されない。

    protected_times に渡した境界は削除しない。除外済みの単色つなぎ目シーンの
    境界を保護することで、つなぎ目を隣のシーンに飲み込んで再混入させない。
    """
    bounds = _dedupe_sorted_boundaries(boundaries)
    if min_scene_duration <= 0 or duration <= 0:
        return bounds

    protected = {round(float(t), 3) for t in protected_times}

    # 境界 + 終端でシーン区間を表す
    edges = [b for b in bounds if b < duration] + [duration]

    def _is_protected(edge_index: int) -> bool:
        # edges[-1] は終端（duration）なので保護対象に含めない
        if edge_index <= 0 or edge_index >= len(edges) - 1:
            return False
        return round(edges[edge_index], 3) in protected

    while len(edges) > 2:
        durations = [edges[i + 1] - edges[i] for i in range(len(edges) - 1)]
        # 短い順に、削除すべき境界が保護されていない最初のシーンを統合する
        order = sorted(range(len(durations)), key=lambda i: durations[i])
        progressed = False
        for shortest in order:
            if durations[shortest] >= min_scene_duration:
                break

            if shortest == 0:
                remove_index = 1
            elif shortest == len(durations) - 1:
                remove_index = shortest
            elif durations[shortest - 1] <= durations[shortest + 1]:
                remove_index = shortest
            else:
                remove_index = shortest + 1

            # 好みの統合方向が保護されている中間シーンは逆方向も試す
            if 0 < shortest < len(durations) - 1 and _is_protected(remove_index):
                alt = shortest + 1 if remove_index == shortest else shortest
                if not _is_protected(alt):
                    remove_index = alt

            if _is_protected(remove_index):
                continue

            del edges[remove_index]
            progressed = True
            break

        if not progressed:
            break

    return _dedupe_sorted_boundaries(edges[:-1])


def merge_boundaries(
    existing: Iterable[float],
    detected: Iterable[float],
    duration: float,
    tolerance_seconds: float = 0.25,
) -> list[float]:
    """Merge detected boundaries into existing ones without near-duplicates."""
    merged = _dedupe_sorted_boundaries(existing)

    for candidate in sorted(detected):
        if candidate <= 0.0 or candidate >= duration:
            continue
        if any(abs(candidate - current) <= tolerance_seconds for current in merged):
            continue
        merged.append(candidate)

    return _dedupe_sorted_boundaries(merged)


def detect_scene_boundaries(
    video_path: Path,
    duration: Optional[float] = None,
    settings: Optional[SceneDetectionSettings] = None,
    cancel_callback: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> Optional[list[float]]:
    """Detect scene boundaries using PySceneDetect.

    cancel_callback is polled once per decoded frame; when it returns True
    detection aborts promptly and this function returns None.
    progress_callback receives the progress percentage (0-100) and is called
    at most once per percentage point.
    """
    settings = settings or SceneDetectionSettings()

    try:
        from scenedetect import (
            AdaptiveDetector,
            ContentDetector,
            SceneManager,
            open_video,
        )
    except ImportError as exc:
        raise SceneDetectionDependencyError(
            "PySceneDetectを読み込めませんでした。requirements.txt を再インストールしてください。\n"
            f"詳細: {exc}"
        ) from exc

    if settings.detector == "content":
        detector = ContentDetector(
            threshold=settings.content_threshold,
            min_scene_len=settings.min_scene_len_frames,
        )
    else:
        detector = AdaptiveDetector(
            adaptive_threshold=settings.adaptive_threshold,
            min_scene_len=settings.min_scene_len_frames,
        )

    video = open_video(str(video_path))

    total_frames = 0
    try:
        if video.duration is not None:
            total_frames = int(video.duration.get_frames())
    except Exception:
        total_frames = 0

    if cancel_callback is not None or progress_callback is not None:
        original_process_frame = detector.process_frame
        last_percent = -1

        def process_frame_with_hooks(position, frame_img):
            nonlocal last_percent
            if cancel_callback is not None and cancel_callback():
                raise SceneDetectionCancelled()
            if progress_callback is not None and total_frames > 0:
                # position は FrameTimecode（古いAPIではint）
                frames = (
                    position.get_frames()
                    if hasattr(position, "get_frames")
                    else int(position)
                )
                percent = min(100, int(frames * 100 / total_frames))
                if percent != last_percent:
                    last_percent = percent
                    progress_callback(percent)
            return original_process_frame(position, frame_img)

        detector.process_frame = process_frame_with_hooks

    scene_manager = SceneManager()
    scene_manager.add_detector(detector)

    try:
        scene_manager.detect_scenes(video=video)
    except SceneDetectionCancelled:
        return None

    scene_list = scene_manager.get_scene_list()

    boundaries = scene_list_to_boundaries(
        scene_list,
        duration=duration,
        min_boundary_gap_seconds=settings.min_boundary_gap_seconds,
    )

    if duration is not None and settings.min_scene_duration_seconds > 0:
        boundaries = absorb_short_scenes(
            boundaries, duration, settings.min_scene_duration_seconds
        )

    return boundaries


def _dedupe_sorted_boundaries(boundaries: Iterable[float]) -> list[float]:
    deduped = sorted({round(float(boundary), 3) for boundary in boundaries})
    if not deduped or deduped[0] != 0.0:
        deduped.insert(0, 0.0)
    return deduped
