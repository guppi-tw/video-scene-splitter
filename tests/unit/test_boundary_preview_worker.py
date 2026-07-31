from pathlib import Path

from app.core.jobs import VideoJob
from app.ui.workers import BoundaryPreviewWorker


class FakeFrames:
    def __init__(self):
        self.times = []

    def generate_thumbnail(self, _source, time_sec, output_path, width=320):
        self.times.append((time_sec, width))
        Path(output_path).write_bytes(b"image")
        return True

    def cancel(self):
        pass


def test_boundary_preview_worker_generates_frames_on_both_sides(tmp_path):
    source = tmp_path / "family.mp4"
    source.touch()
    frames = FakeFrames()
    worker = BoundaryPreviewWorker(
        VideoJob(id=7, source_path=source),
        boundary_time=4.0,
        duration=10.0,
        temp_dir=tmp_path,
        ffmpeg=frames,
    )
    ready = []
    worker.preview_ready.connect(lambda *args: ready.append(args))

    worker.run()

    assert frames.times == [(3.75, 320), (4.25, 320)]
    assert ready and ready[0][0] == 4.0
    assert Path(ready[0][1]).exists()
    assert Path(ready[0][2]).exists()
