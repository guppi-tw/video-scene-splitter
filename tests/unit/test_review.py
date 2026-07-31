from datetime import date
from pathlib import Path

from app.core.jobs import Scene, VideoJob
from app.core.review import pending_review_issues


def test_review_issues_explain_why_a_scene_needs_attention():
    job = VideoJob(id=1, source_path=Path("family.mp4"))
    scene = Scene(
        index=1,
        start_time=0.0,
        end_time=2.0,
        event_date=date(1998, 8, 12),
        date_source="inferred",
        analysis_flags=["silence", "fade"],
    )
    job.scenes = [scene]

    issues = pending_review_issues(job, scene)

    assert [issue.code for issue in issues] == [
        "short_scene",
        "date_inferred",
        "silence",
        "fade",
    ]
    assert [issue.label for issue in issues] == [
        "3秒未満",
        "推定日付: 1998/08/12",
        "長い無音",
        "フェード候補",
    ]


def test_ocr_detected_date_is_a_review_item_with_the_actual_value():
    job = VideoJob(id=1, source_path=Path("family.mp4"))
    scene = Scene(
        index=1,
        start_time=0.0,
        end_time=8.0,
        event_date=date(1998, 8, 12),
        date_source="detected",
    )
    job.scenes = [scene]

    issues = pending_review_issues(job, scene)

    assert [(issue.code, issue.label) for issue in issues] == [
        ("date_detected", "検出日付: 1998/08/12")
    ]
