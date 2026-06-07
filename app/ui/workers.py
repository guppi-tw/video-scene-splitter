"""
バックグラウンドワーカー（QThreadベース）
"""
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from app.core import (
    VideoJob, JobStatus, Scene, Clip,
    FFmpegRunner, Exporter,
    group_clips_by_metadata
)


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
        """サムネイル生成"""
        try:
            thumb_dir = self.temp_dir / f"job_{self.job.id}"
            thumb_dir.mkdir(parents=True, exist_ok=True)

            for scene in self.job.scenes:
                if self._cancelled:
                    break

                thumb_time = scene.start_time + min(2.0, scene.duration / 2)
                thumb_path = thumb_dir / f"clip_{scene.index:04d}.jpg"

                if self.ffmpeg.generate_thumbnail(
                    self.job.source_path, thumb_time, thumb_path
                ):
                    scene.thumbnail_path = thumb_path
                    self.thumbnail_ready.emit(scene.index, str(thumb_path))
        except Exception:
            pass
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

            # クリップを計算
            clips = self.exporter.calculate_clips(self.job)
            if not clips:
                self.progress.emit("書き出し対象のシーンがありません")
                self.job.status = JobStatus.ERROR
                self.job.error_message = "書き出し対象のシーンがありません"
                self.export_complete.emit(self.job)
                return

            self.job.clips = clips
            total_clips = len(clips)

            # メタデータでグループ化
            clips_by_metadata = group_clips_by_metadata(clips)

            self.progress.emit(f"クリップ数: {total_clips}")
            self.progress.emit(f"出力グループ数: {len(clips_by_metadata)}")

            # 各グループを書き出し
            success_count = 0
            current_clip_num = 0

            for (event_name, event_date, is_sensitive), group_clips in clips_by_metadata.items():
                if self._cancelled:
                    self.progress.emit("キャンセルされました")
                    return

                # 出力ディレクトリを作成
                output_dir = self.job.get_output_dir(
                    self.output_dir, event_name, event_date, is_sensitive
                )
                output_dir.mkdir(parents=True, exist_ok=True)

                self.progress.emit(f"出力先: {output_dir}")

                # グループ内のクリップを書き出し
                for clip in group_clips:
                    if self._cancelled:
                        self.progress.emit("キャンセルされました")
                        return

                    current_clip_num += 1
                    self.clip_progress.emit(current_clip_num, total_clips)
                    self.progress.emit(f"書き出し中: {current_clip_num}/{total_clips}")

                    filename = self.job.get_clip_filename(clip)
                    output_path = output_dir / filename
                    clip.output_path = output_path

                    success = self.ffmpeg.extract_clip(
                        video_path=self.job.source_path,
                        start_time=clip.start_time,
                        end_time=clip.end_time,
                        output_path=output_path,
                        use_copy=True,
                        progress_callback=lambda msg: self.progress.emit(msg)
                    )

                    if success:
                        success_count += 1
                    else:
                        self.progress.emit(f"警告: クリップ {clip.index} の書き出しに失敗")

            if success_count > 0:
                self.job.status = JobStatus.DONE
                self.progress.emit(f"書き出し完了: {success_count}/{total_clips} クリップ")
            else:
                self.job.status = JobStatus.ERROR
                self.job.error_message = "すべてのクリップの書き出しに失敗しました"
                self.progress.emit("書き出し失敗")

            self.export_complete.emit(self.job)

        except Exception as e:
            self.job.status = JobStatus.ERROR
            self.job.error_message = str(e)
            self.error.emit(f"エラー: {str(e)}")
