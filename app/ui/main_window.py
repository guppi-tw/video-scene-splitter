"""
メインウィンドウ
"""
import tempfile
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QPushButton, QMessageBox
)
from PySide6.QtCore import Qt, QThread

from ..core import JobQueue, VideoJob, JobStatus
from .queue_widget import QueueWidget
from .review_widget import ReviewWidget
from .log_widget import LogWidget
from .settings_widget import SettingsWidget
from .workers import ProcessingWorker, ExportWorker


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
        self.setMinimumSize(1200, 800)
        
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QVBoxLayout(central)
        
        # メインスプリッター（左: キュー+設定、右: レビュー）
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
        
        # 右側: レビュー
        self.review_widget = ReviewWidget()
        splitter.addWidget(self.review_widget)
        
        splitter.setSizes([400, 800])
        main_layout.addWidget(splitter, stretch=1)
        
        # 下部: ログ
        self.log_widget = LogWidget()
        main_layout.addWidget(self.log_widget)
    
    def _connect_signals(self):
        self.queue_widget.job_selected.connect(self._on_job_selected)
        self.queue_widget.start_processing.connect(self._on_start_processing)
        self.review_widget.export_requested.connect(self._on_export_requested)
    
    def _on_job_selected(self, job: VideoJob):
        """ジョブ選択時"""
        if job.status in [JobStatus.REVIEW, JobStatus.DONE]:
            self.review_widget.set_job(job)
    
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
        
        # ワーカーとスレッドを作成
        self.processing_thread = QThread()
        self.processing_worker = ProcessingWorker(
            job,
            self.temp_dir,
            threshold=threshold,
            min_scene_len_sec=min_scene_len_sec
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
            f"レビューして書き出しを行ってください。"
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
        
        # 一時ディレクトリをクリーンアップ
        import shutil
        try:
            shutil.rmtree(self.temp_dir)
        except Exception:
            pass
        
        event.accept()
