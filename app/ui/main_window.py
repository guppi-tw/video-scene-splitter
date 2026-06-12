"""
メインウィンドウ
"""
import tempfile
from pathlib import Path
from typing import List, Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout,
    QSplitter, QPushButton, QMessageBox, QApplication
)
from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QShortcut, QKeySequence

from app.core import JobQueue, VideoJob, JobStatus, Scene
from app.core.ffmpeg_runner import FFmpegRunner
from app.core.time_format import format_seconds
from app.ui.queue_widget import QueueWidget
from app.ui.clip_list_widget import ClipListWidget
from app.ui.log_widget import LogWidget
from app.ui.preview_widget import PreviewWidget
from app.ui.timeline_widget import TimelineWidget
from app.ui.workers import ThumbnailWorker, ExportWorker, SceneDetectionWorker
from app.core.scene_detector import merge_boundaries


class MainWindow(QMainWindow):
    """メインウィンドウ"""

    def __init__(self):
        super().__init__()

        self.job_queue = JobQueue()
        self.temp_dir = Path(tempfile.mkdtemp(prefix="video_scene_splitter_"))
        self.current_job: VideoJob = None

        self.thumbnail_thread: QThread = None
        self.thumbnail_worker: ThumbnailWorker = None
        self.export_thread: QThread = None
        self.export_worker: ExportWorker = None
        self.scene_detection_thread: QThread = None
        self.scene_detection_worker: SceneDetectionWorker = None

        # Undo履歴（境界のスナップショット）
        # 境界が変わるたびに変更前の状態を積む（分割・ドラッグ・追加・削除・
        # 自動検出・リセットすべてが対象）
        self._undo_stack: List[List[float]] = []
        self._last_boundaries: Optional[List[float]] = None
        self._undoing = False

        self._setup_ui()
        self._apply_theme()
        self._connect_signals()
        self._setup_shortcuts()

    def _setup_ui(self):
        self.setWindowTitle("Video Scene Splitter")
        self.setMinimumSize(1200, 800)

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)

        # メインスプリッター（左: キュー、中央: プレビュー+タイムライン、右: クリップリスト）
        splitter = QSplitter(Qt.Horizontal)

        # 左側: キュー
        self.queue_widget = QueueWidget(self.job_queue)
        splitter.addWidget(self.queue_widget)

        # 中央: プレビュー + タイムライン
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(5)

        self.preview_widget = PreviewWidget()
        center_layout.addWidget(self.preview_widget, stretch=1)

        self.timeline_widget = TimelineWidget()
        center_layout.addWidget(self.timeline_widget)

        splitter.addWidget(center_widget)

        # 右側: クリップリスト
        self.clip_list_widget = ClipListWidget()
        splitter.addWidget(self.clip_list_widget)

        splitter.setSizes([200, 650, 350])
        main_layout.addWidget(splitter, stretch=1)

        # 下部: ログ（トグル可能）
        self.btn_toggle_log = QPushButton("ログ非表示")
        self.btn_toggle_log.setFixedHeight(20)
        self.btn_toggle_log.setStyleSheet("font-size: 10px; padding: 0 8px;")
        self.btn_toggle_log.clicked.connect(self._on_toggle_log)
        main_layout.addWidget(self.btn_toggle_log)

        self.log_widget = LogWidget()
        main_layout.addWidget(self.log_widget)

    def _connect_signals(self):
        # キュー → 動画を開く
        self.queue_widget.open_video.connect(self._on_open_video)
        self.queue_widget.job_selected.connect(self._on_job_selected)
        self.queue_widget.remove_requested.connect(self._on_remove_job)

        # プレビュー → タイムライン同期
        self.preview_widget.position_changed.connect(self.timeline_widget.set_playhead)

        # プレビュー → 分割
        self.preview_widget.split_requested.connect(self._on_split_at_position)

        # プレビュー → 再生エラー
        self.preview_widget.error_occurred.connect(self._on_player_error)

        # タイムライン → シーク
        self.timeline_widget.seek_requested.connect(self.preview_widget.seek_to)

        # タイムライン → 境界変更
        self.timeline_widget.boundaries_changed.connect(self._on_boundaries_changed)
        self.timeline_widget.auto_detect_requested.connect(self._on_auto_detect_requested)

        # クリップリスト → プレビュー
        self.clip_list_widget.clip_preview_requested.connect(self._on_clip_preview)

        # クリップリスト → 書き出し
        self.clip_list_widget.export_requested.connect(self._on_export_requested)

    def _on_job_selected(self, job: VideoJob):
        """ジョブ選択時（既に編集中のジョブを表示）"""
        if job.status in [JobStatus.REVIEW, JobStatus.DONE]:
            self.current_job = job
            self.clip_list_widget.set_job(job)
            self.preview_widget.load_video(job.source_path)
            self._update_timeline(job)
            # ジョブをまたいだUndoは破壊的なのでリセット
            self._undo_stack.clear()
            self._last_boundaries = [s.start_time for s in job.scenes]
            self._regenerate_thumbnails()

    def _on_remove_job(self, job_id: int):
        """キューからのジョブ削除リクエスト"""
        if (self.export_thread and self.export_thread.isRunning()
                and self.export_worker and self.export_worker.job.id == job_id):
            QMessageBox.warning(self, "警告", "書き出し中のジョブは削除できません")
            return

        removing_current = self.current_job is not None and self.current_job.id == job_id

        if removing_current:
            self._stop_thumbnail_worker()
            if self.scene_detection_thread and self.scene_detection_thread.isRunning():
                if self.scene_detection_worker:
                    self.scene_detection_worker.cancel()
                self.scene_detection_thread.quit()
                self.scene_detection_thread.wait()
                self.scene_detection_thread = None
                self.scene_detection_worker = None

        self.job_queue.remove_job(job_id)
        self.queue_widget.refresh()

        if removing_current:
            self.current_job = None
            self._undo_stack.clear()
            self._last_boundaries = None
            self.preview_widget.cleanup()
            self.timeline_widget.clear()
            self.clip_list_widget.clear()
            self.log_widget.set_status("待機中")

    def _on_open_video(self, job: VideoJob):
        """動画を開いて編集開始"""
        if not job:
            return

        self.log_widget.clear_log()
        self.log_widget.set_status(f"編集中: {job.filename}")
        self.log_widget.append_log("動画情報を取得中...")

        # 動画の長さを取得
        ffmpeg = FFmpegRunner()
        duration = ffmpeg.get_video_duration(job.source_path)

        if duration is None:
            QMessageBox.warning(
                self,
                "エラー",
                f"動画の長さを取得できませんでした: {job.filename}"
            )
            return

        self.log_widget.append_log(f"動画の長さ: {format_seconds(duration)}")

        # 動画全体を1シーンとして設定
        scene = Scene(index=1, start_time=0.0, end_time=duration, keep=True)
        job.scenes = [scene]
        job.status = JobStatus.REVIEW
        self.current_job = job

        self._undo_stack.clear()
        self._last_boundaries = [0.0]

        # UIを更新
        self.queue_widget.refresh()
        self.clip_list_widget.set_job(job)
        self.preview_widget.load_video(job.source_path)
        self.timeline_widget.set_scenes([0.0], duration)

        # サムネイルはバックグラウンドで生成（UIをブロックしない）
        self._regenerate_thumbnails()

        self.log_widget.append_log("編集を開始しました")
        self.log_widget.append_log("「ここで分割」ボタンまたはタイムライン右クリックで境界を追加")

    def _on_split_at_position(self, time: float):
        """指定位置で分割（自動一時停止）"""
        if not self.current_job or not self.current_job.scenes:
            return

        duration = self.current_job.scenes[-1].end_time
        if time <= 0 or time >= duration:
            return

        # 既存境界とほぼ同じ位置なら何もしない（floatの完全一致は使わない）
        boundaries = self.timeline_widget.get_boundaries()
        if any(abs(time - b) < 0.05 for b in boundaries):
            return

        # 分割時に一時停止
        self.preview_widget.pause()
        self.timeline_widget.add_boundary(time)

    def _on_boundaries_changed(self, boundaries: List[float]):
        """タイムラインの境界が変更された"""
        if not self.current_job:
            return

        duration = self.current_job.scenes[-1].end_time if self.current_job.scenes else 0

        # Undo履歴に変更前の状態を積む（Undo実行による変更は積まない）
        if (not self._undoing
                and self._last_boundaries is not None
                and boundaries != self._last_boundaries):
            self._undo_stack.append(self._last_boundaries.copy())
        self._last_boundaries = list(boundaries)

        # シーンを再構築
        self.current_job.rebuild_scenes_from_boundaries(boundaries, duration)

        # クリップリストを更新
        self.clip_list_widget.refresh_clips()

        # サムネイルを再生成
        self._regenerate_thumbnails()

        self.log_widget.append_log(
            f"クリップ数: {len(self.current_job.scenes)}"
        )

    def _stop_thumbnail_worker(self):
        """サムネイルワーカーを停止して破棄"""
        if self.thumbnail_thread and self.thumbnail_thread.isRunning():
            if self.thumbnail_worker:
                self.thumbnail_worker.cancel()
            self.thumbnail_thread.quit()
            self.thumbnail_thread.wait()
        self.thumbnail_thread = None
        self.thumbnail_worker = None

    def _regenerate_thumbnails(self):
        """バックグラウンドでサムネイルを再生成（生成済みシーンはスキップ）"""
        if not self.current_job:
            return

        # 既存のサムネイルワーカーを停止
        self._stop_thumbnail_worker()

        self.thumbnail_thread = QThread()
        self.thumbnail_worker = ThumbnailWorker(self.current_job, self.temp_dir)
        self.thumbnail_worker.moveToThread(self.thumbnail_thread)

        self.thumbnail_thread.started.connect(self.thumbnail_worker.run)
        self.thumbnail_worker.thumbnail_ready.connect(self._on_thumbnail_ready)
        self.thumbnail_worker.finished.connect(self._on_thumbnail_finished)

        self.thumbnail_thread.start()

    def _on_thumbnail_ready(self, scene_index: int, path: str):
        """サムネイル生成完了"""
        # 停止済みワーカーや別ジョブのワーカーからの通知は無視する
        if self.sender() is not self.thumbnail_worker:
            return
        if self.thumbnail_worker is None or self.thumbnail_worker.job is not self.current_job:
            return
        self.clip_list_widget.update_thumbnail(scene_index, path)

    def _on_thumbnail_finished(self):
        """サムネイル生成全完了"""
        # 停止済みの旧ワーカーからの通知で現行スレッドを止めない
        if self.sender() is not self.thumbnail_worker:
            return
        if self.thumbnail_thread:
            self.thumbnail_thread.quit()
            self.thumbnail_thread.wait()
            self.thumbnail_thread = None
            self.thumbnail_worker = None

    def _on_clip_preview(self, start_time: float):
        """クリップのプレビュー再生"""
        self.preview_widget.play_from(start_time)

    def _on_auto_detect_requested(self):
        """シーン境界の自動検出を開始"""
        if not self.current_job or not self.current_job.scenes:
            return

        if self.scene_detection_thread and self.scene_detection_thread.isRunning():
            QMessageBox.warning(self, "警告", "シーン自動検出中です")
            return

        duration = self.current_job.scenes[-1].end_time
        self.log_widget.append_log("シーン自動検出を準備中...")
        self.log_widget.set_status("シーン自動検出中")
        self.timeline_widget.set_auto_detect_enabled(False)

        self.scene_detection_thread = QThread()
        self.scene_detection_worker = SceneDetectionWorker(self.current_job, duration)
        self.scene_detection_worker.moveToThread(self.scene_detection_thread)

        self.scene_detection_thread.started.connect(self.scene_detection_worker.run)
        self.scene_detection_worker.progress.connect(self._on_progress)
        self.scene_detection_worker.detection_complete.connect(self._on_scene_detection_complete)
        self.scene_detection_worker.error.connect(self._on_scene_detection_error)

        self.scene_detection_thread.start()

    def _on_scene_detection_complete(self, detected_boundaries: list):
        """シーン自動検出完了"""
        if not self.current_job or not self.current_job.scenes:
            self._finish_scene_detection()
            return

        duration = self.current_job.scenes[-1].end_time
        existing_boundaries = self.timeline_widget.get_boundaries()
        merged_boundaries = merge_boundaries(
            existing_boundaries,
            detected_boundaries,
            duration,
        )
        added_count = len(merged_boundaries) - len(existing_boundaries)

        if added_count > 0:
            self.timeline_widget.replace_boundaries(merged_boundaries)
            self.log_widget.append_log(
                f"シーン自動検出: {added_count} 個の分割候補を追加しました"
            )
        else:
            self.log_widget.append_log("シーン自動検出: 新しい分割候補はありませんでした")

        self.log_widget.set_status(f"編集中: {self.current_job.filename}")
        self._finish_scene_detection()

    def _on_scene_detection_error(self, message: str):
        """シーン自動検出エラー"""
        self.log_widget.append_log(f"[ERROR] {message}")
        self.log_widget.set_status("シーン自動検出エラー")
        QMessageBox.warning(self, "シーン自動検出エラー", message)
        self._finish_scene_detection()

    def _finish_scene_detection(self):
        """シーン自動検出スレッドを片付ける"""
        if self.scene_detection_thread:
            self.scene_detection_thread.quit()
            self.scene_detection_thread.wait()
            self.scene_detection_thread = None
            self.scene_detection_worker = None
        self.timeline_widget.set_auto_detect_enabled(self.current_job is not None)

    def _update_timeline(self, job: VideoJob):
        """タイムラインを更新"""
        if not job.scenes:
            return
        scene_start_times = [scene.start_time for scene in job.scenes]
        duration = job.scenes[-1].end_time
        self.timeline_widget.set_scenes(scene_start_times, duration)

    def _on_export_requested(self, job: VideoJob, output_dir: Path, auto_split: bool):
        """書き出しリクエスト"""
        if self.export_thread and self.export_thread.isRunning():
            QMessageBox.warning(self, "警告", "書き出し中です")
            return

        self.log_widget.clear_log()
        self.log_widget.set_status(f"書き出し中: {job.filename}")
        self.log_widget.hide_progress()

        # ワーカーとスレッドを作成
        self.export_thread = QThread()
        self.export_worker = ExportWorker(job, output_dir, auto_split=auto_split)
        self.export_worker.moveToThread(self.export_thread)

        # シグナル接続
        self.export_thread.started.connect(self.export_worker.run)
        self.export_worker.progress.connect(self._on_progress)
        self.export_worker.clip_progress.connect(self._on_clip_progress)
        self.export_worker.export_complete.connect(self._on_export_complete)
        self.export_worker.error.connect(self._on_error)

        self.export_thread.start()

    def _on_progress(self, message: str):
        self.log_widget.append_log(message)

    def _on_clip_progress(self, current: int, total: int):
        self.log_widget.set_progress_bar(current, total)
        self.log_widget.set_detail(f"書き出し中: {current} / {total} クリップ")

    def _on_export_complete(self, job: VideoJob):
        """書き出し完了（失敗・キャンセルを含む）"""
        self.log_widget.hide_progress()

        if self.export_thread:
            self.export_thread.quit()
            self.export_thread.wait()
            self.export_thread = None
            self.export_worker = None

        self.queue_widget.refresh()

        if job.status == JobStatus.DONE:
            self.log_widget.set_status("書き出し完了")
            QMessageBox.information(
                self,
                "書き出し完了",
                f"{job.filename} の書き出しが完了しました。\n"
                f"出力先: {job.output_dir}\n"
                f"クリップ数: {len(job.clips)}"
            )
        elif job.status == JobStatus.ERROR:
            self.log_widget.set_status("書き出し失敗")
            QMessageBox.warning(
                self,
                "書き出し失敗",
                f"{job.filename} の書き出しに失敗しました。\n"
                f"{job.error_message}\n\n"
                f"詳細はログを確認してください。"
            )
        else:
            # キャンセル時
            self.log_widget.set_status("書き出しキャンセル")

    def _on_error(self, message: str):
        """エラー発生"""
        self.log_widget.append_log(f"[ERROR] {message}")
        self.log_widget.set_status("エラー")
        self.log_widget.hide_progress()

        if self.export_thread:
            self.export_thread.quit()
            self.export_thread.wait()
            self.export_thread = None
            self.export_worker = None

        self.queue_widget.refresh()

    def _apply_theme(self):
        """ダークテーマを適用"""
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #1e1e1e;
                color: #d4d4d4;
            }
            QPushButton {
                background-color: #3c3c3c;
                color: #d4d4d4;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
                border-color: #777;
            }
            QPushButton:pressed {
                background-color: #555;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                color: #666;
                border-color: #444;
            }
            QPushButton#btn_split {
                background-color: #2d5a2d;
                border-color: #4a8c4a;
                font-weight: bold;
            }
            QPushButton#btn_split:hover {
                background-color: #3a7a3a;
            }
            QPushButton#btn_export {
                background-color: #2d4a7a;
                border-color: #4a7abc;
                font-weight: bold;
            }
            QPushButton#btn_export:hover {
                background-color: #3a5a8a;
            }
            QTableWidget {
                background-color: #252526;
                color: #d4d4d4;
                gridline-color: #3c3c3c;
                border: 1px solid #3c3c3c;
                selection-background-color: #264f78;
            }
            QTableWidget::item {
                padding: 4px;
            }
            QHeaderView::section {
                background-color: #333;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                padding: 4px;
            }
            QLineEdit {
                background-color: #333;
                color: #d4d4d4;
                border: 1px solid #555;
                border-radius: 2px;
                padding: 3px 6px;
            }
            QLineEdit:focus {
                border-color: #007acc;
            }
            QComboBox {
                background-color: #333;
                color: #d4d4d4;
                border: 1px solid #555;
                border-radius: 2px;
                padding: 3px 6px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #333;
                color: #d4d4d4;
                selection-background-color: #264f78;
            }
            QCheckBox {
                color: #d4d4d4;
                spacing: 5px;
            }
            QLabel {
                color: #d4d4d4;
            }
            QScrollArea {
                border: 1px solid #3c3c3c;
            }
            QDateEdit {
                background-color: #333;
                color: #d4d4d4;
                border: 1px solid #555;
                border-radius: 2px;
                padding: 3px;
            }
            QSlider::groove:horizontal {
                background: #3c3c3c;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #d4d4d4;
                width: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
            QSplitter::handle {
                background-color: #3c3c3c;
                width: 3px;
            }
            QProgressBar {
                background-color: #333;
                border: 1px solid #555;
                border-radius: 3px;
                text-align: center;
                color: #d4d4d4;
            }
            QProgressBar::chunk {
                background-color: #007acc;
                border-radius: 2px;
            }
        """)

    def _setup_shortcuts(self):
        """キーボードショートカットを設定"""
        # Space: 再生/一時停止
        s = QShortcut(QKeySequence(Qt.Key_Space), self)
        s.activated.connect(self._shortcut_play_pause)

        # S: ここで分割
        s = QShortcut(QKeySequence(Qt.Key_S), self)
        s.activated.connect(self._shortcut_split)

        # 左矢印: コマ戻し
        s = QShortcut(QKeySequence(Qt.Key_Left), self)
        s.activated.connect(self.preview_widget.step_back)

        # 右矢印: コマ送り
        s = QShortcut(QKeySequence(Qt.Key_Right), self)
        s.activated.connect(self.preview_widget.step_forward)

        # Ctrl+Z: Undo
        s = QShortcut(QKeySequence("Ctrl+Z"), self)
        s.activated.connect(self._shortcut_undo)

    def _shortcut_play_pause(self):
        """Space: 再生/一時停止（テキスト入力中は無視）"""
        focused = QApplication.focusWidget()
        from PySide6.QtWidgets import QLineEdit, QTextEdit
        if isinstance(focused, (QLineEdit, QTextEdit)):
            return
        if self.preview_widget.current_video_path:
            self.preview_widget.toggle_play()

    def _shortcut_split(self):
        """S: 分割（テキスト入力中は無視）"""
        focused = QApplication.focusWidget()
        from PySide6.QtWidgets import QLineEdit, QTextEdit
        if isinstance(focused, (QLineEdit, QTextEdit)):
            return
        self.preview_widget.request_split()

    def _shortcut_undo(self):
        """Ctrl+Z: 直前の境界操作を取り消し"""
        if not self._undo_stack:
            return
        prev = self._undo_stack.pop()
        self._undoing = True
        try:
            self.timeline_widget.replace_boundaries(prev)
        finally:
            self._undoing = False

    def _on_player_error(self, message: str):
        """プレイヤーエラーをログに表示"""
        self.log_widget.append_log(f"[ERROR] {message}")
        self.log_widget.set_status("再生エラー")

    def _on_toggle_log(self):
        """ログ表示/非表示"""
        if self.log_widget.isVisible():
            self.log_widget.hide()
            self.btn_toggle_log.setText("ログ表示")
        else:
            self.log_widget.show()
            self.btn_toggle_log.setText("ログ非表示")

    def closeEvent(self, event):
        """ウィンドウ閉じる時"""
        if self.export_thread and self.export_thread.isRunning():
            reply = QMessageBox.question(
                self,
                "確認",
                "書き出し中です。終了しますか？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                event.ignore()
                return

            if self.export_worker:
                self.export_worker.cancel()
            self.export_thread.quit()
            self.export_thread.wait()

        if self.scene_detection_thread and self.scene_detection_thread.isRunning():
            if self.scene_detection_worker:
                self.scene_detection_worker.cancel()
            self.scene_detection_thread.quit()
            self.scene_detection_thread.wait()

        if self.thumbnail_thread and self.thumbnail_thread.isRunning():
            if self.thumbnail_worker:
                self.thumbnail_worker.cancel()
            self.thumbnail_thread.quit()
            self.thumbnail_thread.wait()

        self.preview_widget.cleanup()

        # 一時ディレクトリを削除
        import shutil
        import logging
        try:
            shutil.rmtree(self.temp_dir)
        except PermissionError as e:
            logging.warning(f"一時ディレクトリの削除に失敗: {self.temp_dir}: {e}")
        except FileNotFoundError:
            pass
        except OSError as e:
            logging.warning(f"一時ディレクトリの削除に失敗: {self.temp_dir}: {e}")

        event.accept()
