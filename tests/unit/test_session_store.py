from datetime import date

from app.core.jobs import JobQueue, JobStatus, Scene
from app.core.session_store import SessionStore


def test_session_round_trip_restores_queue_and_editable_state(tmp_path):
    source = tmp_path / "family.mp4"
    source.touch()
    output = tmp_path / "exports"

    queue = JobQueue()
    job = queue.add_file(source)
    job.status = JobStatus.REVIEW
    job.default_event_name = "夏休み"
    job.default_event_date = date(1998, 8, 12)
    job.output_dir = output
    job.auto_split_enabled = False
    job.needs_post_process = True
    job.scenes = [
        Scene(
            index=1,
            start_time=0.0,
            end_time=12.5,
            keep=False,
            is_sensitive=True,
            event_name="海辺",
            event_date=date(1998, 8, 13),
            filename_override="海辺_01",
        )
    ]

    store = SessionStore(tmp_path / "session.json")
    store.save(queue, current_job_id=job.id)
    restored = store.load()

    assert restored.current_job_id == job.id
    assert len(restored.job_queue.get_all_jobs()) == 1
    loaded = restored.job_queue.get_job_by_id(job.id)
    assert loaded.source_path == source
    assert loaded.status == JobStatus.REVIEW
    assert loaded.default_event_name == "夏休み"
    assert loaded.default_event_date == date(1998, 8, 12)
    assert loaded.output_dir == output
    assert loaded.auto_split_enabled is False
    assert loaded.needs_post_process is True
    assert loaded.scenes == [
        Scene(
            index=1,
            start_time=0.0,
            end_time=12.5,
            keep=False,
            is_sensitive=True,
            event_name="海辺",
            event_date=date(1998, 8, 13),
            filename_override="海辺_01",
        )
    ]

    next_source = tmp_path / "next.mp4"
    next_source.touch()
    next_job = restored.job_queue.add_file(next_source)
    assert next_job.id == job.id + 1


def test_corrupt_session_fails_safe_without_crashing(tmp_path):
    path = tmp_path / "session.json"
    path.write_text("{broken", encoding="utf-8")

    restored = SessionStore(path).load()

    assert restored.job_queue.get_all_jobs() == []
    assert restored.current_job_id is None
    assert restored.warning
