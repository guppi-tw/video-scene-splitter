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
) -> Optional[list[float]]:
    """Detect scene boundaries using PySceneDetect.

    cancel_callback is polled once per decoded frame; when it returns True
    detection aborts promptly and this function returns None.
    """
    settings = settings or SceneDetectionSettings()

    try:
        from scenedetect import AdaptiveDetector, ContentDetector, detect
    except ImportError as exc:
        raise SceneDetectionDependencyError(
            "PySceneDetectがインストールされていません。requirements.txt を再インストールしてください。"
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

    if cancel_callback is not None:
        original_process_frame = detector.process_frame

        def process_frame_with_cancel(frame_num, frame_img):
            if cancel_callback():
                raise SceneDetectionCancelled()
            return original_process_frame(frame_num, frame_img)

        detector.process_frame = process_frame_with_cancel

    try:
        scene_list = detect(str(video_path), detector)
    except SceneDetectionCancelled:
        return None

    return scene_list_to_boundaries(
        scene_list,
        duration=duration,
        min_boundary_gap_seconds=settings.min_boundary_gap_seconds,
    )


def _dedupe_sorted_boundaries(boundaries: Iterable[float]) -> list[float]:
    deduped = sorted({round(float(boundary), 3) for boundary in boundaries})
    if not deduped or deduped[0] != 0.0:
        deduped.insert(0, 0.0)
    return deduped
