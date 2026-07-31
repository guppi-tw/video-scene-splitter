from datetime import date
from pathlib import Path

from app.core.jobs import Scene, VideoJob
from app.core.metadata import BulkMetadataUpdate, apply_bulk_metadata


def test_bulk_metadata_updates_selected_videos_and_their_clips():
    first = VideoJob(
        id=1,
        source_path=Path("tape-1.mp4"),
        scenes=[Scene(index=1, start_time=0.0, end_time=4.0)],
    )
    second = VideoJob(
        id=2,
        source_path=Path("tape-2.mp4"),
        scenes=[Scene(index=1, start_time=0.0, end_time=6.0)],
    )
    update = BulkMetadataUpdate(
        event_name="運動会",
        event_date=date(1998, 10, 10),
        set_event_name=True,
        set_event_date=True,
        apply_to_scenes=True,
    )

    changed = apply_bulk_metadata([first, second], update)

    assert changed == 2
    assert all(job.default_event_name == "運動会" for job in (first, second))
    assert all(job.default_event_date == date(1998, 10, 10) for job in (first, second))
    assert all(job.scenes[0].event_name == "運動会" for job in (first, second))
    assert all(job.scenes[0].date_source == "manual" for job in (first, second))
