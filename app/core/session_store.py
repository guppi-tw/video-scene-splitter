"""編集セッションの自動保存・復元。"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional

from app.core.jobs import Clip, JobQueue, JobStatus, Scene, VideoJob


SESSION_VERSION = 1


@dataclass(frozen=True)
class RestoredSession:
    job_queue: JobQueue
    current_job_id: Optional[int] = None
    warning: str = ""


def default_session_path() -> Path:
    """OSごとのユーザーデータ領域にセッション保存先を返す。"""
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        root = Path(
            os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")
        )
    return root / "VideoSceneSplitter" / "session.json"


def _date_to_json(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _date_from_json(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None


def _path_to_json(value: Optional[Path]) -> Optional[str]:
    return str(value) if value is not None else None


def _scene_to_json(scene: Scene) -> dict[str, Any]:
    return {
        "index": scene.index,
        "start_time": scene.start_time,
        "end_time": scene.end_time,
        # サムネイルは一時領域にあるため、復元後に再生成する。
        "keep": scene.keep,
        "is_sensitive": scene.is_sensitive,
        "event_name": scene.event_name,
        "event_date": _date_to_json(scene.event_date),
        "filename_override": scene.filename_override,
        "analysis_flags": list(scene.analysis_flags),
        "reviewed_flags": list(scene.reviewed_flags),
        "date_source": scene.date_source,
    }


def _scene_from_json(data: dict[str, Any]) -> Scene:
    return Scene(
        index=int(data["index"]),
        start_time=float(data["start_time"]),
        end_time=float(data["end_time"]),
        keep=bool(data.get("keep", True)),
        is_sensitive=bool(data.get("is_sensitive", False)),
        event_name=data.get("event_name"),
        event_date=_date_from_json(data.get("event_date")),
        filename_override=data.get("filename_override"),
        analysis_flags=[str(flag) for flag in data.get("analysis_flags", [])],
        reviewed_flags=[str(flag) for flag in data.get("reviewed_flags", [])],
        date_source=data.get("date_source"),
    )


def _clip_to_json(clip: Clip) -> dict[str, Any]:
    data = asdict(clip)
    data["event_date"] = _date_to_json(clip.event_date)
    data["output_path"] = _path_to_json(clip.output_path)
    return data


def _clip_from_json(data: dict[str, Any]) -> Clip:
    return Clip(
        index=int(data["index"]),
        start_time=float(data["start_time"]),
        end_time=float(data["end_time"]),
        source_scene_indices=[int(index) for index in data.get("source_scene_indices", [])],
        event_name=data.get("event_name", ""),
        event_date=_date_from_json(data.get("event_date")),
        is_sensitive=bool(data.get("is_sensitive", False)),
        output_path=Path(data["output_path"]) if data.get("output_path") else None,
        filename_override=data.get("filename_override"),
    )


def _job_to_json(job: VideoJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "source_path": str(job.source_path),
        "status": job.status.value,
        "default_event_name": job.default_event_name,
        "default_event_date": _date_to_json(job.default_event_date),
        "scenes": [_scene_to_json(scene) for scene in job.scenes],
        "clips": [_clip_to_json(clip) for clip in job.clips],
        "output_dir": _path_to_json(job.output_dir),
        "auto_split_enabled": job.auto_split_enabled,
        "export_preset": job.export_preset,
        "suggested_boundaries": list(job.suggested_boundaries),
        "error_message": job.error_message,
        "needs_post_process": job.needs_post_process,
    }


def _job_from_json(data: dict[str, Any]) -> VideoJob:
    source_path = Path(data["source_path"])
    raw_status = JobStatus(data.get("status", JobStatus.WAITING.value))
    scenes = [_scene_from_json(scene) for scene in data.get("scenes", [])]
    if raw_status == JobStatus.PROCESSING:
        raw_status = JobStatus.REVIEW if scenes else JobStatus.WAITING

    error_message = data.get("error_message", "")
    if not source_path.exists():
        raw_status = JobStatus.ERROR
        error_message = "元動画が見つかりません"

    auto_split_enabled = bool(data.get("auto_split_enabled", True))
    export_preset = data.get("export_preset")
    if not export_preset:
        export_preset = "share_fast" if auto_split_enabled else "archive_fast"

    return VideoJob(
        id=int(data["id"]),
        source_path=source_path,
        status=raw_status,
        default_event_name=data.get("default_event_name", ""),
        default_event_date=_date_from_json(data.get("default_event_date")),
        scenes=scenes,
        clips=[_clip_from_json(clip) for clip in data.get("clips", [])],
        output_dir=Path(data["output_dir"]) if data.get("output_dir") else None,
        auto_split_enabled=auto_split_enabled,
        export_preset=str(export_preset),
        suggested_boundaries=[
            float(value) for value in data.get("suggested_boundaries", [])
        ],
        error_message=error_message,
        needs_post_process=bool(data.get("needs_post_process", False)),
    )


class SessionStore:
    """JobQueueをバージョン付きJSONとして原子的に保存する。"""

    def __init__(self, path: Path):
        self.path = Path(path)

    def save(self, job_queue: JobQueue, current_job_id: Optional[int] = None) -> None:
        payload = {
            "version": SESSION_VERSION,
            "current_job_id": current_job_id,
            "jobs": [_job_to_json(job) for job in job_queue.get_all_jobs()],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def load(self) -> RestoredSession:
        if not self.path.exists():
            return RestoredSession(JobQueue())
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("version") != SESSION_VERSION:
                return RestoredSession(
                    JobQueue(),
                    warning="保存データの形式が新旧で一致しないため復元できませんでした",
                )
            jobs = [_job_from_json(job) for job in payload.get("jobs", [])]
            queue = JobQueue.from_jobs(jobs)
            current_job_id = payload.get("current_job_id")
            if queue.get_job_by_id(current_job_id) is None:
                current_job_id = None
            return RestoredSession(queue, current_job_id)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return RestoredSession(
                JobQueue(),
                warning=f"保存データを読み込めませんでした: {exc}",
            )
