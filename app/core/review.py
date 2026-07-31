"""人が確認すべきクリップを理由付きで絞り込む。"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.jobs import Scene, VideoJob


@dataclass(frozen=True)
class ReviewIssue:
    code: str
    label: str


_ISSUE_ORDER = (
    "short_scene",
    "date_missing",
    "date_inferred",
    "silence",
    "fade",
    "blank",
)

_ISSUE_LABELS = {
    "short_scene": "3秒未満",
    "date_missing": "日付未設定",
    "date_inferred": "日付は推定",
    "silence": "長い無音",
    "fade": "フェード候補",
    "blank": "単色つなぎ目",
}


def review_issue_codes(job: VideoJob, scene: Scene) -> list[str]:
    """現在の状態から、確認理由コードを安定した順序で返す。"""
    codes = set(scene.analysis_flags)
    if scene.duration < 3.0:
        codes.add("short_scene")
    _name, event_date = job.get_scene_metadata(scene.index)
    if event_date is None:
        codes.add("date_missing")
    if scene.date_source == "inferred":
        codes.add("date_inferred")
    return [code for code in _ISSUE_ORDER if code in codes]


def pending_review_issues(job: VideoJob, scene: Scene) -> list[ReviewIssue]:
    """ユーザーがまだ確認済みにしていない理由を返す。"""
    acknowledged = set(scene.reviewed_flags)
    return [
        ReviewIssue(code, _ISSUE_LABELS[code])
        for code in review_issue_codes(job, scene)
        if code not in acknowledged
    ]


def pending_review_count(job: VideoJob) -> int:
    """未確認の理由が1つ以上あるクリップ数を返す。"""
    return sum(bool(pending_review_issues(job, scene)) for scene in job.scenes)


def acknowledge_review_issues(job: VideoJob, scene: Scene) -> None:
    """その時点で表示されている確認理由を確認済みにする。"""
    reviewed = set(scene.reviewed_flags)
    reviewed.update(review_issue_codes(job, scene))
    scene.reviewed_flags = [code for code in _ISSUE_ORDER if code in reviewed]
