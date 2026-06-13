"""
一括シーン検出ワーカーのエラー処理テスト
"""
from pathlib import Path

from app.core.jobs import JobStatus, VideoJob
from app.ui import workers


def test_batch_detection_continues_after_one_video_error(monkeypatch):
    jobs = [
        VideoJob(id=1, source_path=Path("/tmp/broken.mp4")),
        VideoJob(id=2, source_path=Path("/tmp/ok.mp4")),
    ]

    class FakeRunner:
        def get_video_duration(self, _path):
            return 20.0

    def fake_detect_scene_boundaries(path, **_kwargs):
        if path.name == "broken.mp4":
            raise RuntimeError("Error -3 while decompressing data: incorrect header check")
        return [0.0, 10.0]

    monkeypatch.setattr(workers, "FFmpegRunner", FakeRunner)
    monkeypatch.setattr(workers, "detect_scene_boundaries", fake_detect_scene_boundaries)

    worker = workers.BatchSceneDetectionWorker(jobs)
    errors = []
    done = []
    finished = []
    worker.error.connect(errors.append)
    worker.video_done.connect(lambda job_id, scene_count: done.append((job_id, scene_count)))
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    assert errors == [
        "broken.mp4: Error -3 while decompressing data: incorrect header check"
    ]
    assert jobs[0].status == JobStatus.ERROR
    assert jobs[0].error_message == "Error -3 while decompressing data: incorrect header check"
    assert jobs[1].status == JobStatus.REVIEW
    assert jobs[1].needs_post_process is True
    assert done == [(2, 2)]
    assert finished == [True]


def test_batch_detection_marks_duration_failure_as_job_error(monkeypatch):
    job = VideoJob(id=1, source_path=Path("/tmp/no-duration.mp4"))

    class FakeRunner:
        def get_video_duration(self, _path):
            return None

    monkeypatch.setattr(workers, "FFmpegRunner", FakeRunner)

    worker = workers.BatchSceneDetectionWorker([job])
    errors = []
    worker.error.connect(errors.append)

    worker.run()

    assert errors == ["no-duration.mp4: 動画の長さを取得できませんでした"]
    assert job.status == JobStatus.ERROR
    assert job.error_message == "動画の長さを取得できませんでした"
