from datetime import date
from pathlib import Path

from app.core.jobs import Scene, VideoJob
from app.core.media_signal_detector import (
    apply_media_signal_result,
    build_media_signal_result,
    parse_silencedetect_output,
)
from app.core.review import acknowledge_review_issues, pending_review_issues
from app.ui.workers import MediaSignalWorker


def test_silence_output_becomes_review_flags_and_boundary_candidates():
    output = """
[silencedetect @ 0x1] silence_start: 4.0
[silencedetect @ 0x1] silence_end: 6.0 | silence_duration: 2.0
[silencedetect @ 0x1] silence_start: 18.0
"""
    silence_ranges = parse_silencedetect_output(output, duration=20.0)
    result = build_media_signal_result(
        existing_boundaries=[0.0, 10.0],
        duration=20.0,
        silence_ranges=silence_ranges,
        fade_times=[10.2, 15.0],
    )
    job = VideoJob(
        id=1,
        source_path=Path("family.mp4"),
        scenes=[
            Scene(index=1, start_time=0.0, end_time=10.0),
            Scene(index=2, start_time=10.0, end_time=20.0),
        ],
    )

    apply_media_signal_result(job, result)

    assert silence_ranges == [(4.0, 6.0), (18.0, 20.0)]
    assert result.candidate_times == [4.0, 6.0, 15.0, 18.0]
    assert job.scenes[0].analysis_flags == ["silence"]
    assert job.scenes[1].analysis_flags == ["silence", "fade"]
    assert job.suggested_boundaries == [4.0, 6.0, 15.0, 18.0]


def test_media_signal_worker_combines_audio_and_fade_analysis():
    job = VideoJob(
        id=1,
        source_path=Path("family.mp4"),
        scenes=[Scene(index=1, start_time=0.0, end_time=20.0)],
    )

    class FakeAudio:
        def detect_silence(self, _path, duration):
            assert duration == 20.0
            return [(4.0, 6.0)]

        def cancel(self):
            pass

    worker = MediaSignalWorker(
        job,
        duration=20.0,
        ffmpeg=FakeAudio(),
        fade_detector=lambda *_args, **_kwargs: [10.0, 15.0],
    )
    completed = []
    worker.analysis_complete.connect(completed.append)

    worker.run()

    assert completed[0].silence_ranges == [(4.0, 6.0)]
    assert completed[0].fade_times == [10.0, 15.0]
    assert completed[0].candidate_times == [4.0, 6.0, 10.0, 15.0]


def test_rerunning_media_analysis_reopens_changed_findings():
    job = VideoJob(
        id=1,
        source_path=Path("family.mp4"),
        default_event_date=date(1998, 8, 12),
        scenes=[Scene(index=1, start_time=0.0, end_time=10.0)],
    )
    found = build_media_signal_result([0.0], 10.0, [(3.0, 5.0)], [])
    empty = build_media_signal_result([0.0], 10.0, [], [])

    apply_media_signal_result(job, found)
    acknowledge_review_issues(job, job.scenes[0])
    assert not pending_review_issues(job, job.scenes[0])

    apply_media_signal_result(job, empty)
    apply_media_signal_result(job, found)

    assert [issue.code for issue in pending_review_issues(job, job.scenes[0])] == [
        "silence",
    ]
