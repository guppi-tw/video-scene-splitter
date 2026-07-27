"""ユーザー編集をUndo/Redoするためのジョブスナップショット。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from typing import Optional

from app.core.jobs import Scene, VideoJob


@dataclass(frozen=True)
class JobEditSnapshot:
    default_event_name: str
    default_event_date: Optional[date]
    auto_split_enabled: bool
    scenes: list[Scene]

    @classmethod
    def capture(cls, job: VideoJob) -> "JobEditSnapshot":
        return cls(
            default_event_name=job.default_event_name,
            default_event_date=job.default_event_date,
            auto_split_enabled=job.auto_split_enabled,
            scenes=deepcopy(job.scenes),
        )

    def apply_to(self, job: VideoJob) -> None:
        job.default_event_name = self.default_event_name
        job.default_event_date = self.default_event_date
        job.auto_split_enabled = self.auto_split_enabled
        job.scenes = deepcopy(self.scenes)
