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
    scene_detected = Signal(object)  # シーン検知完了 (VideoJob)
    thumbnail_generated = Signal(int, str)  # サムネイル生成完了 (scene_index, path)
    processing_complete = Signal(object)  # 処理完了 (VideoJob)
    error = Signal(str)  # エラー
    
    def __init__(self, job: VideoJob, temp_dir: Path):
        super().__init__()
        self.job = job
        self.temp_dir = temp_dir
        self._cancelled = False
        
        self.scene_detector = SceneDetectRunner()
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
                progress_callback=lambda msg: self.progress.emit(msg)
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
            
            for scene in scenes:
                if self._cancelled:
                    self.progress.emit("キャンセルされました")
                    return
                
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


class ExportWorker(QObject):
    """書き出しワーカー"""
    
    progress = Signal(str)
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
            
            success = self.exporter.export(
                self.job,
                self.output_dir,
                progress_callback=lambda msg: self.progress.emit(msg)
            )
            
            if success:
                self.job.status = JobStatus.DONE
                self.progress.emit("書き出し完了")
            else:
                self.job.status = JobStatus.ERROR
                self.job.error_message = "書き出しに失敗しました"
                self.progress.emit("書き出し失敗")
            
            self.export_complete.emit(self.job)
            
        except Exception as e:
            self.job.status = JobStatus.ERROR
            self.job.error_message = str(e)
            self.error.emit(f"エラー: {str(e)}")
