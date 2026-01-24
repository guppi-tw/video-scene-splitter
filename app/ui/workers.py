"""
バックグラウンドワーカー（QThreadベース）
"""
import tempfile
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal, QThread

from ..core import (
    VideoJob, JobStatus, Scene,
    SceneDetectRunner, FFmpegRunner, Exporter
)


class ProcessingWorker(QObject):
    """動画処理ワーカー"""
    
    # シグナル定義
    progress = Signal(str)  # 進捗メッセージ
    frame_progress = Signal(int, int, float)  # フレーム進捗 (current, total, percent)
    scene_detected = Signal(object)  # シーン検知完了 (VideoJob)
    thumbnail_progress = Signal(int, int)  # サムネイル進捗 (current, total)
    thumbnail_generated = Signal(int, str)  # サムネイル生成完了 (scene_index, path)
    processing_complete = Signal(object)  # 処理完了 (VideoJob)
    error = Signal(str)  # エラー
    
    def __init__(
        self,
        job: VideoJob,
        temp_dir: Path,
        threshold: float = 27.0,
        min_scene_len_sec: float = 2.0
    ):
        super().__init__()
        self.job = job
        self.temp_dir = temp_dir
        self._cancelled = False
        
        # 設定を反映したシーン検知器を作成
        self.scene_detector = SceneDetectRunner(
            threshold=threshold,
            min_scene_len_sec=min_scene_len_sec
        )
        self.ffmpeg = FFmpegRunner()
    
    def cancel(self):
        """処理をキャンセル"""
        self._cancelled = True
        self.ffmpeg.cancel()
    
    def run(self):
        """メイン処理"""
        try:
            self.job.status = JobStatus.PROCESSING
            self.progress.emit(f"処理開始: {self.job.filename}")
            
            # シーン検知
            self.progress.emit("シーン検知中...")
            scenes = self.scene_detector.detect_scenes(
                self.job.source_path,
                progress_callback=lambda msg: self.progress.emit(msg),
                frame_progress_callback=self._on_frame_progress
            )
            
            if self._cancelled:
                self.progress.emit("キャンセルされました")
                return
            
            self.job.scenes = scenes
            self.scene_detected.emit(self.job)
            
            # サムネイル生成
            self.progress.emit("サムネイル生成中...")
            thumb_dir = self.temp_dir / f"job_{self.job.id}"
            thumb_dir.mkdir(parents=True, exist_ok=True)
            
            total_scenes = len(scenes)
            for i, scene in enumerate(scenes):
                if self._cancelled:
                    self.progress.emit("キャンセルされました")
                    return
                
                # 進捗を報告
                self.thumbnail_progress.emit(i + 1, total_scenes)
                
                # シーン開始+2秒の位置（暗転回避）
                thumb_time = scene.start_time + 2.0
                if thumb_time > scene.end_time:
                    thumb_time = scene.start_time + (scene.duration / 2)
                
                thumb_path = thumb_dir / f"scene_{scene.index:04d}.jpg"
                
                success = self.ffmpeg.generate_thumbnail(
                    self.job.source_path,
                    thumb_time,
                    thumb_path,
                    progress_callback=lambda msg: self.progress.emit(msg)
                )
                
                if success:
                    scene.thumbnail_path = thumb_path
                    self.thumbnail_generated.emit(scene.index, str(thumb_path))
            
            self.job.status = JobStatus.REVIEW
            self.progress.emit("処理完了 - レビュー待ち")
            self.processing_complete.emit(self.job)
            
        except Exception as e:
            self.job.status = JobStatus.ERROR
            self.job.error_message = str(e)
            self.error.emit(f"エラー: {str(e)}")
    
    def _on_frame_progress(self, current: int, total: int, percent: float):
        """フレーム進捗コールバック"""
        self.frame_progress.emit(current, total, percent)


class ExportWorker(QObject):
    """書き出しワーカー"""
    
    progress = Signal(str)
    clip_progress = Signal(int, int)  # クリップ進捗 (current, total)
    export_complete = Signal(object)  # VideoJob
    error = Signal(str)
    
    def __init__(self, job: VideoJob, output_dir: Path):
        super().__init__()
        self.job = job
        self.output_dir = output_dir
        self._cancelled = False
        
        self.ffmpeg = FFmpegRunner()
        self.exporter = Exporter(self.ffmpeg)
    
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
            
            # 出力ディレクトリを作成
            folder_name = self.job.get_output_folder_name()
            output_dir = self.output_dir / folder_name
            output_dir.mkdir(parents=True, exist_ok=True)
            self.job.output_dir = output_dir
            
            self.progress.emit(f"出力先: {output_dir}")
            self.progress.emit(f"クリップ数: {total_clips}")
            
            # 各クリップを書き出し
            success_count = 0
            for i, clip in enumerate(clips):
                if self._cancelled:
                    self.progress.emit("キャンセルされました")
                    return
                
                self.clip_progress.emit(i + 1, total_clips)
                self.progress.emit(f"書き出し中: {i + 1}/{total_clips}")
                
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
