"""複数動画へ同じ整理情報を安全に反映する。"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from app.core.jobs import VideoJob
from app.core.review import clear_date_review_acknowledgements


@dataclass(frozen=True)
class BulkMetadataUpdate:
    event_name: str = ""
    event_date: Optional[date] = None
    set_event_name: bool = False
    set_event_date: bool = False
    apply_to_scenes: bool = True


def apply_bulk_metadata(
    jobs: list[VideoJob], update: BulkMetadataUpdate
) -> int:
    """選択された動画へ更新を反映し、実際に変わった動画数を返す。"""
    changed_jobs = 0
    for job in jobs:
        changed = False
        default_date_changed = False
        if update.set_event_name and job.default_event_name != update.event_name:
            job.default_event_name = update.event_name
            changed = True
        if update.set_event_date and job.default_event_date != update.event_date:
            job.default_event_date = update.event_date
            changed = True
            default_date_changed = True

        if default_date_changed:
            for scene in job.scenes:
                clear_date_review_acknowledgements(scene)

        if update.apply_to_scenes:
            for scene in job.scenes:
                if update.set_event_name and scene.event_name != update.event_name:
                    scene.event_name = update.event_name
                    changed = True
                if update.set_event_date:
                    source = "manual" if update.event_date is not None else None
                    if (
                        scene.event_date != update.event_date
                        or scene.date_source != source
                    ):
                        scene.event_date = update.event_date
                        scene.date_source = source
                        changed = True
                    clear_date_review_acknowledgements(scene)

        if changed:
            changed_jobs += 1
    return changed_jobs
