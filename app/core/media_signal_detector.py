"""音声の無音区間と映像フェードを、非破壊の確認候補へ変換する。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable, Optional

from app.core.jobs import VideoJob
from app.core.scene_detector import SceneDetectionSettings, detect_scene_boundaries


@dataclass(frozen=True)
class MediaSignalResult:
    silence_ranges: list[tuple[float, float]]
    fade_times: list[float]
    candidate_times: list[float]


_SILENCE_START = re.compile(r"silence_start:\s*([0-9.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*([0-9.]+)")


def parse_silencedetect_output(
    output: str, duration: float
) -> list[tuple[float, float]]:
    """FFmpeg silencedetect のログを開始・終了秒へ変換する。"""
    ranges: list[tuple[float, float]] = []
    current_start: float | None = None
    for line in output.splitlines():
        start_match = _SILENCE_START.search(line)
        if start_match:
            current_start = float(start_match.group(1))
        end_match = _SILENCE_END.search(line)
        if end_match and current_start is not None:
            end = min(float(end_match.group(1)), duration)
            if end > current_start:
                ranges.append((current_start, end))
            current_start = None
    if current_start is not None and duration > current_start:
        ranges.append((current_start, duration))
    return ranges


def build_media_signal_result(
    existing_boundaries: list[float],
    duration: float,
    silence_ranges: list[tuple[float, float]],
    fade_times: list[float],
    boundary_tolerance: float = 0.5,
) -> MediaSignalResult:
    """検出時刻を既存境界と重ならない候補へ整理する。"""
    raw_candidates = [
        time
        for start, end in silence_ranges
        for time in (start, end)
    ] + list(fade_times)
    candidates: list[float] = []
    for time in sorted(raw_candidates):
        value = round(float(time), 3)
        if value <= 1.0 or value >= duration - 1.0:
            continue
        if any(abs(value - boundary) <= boundary_tolerance for boundary in existing_boundaries):
            continue
        if any(abs(value - candidate) <= boundary_tolerance for candidate in candidates):
            continue
        candidates.append(value)
    return MediaSignalResult(
        silence_ranges=[(float(start), float(end)) for start, end in silence_ranges],
        fade_times=sorted({round(float(time), 3) for time in fade_times}),
        candidate_times=candidates,
    )


def apply_media_signal_result(job: VideoJob, result: MediaSignalResult) -> None:
    """解析結果を確認理由と未適用の境界候補としてジョブへ保存する。"""
    for scene in job.scenes:
        retained = [
            flag for flag in scene.analysis_flags if flag not in ("silence", "fade")
        ]
        scene.reviewed_flags = [
            flag for flag in scene.reviewed_flags if flag not in ("silence", "fade")
        ]
        has_silence = any(
            min(scene.end_time, end) - max(scene.start_time, start) > 0.0
            for start, end in result.silence_ranges
        )
        has_fade = any(
            scene.start_time <= time < scene.end_time for time in result.fade_times
        )
        if has_silence:
            retained.append("silence")
        if has_fade:
            retained.append("fade")
        scene.analysis_flags = retained
    job.suggested_boundaries = list(result.candidate_times)


def detect_fade_times(
    video_path: Path,
    duration: float,
    cancel_callback: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> list[float]:
    """明暗のしきい値をまたぐフェード位置を検出する。"""
    boundaries = detect_scene_boundaries(
        video_path,
        duration=duration,
        settings=SceneDetectionSettings(
            detector="threshold",
            threshold_value=12.0,
            min_scene_len_frames=30,
            min_boundary_gap_seconds=1.0,
        ),
        cancel_callback=cancel_callback,
        progress_callback=progress_callback,
    )
    if boundaries is None:
        return []
    return boundaries[1:]
