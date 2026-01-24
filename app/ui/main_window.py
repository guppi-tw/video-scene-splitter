"""
メインウィンドウ
"""
import tempfile
from pathlib import Path
from typing import List

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QPushButton, QMessageBox
)
from PySide6.QtCore import Qt, QThread

from app.core import JobQueue, VideoJob, JobStatus, Scene
from app.ui.queue_widget import QueueWidget
from app.ui.review_widget import ReviewWidget
from app.ui.log_widget import LogWidget
from app.ui.settings_widget import SettingsWidget
from app.ui.preview_widget import PreviewWidget
from app.ui.timeline_widget import TimelineWidget
from app.ui.workers import ProcessingWorker, ExportWorker


class MainWindow(QMainWindow):
    """メインウィンドウ"""
    
    def __init__(self):
        super().__init__()
        
        self.job_queue = JobQueue()
        self.temp_dir = Path(tempfile.mkdtemp(prefix="video_scene_splitter_"))
        
        self.processing_thread: QThread = None
        self.processing_worker: ProcessingWorker = None
        self.export_thread: QThread = None
        self.export_worker: ExportWorker = None
        
        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self):
        self.setWindowTitle("Video Scene Splitter")
        self.setMinimumSize(1400, 900)
        
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QVBoxLayout(central)
        
        # メインスプリッター（左: キュー+設定、中央: レビュー、右: プレビュー+タイムライン）
        splitter = QSplitter(Qt.Horizontal)
        
        # 左側: キュー + 設定
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        self.queue_widget = QueueWidget(self.job_queue)
        left_layout.addWidget(self.queue_widget)
        
        # 設定ウィジェット
        self.settings_widget = SettingsWidget()
        left_layout.addWidget(self.settings_widget)
        
        # 停止ボタン
        self.btn_stop = QPushButton("処理停止")
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_stop.setEnabled(False)
        left_layout.addWidget(self.btn_stop)
        
        splitter.addWidget(left_widget)
        
        # 中央: レビュー
        self.review_widget = ReviewWidget()
        splitter.addWidget(self.review_widget)
        
        # 右側: プレビュー + タイムライン
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(5)
        
        self.preview_widget = PreviewWidget()
        preview_layout.addWidget(self.preview_widget, stretch=1)
        
        # タイムラインウィジェット
        self.timeline_widget = TimelineWidget()
        preview_layout.addWidget(self.timeline_widget)
        
        splitter.addWidget(preview_container)
        
        splitter.setSizes([300, 650, 450])
        main_layout.addWidget(splitter, stretch=1)
        
        # 下部: ログ
        self.log_widget = LogWidget()
        main_layout.addWidget(self.log_widget)
    
    def _connect_signals(self):
        self.queue_widget.job_selected.connect(self._on_job_selected)
        self.queue_widget.start_processing.connect(self._on_start_processing)
        self.review_widget.export_requested.connect(self._on_export_requested)
        
        # レビューウィジェットからのシーン選択をプレビューに接続
        self.review_widget.scene_preview_requested.connect(self._on_scene_preview_requested)
        
        # プレビューの再生位置をタイムラインに反映
        self.preview_widget.position_changed.connect(self._on_playhead_changed)
        
        # タイムラインからのシーク要求
        self.timeline_widget.seek_requested.connect(self._on_timeline_seek)
        
        # タイムラインの境界変更
        self.timeline_widget.boundaries_changed.connect(self._on_boundaries_changed)
    
    def _on_job_selected(self, job: VideoJob):
        """ジョブ選択時"""
        if job.status in [JobStatus.REVIEW, JobStatus.DONE]:
            self.review_widget.set_job(job)
            # プレビューに動画を読み込む
            self.preview_widget.load_video(job.source_path)
            # タイムラインを更新
            self._update_timeline(job)
    
    def _update_timeline(self, job: VideoJob):
        """タイムラインを更新"""
        if not job.scenes:
            return
        
        # シーン開始時刻のリストを作成
        scene_start_times = [scene.start_time for scene in job.scenes]
        
        # 動画の長さを取得（最後のシーンの終了時刻）
        duration = job.scenes[-1].end_time if job.scenes else 0
        
        self.timeline_widget.set_scenes(scene_start_times, duration)
    
    def _on_scene_preview_requested(self, job: VideoJob, scene_index: int, start_time: float):
        """シーンプレビューリクエスト"""
        # 動画が読み込まれていなければ読み込む
        if self.preview_widget.current_video_path != job.source_path:
            self.preview_widget.load_video(job.source_path)
        
        # 指定位置にシークして再生
        self.preview_widget.seek_to(start_time)
        self.preview_widget.play()
    
    def _on_playhead_changed(self, position: float):
        """再生位置が変わった"""
        self.timeline_widget.set_playhead(position)
    
    def _on_timeline_seek(self, time: float):
        """タイムラインからのシーク要求"""
        self.preview_widget.seek_to(time)
    
    def _on_boundaries_changed(self, boundaries: List[float]):
        """タイムラインの境界が変更された"""
        job = self.review_widget.current_job
        if not job:
            return
        
        # シーンを再構築
        self._rebuild_scenes(job, boundaries)
        
        # レビューUIを更新
        self.review_widget.set_job(job)
        
        self.log_widget.append_log(f"シーン境界を更新: {len(boundaries)}シーン")
    
    def _rebuild_scenes(self, job: VideoJob, boundaries: List[float]):
        """境界時刻からシーンを再構築"""
        if not boundaries:
            return
        
        # 最後のシーンの終了時刻を保持
        duration = job.scenes[-1].end_time if job.scenes else 0
        
        # 古いシーンのメタデータを保持（可能な範囲で）
        old_metadata = {}
        for scene in job.scenes:
            old_metadata[scene.index] = {
                'event_name': scene.event_name,
                'event_date': scene.event_date,
                'keep': scene.keep,
                'thumbnail_path': scene.thumbnail_path
            }
        
        # 新しいシーンを作成
        new_scenes = []
        sorted_boundaries = sorted(boundaries)
        
        for i in range(len(sorted_boundaries)):
            start_time = sorted_boundaries[i]
            end_time = sorted_boundaries[i + 1] if i + 1 < len(sorted_boundaries) else duration
            
            scene = Scene(
                index=i + 1,
                start_time=start_time,
                end_time=end_time
            )
            
            # 近い位置の古いシーンからメタデータを引き継ぐ
            for old_idx, meta in old_metadata.items():
                # 開始時刻が近いシーンを探す
                old_scene = next((s for s in job.scenes if s.index == old_idx), None)
                if old_scene and abs(old_scene.start_time - start_time) < 5.0:
                    scene.event_name = meta['event_name']
                    scene.event_date = meta['event_date']
                    scene.keep = meta['keep']
                    scene.thumbnail_path = meta['thumbnail_path']
                    break
            
            new_scenes.append(scene)
        
        job.scenes = new_scenes
    
    def _on_start_processing(self):
        """処理開始"""
        job = self.job_queue.get_next_waiting()
        if not job:
            QMessageBox.information(self, "情報", "処理待ちのジョブがありません")
            return
        
        self._start_job_processing(job)
    
    def _start_job_processing(self, job: VideoJob):
        """ジョブの処理を開始"""
        if self.processing_thread and self.processing_thread.isRunning():
            return
        
        self.log_widget.clear_log()
        self.log_widget.set_status(f"処理中: {job.filename}")
        self.log_widget.hide_progress()
        self.btn_stop.setEnabled(True)
        
        # 設定から閾値と最小シーン長を取得
        threshold = self.settings_widget.threshold
        min_scene_len_sec = self.settings_widget.min_scene_len_sec
        detect_blanks = self.settings_widget.detect_blanks
        blank_variance_threshold = self.settings_widget.blank_variance_threshold
        min_blank_duration = self.settings_widget.min_blank_duration
        
        # ワーカーとスレッドを作成
        self.processing_thread = QThread()
        self.processing_worker = ProcessingWorker(
            job,
            self.temp_dir,
            threshold=threshold,
            min_scene_len_sec=min_scene_len_sec,
            detect_blanks=detect_blanks,
            blank_variance_threshold=blank_variance_threshold,
            min_blank_duration=min_blank_duration
        )
        self.processing_worker.moveToThread(self.processing_thread)
        
        # シグナル接続
        self.processing_thread.started.connect(self.processing_worker.run)
        self.processing_worker.progress.connect(self._on_progress)
        self.processing_worker.frame_progress.connect(self._on_frame_progress)
        self.processing_worker.scene_detected.connect(self._on_scene_detected)
        self.processing_worker.thumbnail_progress.connect(self._on_thumbnail_progress)
        self.processing_worker.thumbnail_generated.connect(self._on_thumbnail_generated)
        self.processing_worker.processing_complete.connect(self._on_processing_complete)
        self.processing_worker.error.connect(self._on_error)
        
        self.processing_thread.start()
        self.queue_widget.refresh()
    
    def _on_stop(self):
        """処理停止"""
        if self.processing_worker:
            self.processing_worker.cancel()
        if self.export_worker:
            self.export_worker.cancel()
        
        self.log_widget.append_log("停止リクエストを送信しました")
    
    def _on_progress(self, message: str):
        """進捗更新"""
        self.log_widget.append_log(message)
    
    def _on_frame_progress(self, current: int, total: int, percent: float):
        """フレーム進捗更新"""
        self.log_widget.set_progress_bar(current, total)
        self.log_widget.set_detail(
            f"シーン検知中: {current:,} / {total:,} フレーム ({percent:.1f}%)"
        )
    
    def _on_thumbnail_progress(self, current: int, total: int):
        """サムネイル進捗更新"""
        self.log_widget.set_progress_bar(current, total)
        self.log_widget.set_detail(
            f"サムネイル生成中: {current} / {total}"
        )
    
    def _on_scene_detected(self, job: VideoJob):
        """シーン検知完了"""
        self.log_widget.set_progress(f"{len(job.scenes)}シーン検出")
        self.review_widget.set_job(job)
        self.queue_widget.refresh()
        
        # プレビューに動画を読み込む
        self.preview_widget.load_video(job.source_path)
        
        # タイムラインを更新
        self._update_timeline(job)
    
    def _on_thumbnail_generated(self, scene_index: int, path: str):
        """サムネイル生成完了"""
        self.review_widget.update_thumbnail(scene_index, path)
    
    def _on_processing_complete(self, job: VideoJob):
        """処理完了"""
        self.log_widget.set_status("レビュー待ち")
        self.log_widget.hide_progress()
        self.btn_stop.setEnabled(False)
        
        # スレッドをクリーンアップ
        if self.processing_thread:
            self.processing_thread.quit()
            self.processing_thread.wait()
            self.processing_thread = None
            self.processing_worker = None
        
        self.queue_widget.refresh()
        self.queue_widget.select_job(job.id)
        
        # 次のジョブがあれば自動で開始しない（レビューが必要なため）
        QMessageBox.information(
            self,
            "処理完了",
            f"{job.filename} のシーン検知が完了しました。\n"
            f"検出シーン数: {len(job.scenes)}\n\n"
            f"レビューして書き出しを行ってください。\n"
            f"タイムラインで境界を調整することもできます。"
        )
    
    def _on_error(self, message: str):
        """エラー発生"""
        self.log_widget.append_log(f"[ERROR] {message}")
        self.log_widget.set_status("エラー")
        self.log_widget.hide_progress()
        self.btn_stop.setEnabled(False)
        
        # スレッドをクリーンアップ
        if self.processing_thread:
            self.processing_thread.quit()
            self.processing_thread.wait()
            self.processing_thread = None
            self.processing_worker = None
        
        self.queue_widget.refresh()
        
        # 次のジョブを処理
        next_job = self.job_queue.get_next_waiting()
        if next_job:
            reply = QMessageBox.question(
                self,
                "次のジョブ",
                "エラーが発生しました。次のジョブを処理しますか？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self._start_job_processing(next_job)
    
    def _on_export_requested(self, job: VideoJob, output_dir: Path):
        """書き出しリクエスト"""
        if self.export_thread and self.export_thread.isRunning():
            QMessageBox.warning(self, "警告", "書き出し中です")
            return
        
        self.log_widget.clear_log()
        self.log_widget.set_status(f"書き出し中: {job.filename}")
        self.log_widget.hide_progress()
        self.btn_stop.setEnabled(True)
        
        # ワーカーとスレッドを作成
        self.export_thread = QThread()
        self.export_worker = ExportWorker(job, output_dir)
        self.export_worker.moveToThread(self.export_thread)
        
        # シグナル接続
        self.export_thread.started.connect(self.export_worker.run)
        self.export_worker.progress.connect(self._on_progress)
        self.export_worker.clip_progress.connect(self._on_clip_progress)
        self.export_worker.export_complete.connect(self._on_export_complete)
        self.export_worker.error.connect(self._on_error)
        
        self.export_thread.start()
    
    def _on_clip_progress(self, current: int, total: int):
        """クリップ進捗更新"""
        self.log_widget.set_progress_bar(current, total)
        self.log_widget.set_detail(
            f"書き出し中: {current} / {total} クリップ"
        )
    
    def _on_export_complete(self, job: VideoJob):
        """書き出し完了"""
        self.log_widget.set_status("書き出し完了")
        self.log_widget.hide_progress()
        self.btn_stop.setEnabled(False)
        
        # スレッドをクリーンアップ
        if self.export_thread:
            self.export_thread.quit()
            self.export_thread.wait()
            self.export_thread = None
            self.export_worker = None
        
        self.queue_widget.refresh()
        
        if job.status == JobStatus.DONE:
            QMessageBox.information(
                self,
                "書き出し完了",
                f"{job.filename} の書き出しが完了しました。\n"
                f"出力先: {job.output_dir}\n"
                f"クリップ数: {len(job.clips)}"
            )
        
        # 次の待機ジョブを処理
        next_job = self.job_queue.get_next_waiting()
        if next_job:
            reply = QMessageBox.question(
                self,
                "次のジョブ",
                "次のジョブを処理しますか？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self._start_job_processing(next_job)
    
    def closeEvent(self, event):
        """ウィンドウ閉じる時"""
        # 処理中なら確認
        if (self.processing_thread and self.processing_thread.isRunning()) or \
           (self.export_thread and self.export_thread.isRunning()):
            reply = QMessageBox.question(
                self,
                "確認",
                "処理中です。終了しますか？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
            
            # 処理を停止
            self._on_stop()
            if self.processing_thread:
                self.processing_thread.quit()
                self.processing_thread.wait(3000)
            if self.export_thread:
                self.export_thread.quit()
                self.export_thread.wait(3000)
        
        # プレビューをクリーンアップ
        self.preview_widget.cleanup()
        
        # 一時ディレクトリをクリーンアップ
        import shutil
        try:
            shutil.rmtree(self.temp_dir)
        except Exception:
            pass
        
        event.accept()
