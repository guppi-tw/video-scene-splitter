"""
バックグラウンドワーカー（QThreadベース）
"""
import logging
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from typing import Optional

from app.core import VideoJob, JobStatus, FFmpegRunner, Exporter
from app.core.scene_detector import SceneDetectionSettings, detect_scene_boundaries

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
    progress_percent = Signal(int)  # 検出進捗 (0-100)
    detection_complete = Signal(list)
    error = Signal(str)
    finished = Signal()  # 完了・キャンセル・エラーのいずれでも最後に発火

    def __init__(
        self,
        job: VideoJob,
        duration: float,
        settings: Optional[SceneDetectionSettings] = None,
    ):
        super().__init__()
        self.job = job
        self.duration = duration
        self.settings = settings
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
                settings=self.settings,
                cancel_callback=lambda: self._cancelled,
                progress_callback=self.progress_percent.emit,
            )
            if boundaries is None or self._cancelled:
                self.progress.emit("シーン自動検出はキャンセルされました")
                return
            self.detection_complete.emit(boundaries)
        except Exception as e:
            self.error.emit(f"シーン自動検出エラー: {str(e)}")
        finally:
            self.finished.emit()


class BatchSceneDetectionWorker(QObject):
    """複数動画のシーン分割を一括検出するワーカー（逐次処理）"""

    progress = Signal(str)
    progress_percent = Signal(int)  # 全体進捗 (0-100)
    video_done = Signal(int, int)   # job_id, 検出シーン数
    error = Signal(str)
    finished = Signal()

    def __init__(self, jobs: list, settings: Optional[SceneDetectionSettings] = None):
        super().__init__()
        self.jobs = jobs
        self.settings = settings
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        """各動画を順番にシーン検出し、結果を各ジョブに設定する"""
        runner = FFmpegRunner()
        total = len(self.jobs)
        for i, job in enumerate(self.jobs):
            if self._cancelled:
                break

            self.progress.emit(f"({i + 1}/{total}) 検出中: {job.filename}")

            try:
                duration = runner.get_video_duration(job.source_path)
                if duration is None or duration <= 0:
                    message = "動画の長さを取得できませんでした"
                    job.status = JobStatus.ERROR
                    job.error_message = message
                    self.error.emit(f"{job.filename}: {message}")
                    self.progress_percent.emit(int((i + 1) / total * 100) if total else 100)
                    continue

                def on_percent(pct, _i=i):
                    overall = int((_i + pct / 100.0) / total * 100) if total else 100
                    self.progress_percent.emit(overall)

                boundaries = detect_scene_boundaries(
                    job.source_path,
                    duration=duration,
                    settings=self.settings,
                    cancel_callback=lambda: self._cancelled,
                    progress_callback=on_percent,
                )
                if self._cancelled or boundaries is None:
                    break

                job.rebuild_scenes_from_boundaries(boundaries, duration)
                job.status = JobStatus.REVIEW
                # 開いたときに日付検出などの仕上げ処理を実行させる
                job.needs_post_process = True
                self.video_done.emit(job.id, len(job.scenes))
                self.progress_percent.emit(int((i + 1) / total * 100) if total else 100)
            except Exception as e:
                logger.exception("一括検出中に動画単位のエラー: %s", job.source_path)
                job.status = JobStatus.ERROR
                job.error_message = str(e)
                self.error.emit(f"{job.filename}: {e}")
                self.progress_percent.emit(int((i + 1) / total * 100) if total else 100)
                continue

        self.finished.emit()


class DateDetectionWorker(QObject):
    """焼き込み日付検出ワーカー"""

    progress = Signal(str)
    progress_percent = Signal(int)  # 検出進捗 (0-100)
    detection_complete = Signal(dict)  # {'full': {idx: date}, 'ym': {idx: (y,m)}}
    error = Signal(str)
    finished = Signal()  # 完了・キャンセル・エラーのいずれでも最後に発火

    def __init__(self, job: VideoJob):
        super().__init__()
        self.job = job
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        """各シーンの焼き込み日付を検出"""
        from app.core.date_detector import detect_scene_dates

        try:
            self.progress.emit("日付検出を開始しました")
            scene_times = [
                (s.index, s.start_time, s.end_time) for s in self.job.scenes
            ]
            full, year_months = detect_scene_dates(
                self.job.source_path,
                scene_times,
                cancel_callback=lambda: self._cancelled,
                progress_callback=lambda done, total: self.progress_percent.emit(
                    int(done * 100 / total) if total else 100
                ),
            )
            if self._cancelled:
                self.progress.emit("日付検出はキャンセルされました")
                return
            self.detection_complete.emit({"full": full, "ym": year_months})
        except Exception as e:
            self.error.emit(f"日付検出エラー: {str(e)}")
        finally:
            self.finished.emit()


class BlankDetectionWorker(QObject):
    """単色（青/黒一色）つなぎ目シーン検出ワーカー"""

    progress = Signal(str)
    progress_percent = Signal(int)  # 検出進捗 (0-100)
    detection_complete = Signal(list)  # [(開始秒, 終了秒, ラベル)]
    error = Signal(str)
    finished = Signal()

    def __init__(self, job: VideoJob):
        super().__init__()
        self.job = job
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        """単色のつなぎ目区間を検出"""
        from app.core.blank_detector import detect_blank_segments

        try:
            self.progress.emit("つなぎ目（単色）の検出を開始しました")
            scene_times = [
                (s.index, s.start_time, s.end_time) for s in self.job.scenes
            ]
            segments = detect_blank_segments(
                self.job.source_path,
                scene_times,
                cancel_callback=lambda: self._cancelled,
                progress_callback=lambda done, total: self.progress_percent.emit(
                    int(done * 100 / total) if total else 100
                ),
            )
            if self._cancelled:
                self.progress.emit("つなぎ目検出はキャンセルされました")
                return
            self.detection_complete.emit(segments)
        except Exception as e:
            self.error.emit(f"つなぎ目検出エラー: {str(e)}")
        finally:
            self.finished.emit()


class ExportWorker(QObject):
    """書き出しワーカー"""

    progress = Signal(str)
    clip_progress = Signal(int, int)  # クリップ進捗 (current, total)
    export_complete = Signal(object)  # VideoJob
    error = Signal(str)

    def __init__(self, job: VideoJob, output_dir: Path, auto_split: bool = True):
        super().__init__()
        self.job = job
        # 書き出し開始後のUI編集が出力内容へ混入しないよう固定する。
        self.export_job = deepcopy(job)
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
                self.export_job,
                self.output_dir,
                progress_callback=self.progress.emit,
                clip_progress_callback=self.clip_progress.emit,
                cancel_callback=lambda: self._cancelled,
            )

            if result.cancelled:
                self.job.status = JobStatus.REVIEW
                self.job.error_message = ""
                self.progress.emit("書き出しをキャンセルしました")
            elif result.total == 0:
                self.job.status = JobStatus.ERROR
                self.job.error_message = "書き出し対象のシーンがありません"
            elif result.all_succeeded:
                self.job.status = JobStatus.DONE
                self.job.error_message = ""
                self.job.clips = deepcopy(self.export_job.clips)
            else:
                self.job.clips = deepcopy(self.export_job.clips)
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
