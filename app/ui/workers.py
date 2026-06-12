"""
バックグラウンドワーカー（QThreadベース）
"""
import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from app.core import VideoJob, JobStatus, FFmpegRunner, Exporter
from app.core.scene_detector import detect_scene_boundaries

logger = logging.getLogger(__name__)


class ThumbnailWorker(QObject):
    """サムネイル生成ワーカー"""

    thumbnail_ready = Signal(int, str)  # scene_index, path
    finished = Signal()

    def __init__(self, job: VideoJob, temp_dir: Path):
        super().__init__()
        self.job = job
        self.temp_dir = temp_dir
        self.ffmpeg = FFmpegRunner()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        self.ffmpeg.cancel()

    def run(self):
        """サムネイル生成（生成済みのシーンはスキップ）"""
        try:
            thumb_dir = self.temp_dir / f"job_{self.job.id}"
            thumb_dir.mkdir(parents=True, exist_ok=True)

            for scene in self.job.scenes:
                if self._cancelled:
                    break

                if scene.thumbnail_path and Path(scene.thumbnail_path).exists():
                    continue

                thumb_time = scene.start_time + min(2.0, scene.duration / 2)
                # 開始時刻ベースのファイル名にすることで、境界編集後も
                # 変わらないシーンのサムネイルを再利用できる
                thumb_path = thumb_dir / f"thumb_{int(scene.start_time * 1000):010d}.jpg"

                if thumb_path.exists() or self.ffmpeg.generate_thumbnail(
                    self.job.source_path, thumb_time, thumb_path
                ):
                    scene.thumbnail_path = thumb_path
                    self.thumbnail_ready.emit(scene.index, str(thumb_path))
        except Exception:
            logger.exception("サムネイル生成中にエラー: %s", self.job.source_path)
        finally:
            self.finished.emit()


class SceneDetectionWorker(QObject):
    """シーン自動検出ワーカー"""

    progress = Signal(str)
    detection_complete = Signal(list)
    error = Signal(str)

    def __init__(self, job: VideoJob, duration: float):
        super().__init__()
        self.job = job
        self.duration = duration
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        """シーン境界を検出"""
        try:
            self.progress.emit("シーン自動検出を開始しました")
            boundaries = detect_scene_boundaries(
                self.job.source_path,
                duration=self.duration,
                cancel_callback=lambda: self._cancelled,
            )
            if boundaries is None or self._cancelled:
                self.progress.emit("シーン自動検出はキャンセルされました")
                return
            self.detection_complete.emit(boundaries)
        except Exception as e:
            self.error.emit(f"シーン自動検出エラー: {str(e)}")


class ExportWorker(QObject):
    """書き出しワーカー"""

    progress = Signal(str)
    clip_progress = Signal(int, int)  # クリップ進捗 (current, total)
    export_complete = Signal(object)  # VideoJob
    error = Signal(str)

    def __init__(self, job: VideoJob, output_dir: Path, auto_split: bool = True):
        super().__init__()
        self.job = job
        self.output_dir = output_dir
        self._cancelled = False

        self.ffmpeg = FFmpegRunner()
        self.exporter = Exporter(self.ffmpeg, auto_split=auto_split)

    def cancel(self):
        self._cancelled = True
        self.ffmpeg.cancel()

    def run(self):
        """書き出し実行"""
        try:
            self.progress.emit(f"書き出し開始: {self.job.filename}")

            result = self.exporter.export(
                self.job,
                self.output_dir,
                progress_callback=self.progress.emit,
                clip_progress_callback=self.clip_progress.emit,
                cancel_callback=lambda: self._cancelled,
            )

            if result.cancelled:
                self.job.status = JobStatus.REVIEW
                self.progress.emit("書き出しをキャンセルしました")
            elif result.total == 0:
                self.job.status = JobStatus.ERROR
                self.job.error_message = "書き出し対象のシーンがありません"
            elif result.all_succeeded:
                self.job.status = JobStatus.DONE
            else:
                failed = result.total - result.succeeded
                self.job.status = JobStatus.ERROR
                self.job.error_message = (
                    f"{failed}/{result.total} クリップの書き出しに失敗しました"
                )
        except Exception as e:
            self.job.status = JobStatus.ERROR
            self.job.error_message = str(e)
            self.error.emit(f"エラー: {str(e)}")
        finally:
            self.export_complete.emit(self.job)
