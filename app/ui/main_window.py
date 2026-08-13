"""
メインウィンドウ
"""
import tempfile
from pathlib import Path
from typing import List, Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout,
    QSplitter, QPushButton, QMessageBox, QApplication,
    QAbstractButton, QAbstractItemView, QAbstractSlider,
    QAbstractSpinBox, QComboBox, QLineEdit, QTextEdit, QStackedLayout, QDialog,
    QStackedWidget,
)
from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtGui import QShortcut, QKeySequence

from app.core import JobQueue, VideoJob, JobStatus, Scene
from app.core.ffmpeg_runner import FFmpegRunner
from app.core.time_format import format_seconds
from app.ui.queue_widget import QueueWidget
from app.ui.clip_list_widget import ClipListWidget
from app.ui.log_widget import LogWidget
from app.ui.merge_dialog import MergeProposalDialog
from app.ui.batch_progress_dialog import BatchProgressDialog
from app.ui.bulk_metadata_dialog import BulkMetadataDialog
from app.ui.preview_widget import PreviewWidget
from app.ui.timeline_widget import TimelineWidget
from app.ui.filmstrip_review_widget import FilmstripReviewWidget
from app.ui.drop_zone import VideoDropZone
from app.ui.workers import (
    ThumbnailWorker, ExportWorker, SceneDetectionWorker,
    DateDetectionWorker, BlankDetectionWorker, BatchSceneDetectionWorker,
    BoundaryPreviewWorker, MediaSignalWorker,
)
from app.core.scene_detector import absorb_short_scenes
from app.core.session_store import SessionStore
from app.core.edit_history import JobEditSnapshot
from app.core.metadata import apply_bulk_metadata
from app.core.media_signal_detector import apply_media_signal_result
from app.core.review import clear_date_review_acknowledgements


def _boundaries_equal(left: List[float], right: List[float], tolerance: float = 1e-6) -> bool:
    """境界リストが実質同じか判定する"""
    if len(left) != len(right):
        return False
    return all(abs(a - b) <= tolerance for a, b in zip(left, right))


class MainWindow(QMainWindow):
    """メインウィンドウ"""

    def __init__(
        self,
        session_store: Optional[SessionStore] = None,
        autosave_interval_ms: int = 300,
    ):
        super().__init__()

        self._session_store = session_store
        self._session_warning = ""
        restored_current_job_id = None
        if session_store is None:
            self.job_queue = JobQueue()
        else:
            restored = session_store.load()
            self.job_queue = restored.job_queue
            restored_current_job_id = restored.current_job_id
            self._session_warning = restored.warning
        self.temp_dir = Path(tempfile.mkdtemp(prefix="video_scene_splitter_"))
        self.current_job: VideoJob = None
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(max(0, autosave_interval_ms))
        self._autosave_timer.timeout.connect(self._flush_autosave)

        self.thumbnail_thread: QThread = None
        self.thumbnail_worker: ThumbnailWorker = None
        self.boundary_preview_thread: QThread = None
        self.boundary_preview_worker: BoundaryPreviewWorker = None
        self.media_signal_thread: QThread = None
        self.media_signal_worker: MediaSignalWorker = None
        self.export_thread: QThread = None
        self.export_worker: ExportWorker = None
        self.scene_detection_thread: QThread = None
        self.scene_detection_worker: SceneDetectionWorker = None
        self._scene_detection_result_received = False
        self.date_detection_thread: QThread = None
        self.date_detection_worker: DateDetectionWorker = None
        self._date_detect_auto = False
        self.blank_detection_thread: QThread = None
        self.blank_detection_worker: BlankDetectionWorker = None
        self._pending_blank_segments: Optional[list] = None
        self.batch_detection_thread: QThread = None
        self.batch_detection_worker: BatchSceneDetectionWorker = None
        self.batch_progress_dialog: BatchProgressDialog = None
        self._batch_cancel_requested = False
        self._batch_error = False
        self._defer_thumbnail_regen = False
        self._thumbnail_regen_pending = False

        # 境界・メタデータ・書き出し設定を含む編集履歴
        self._undo_stack: List[JobEditSnapshot] = []
        self._redo_stack: List[JobEditSnapshot] = []
        self._last_boundaries: Optional[List[float]] = None
        self._restoring_history = False

        self._setup_ui()
        self._apply_theme()
        self._connect_signals()
        self._setup_shortcuts()
        self._restore_session_ui(restored_current_job_id)

    def _setup_ui(self):
        self.setWindowTitle("Video Scene Splitter")
        self.setMinimumSize(960, 640)

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        self.workspace_stack = QStackedWidget()

        # メインスプリッター（左: キュー、中央: プレビュー+タイムライン、右: クリップリスト）
        splitter = QSplitter(Qt.Horizontal)
        self.editor_splitter = splitter

        # 左側: キュー
        self.queue_widget = QueueWidget(self.job_queue)
        self.queue_widget.setMinimumWidth(200)
        self.queue_widget.setMaximumWidth(320)
        splitter.addWidget(self.queue_widget)

        # 中央: プレビュー + タイムライン
        center_widget = QWidget()
        self.center_stack = QStackedLayout(center_widget)
        self.center_stack.setContentsMargins(0, 0, 0, 0)

        self.drop_zone = VideoDropZone()
        self.center_stack.addWidget(self.drop_zone)

        self.editor_center = QWidget()
        center_layout = QVBoxLayout(self.editor_center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(5)

        self.preview_widget = PreviewWidget()
        center_layout.addWidget(self.preview_widget, stretch=1)

        self.timeline_widget = TimelineWidget()
        center_layout.addWidget(self.timeline_widget)
        self.center_stack.addWidget(self.editor_center)
        self.center_stack.setCurrentWidget(self.drop_zone)

        splitter.addWidget(center_widget)

        # 右側: クリップリスト
        self.clip_list_widget = ClipListWidget()
        self.clip_list_widget.setMinimumWidth(340)
        self.clip_list_widget.hide()
        splitter.addWidget(self.clip_list_widget)

        splitter.setSizes([210, 560, 420])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 1)
        self.workspace_stack.addWidget(splitter)

        self.filmstrip_review_widget = FilmstripReviewWidget()
        self.workspace_stack.addWidget(self.filmstrip_review_widget)
        self.workspace_stack.setCurrentWidget(splitter)
        main_layout.addWidget(self.workspace_stack, stretch=1)

        # 下部: コンパクトな状態表示。詳細ログは内部の開閉操作で表示する。
        self.log_widget = LogWidget()
        main_layout.addWidget(self.log_widget)

    def _connect_signals(self):
        # キュー → 動画を開く
        self.queue_widget.open_video.connect(self._on_open_video)
        self.queue_widget.job_selected.connect(self._on_job_selected)
        self.queue_widget.remove_requested.connect(self._on_remove_job)
        self.queue_widget.detect_all_requested.connect(self._on_detect_all_requested)
        self.queue_widget.bulk_metadata_requested.connect(
            self._on_bulk_metadata_requested
        )
        self.queue_widget.clip_preview_requested.connect(self._on_queue_clip_preview)
        self.queue_widget.queue_changed.connect(self._schedule_autosave)
        self.drop_zone.add_requested.connect(self.queue_widget.action_add_file.trigger)
        self.drop_zone.paths_dropped.connect(self.queue_widget.add_paths)

        # プレビュー → タイムライン同期
        self.preview_widget.position_changed.connect(self.timeline_widget.set_playhead)
        self.preview_widget.position_changed.connect(
            self.filmstrip_review_widget.set_playhead
        )

        # プレビュー → 分割
        self.preview_widget.split_requested.connect(self._on_split_at_position)

        # プレビュー → 再生エラー
        self.preview_widget.error_occurred.connect(self._on_player_error)

        # タイムライン → シーク
        self.timeline_widget.seek_requested.connect(self.preview_widget.seek_to)

        # フィルムレビュー → シーク／通常編集へ戻る
        self.filmstrip_review_widget.seek_requested.connect(
            self.preview_widget.seek_to
        )
        self.filmstrip_review_widget.edit_requested.connect(
            self._on_filmstrip_edit_requested
        )
        self.timeline_widget.filmstrip_review_requested.connect(
            lambda: self._set_workspace_view(True)
        )

        # タイムライン → 境界変更
        self.timeline_widget.boundaries_changed.connect(self._on_boundaries_changed)
        self.timeline_widget.auto_detect_requested.connect(self._on_auto_detect_requested)
        self.timeline_widget.auto_detect_cancel_requested.connect(self._on_auto_detect_cancel)
        self.timeline_widget.blank_trim_requested.connect(self._on_blank_detect_requested)
        self.timeline_widget.blank_trim_cancel_requested.connect(self._on_blank_detect_cancel)
        self.timeline_widget.boundary_review_requested.connect(
            self._on_boundary_review_requested
        )
        self.timeline_widget.boundary_candidates_applied.connect(
            self._on_boundary_candidates_applied
        )
        self.timeline_widget.scene_detection_preview_applied.connect(
            self._on_scene_detection_preview_applied
        )

        # クリップリスト → プレビュー
        self.clip_list_widget.clip_preview_requested.connect(self._on_clip_preview)
        self.clip_list_widget.blank_preview_requested.connect(
            self._on_blank_preview_requested
        )
        self.clip_list_widget.blank_trim_confirmed.connect(
            self._on_blank_trim_confirmed
        )
        self.clip_list_widget.blank_trim_cancelled.connect(
            self._on_blank_trim_cancelled
        )

        # クリップリスト → 書き出し
        self.clip_list_widget.export_requested.connect(self._on_export_requested)
        self.clip_list_widget.export_cancel_requested.connect(
            self._on_export_cancel_requested
        )

        # クリップリスト → シーン結合
        self.clip_list_widget.merge_requested.connect(self._on_merge_scenes_requested)
        self.clip_list_widget.short_merge_requested.connect(self._on_short_merge_requested)

        # クリップリスト → 日付検出
        self.clip_list_widget.date_detect_requested.connect(self._on_date_detect_requested)
        self.clip_list_widget.date_detect_cancel_requested.connect(self._on_date_detect_cancel)
        self.clip_list_widget.media_signal_requested.connect(
            self._on_media_signal_requested
        )
        self.clip_list_widget.media_signal_cancel_requested.connect(
            self._on_media_signal_cancel_requested
        )
        self.clip_list_widget.edit_started.connect(self._push_edit_snapshot)
        self.clip_list_widget.job_changed.connect(self._on_job_edited)

    def _restore_session_ui(self, current_job_id: Optional[int]):
        """保存済みキューと編集中ジョブを画面へ復元する。"""
        self.queue_widget.refresh()
        if self._session_warning:
            self.log_widget.set_status("復元できない保存データがあります")
            self.log_widget.append_log(self._session_warning)

        job = self.job_queue.get_job_by_id(current_job_id) if current_job_id else None
        if job is None or job.status not in (JobStatus.REVIEW, JobStatus.DONE):
            return
        self.current_job = job
        self._show_editor_layout()
        self.clip_list_widget.set_job(job)
        self.preview_widget.load_video(job.source_path)
        self._update_timeline(job)
        self.queue_widget.select_job(job.id)
        self.log_widget.set_status(f"復元: {job.filename}")
        self._last_boundaries = [scene.start_time for scene in job.scenes]
        self._regenerate_thumbnails()

    def _show_editor_layout(self):
        self.center_stack.setCurrentWidget(self.editor_center)
        self.clip_list_widget.show()

    def _show_empty_layout(self):
        self._set_workspace_view(False)
        self.center_stack.setCurrentWidget(self.drop_zone)
        self.clip_list_widget.hide()
        self.filmstrip_review_widget.set_job(None)

    def _set_workspace_view(self, filmstrip: bool):
        """通常編集と全体レビューを切り替える。"""
        show_filmstrip = bool(
            filmstrip and self.current_job is not None and self.current_job.scenes
        )
        if show_filmstrip:
            self._sync_filmstrip_candidates()
            self.filmstrip_review_widget.refresh()
            self.filmstrip_review_widget.set_playhead(
                self.preview_widget.get_position()
            )
            self.workspace_stack.setCurrentWidget(self.filmstrip_review_widget)
        else:
            self.workspace_stack.setCurrentWidget(self.editor_splitter)

    def _on_filmstrip_edit_requested(self, position: float):
        """レビュー位置を保ったまま通常編集へ戻る。"""
        self.preview_widget.seek_to(position)
        self._set_workspace_view(False)

    def _sync_filmstrip_candidates(self):
        """解析由来とシーン検出由来の未適用候補をまとめて表示する。"""
        if self.current_job is None:
            self.filmstrip_review_widget.set_candidate_times([])
            return
        candidates = list(self.current_job.suggested_boundaries)
        candidates.extend(self.timeline_widget.detection_preview_times)
        self.filmstrip_review_widget.set_candidate_times(candidates)

    def _schedule_autosave(self):
        if self._session_store is not None:
            self._autosave_timer.start()

    def _flush_autosave(self):
        if self._session_store is None:
            return
        current_job_id = self.current_job.id if self.current_job else None
        try:
            self._session_store.save(self.job_queue, current_job_id=current_job_id)
        except OSError as exc:
            self.log_widget.set_status("自動保存に失敗")
            self.log_widget.append_log(f"[ERROR] 自動保存に失敗しました: {exc}")

    def _push_edit_snapshot(self):
        """変更直前の編集状態をUndo履歴へ積む。"""
        if self.current_job is None or self._restoring_history:
            return
        self._append_edit_snapshot(JobEditSnapshot.capture(self.current_job))

    def _append_edit_snapshot(self, snapshot: JobEditSnapshot):
        if not self._undo_stack or self._undo_stack[-1] != snapshot:
            self._undo_stack.append(snapshot)
            del self._undo_stack[:-100]
        self._redo_stack.clear()

    def _on_job_edited(self):
        self.queue_widget.refresh()
        self.filmstrip_review_widget.refresh()
        self._schedule_autosave()

    def _restore_edit_snapshot(self, snapshot: JobEditSnapshot):
        if self.current_job is None:
            return
        previous_boundaries = [scene.start_time for scene in self.current_job.scenes]
        self._restoring_history = True
        try:
            snapshot.apply_to(self.current_job)
            boundaries = [scene.start_time for scene in self.current_job.scenes]
            self._last_boundaries = list(boundaries)
            self.clip_list_widget.set_job(self.current_job)
            self.timeline_widget.set_scenes(
                boundaries,
                self.current_job.scenes[-1].end_time if self.current_job.scenes else 0,
            )
            self.timeline_widget.set_boundary_candidates(
                self.current_job.suggested_boundaries
            )
            self.filmstrip_review_widget.set_job(self.current_job)
            self.queue_widget.refresh()
            if not _boundaries_equal(previous_boundaries, boundaries):
                self._regenerate_thumbnails()
        finally:
            self._restoring_history = False
        self._schedule_autosave()

    def _on_job_selected(self, job: VideoJob):
        """ジョブ選択時（既に編集中のジョブを表示）"""
        if job is self.current_job:
            return
        if job.status in [JobStatus.REVIEW, JobStatus.DONE]:
            self._stop_boundary_preview_worker()
            self._stop_media_signal_worker()
            self.current_job = job
            self._show_editor_layout()
            self.clip_list_widget.set_job(job)
            self.preview_widget.load_video(job.source_path)
            self._update_timeline(job)
            # ジョブをまたいだUndoは破壊的なのでリセット
            self._undo_stack.clear()
            self._redo_stack.clear()
            self._last_boundaries = [s.start_time for s in job.scenes]
            self._regenerate_thumbnails()

    def _on_remove_job(self, job_id: int):
        """キューからのジョブ削除リクエスト"""
        if (self.export_thread and self.export_thread.isRunning()
                and self.export_worker and self.export_worker.job.id == job_id):
            QMessageBox.warning(self, "警告", "書き出し中のジョブは削除できません")
            return

        job = self.job_queue.get_job_by_id(job_id)
        if job is None:
            return
        reply = QMessageBox.question(
            self,
            "キューから削除",
            f"{job.filename} をキューから削除しますか？\n"
            "分割位置やクリップの編集内容も失われます。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        removing_current = self.current_job is not None and self.current_job.id == job_id

        if removing_current:
            self._stop_thumbnail_worker()
            self._stop_boundary_preview_worker()
            self._stop_media_signal_worker()
            if self.scene_detection_thread and self.scene_detection_thread.isRunning():
                if self.scene_detection_worker:
                    self.scene_detection_worker.cancel()
                self.scene_detection_thread.quit()
                self.scene_detection_thread.wait()
                self.scene_detection_thread = None
                self.scene_detection_worker = None
            if self.date_detection_thread and self.date_detection_thread.isRunning():
                if self.date_detection_worker:
                    self.date_detection_worker.cancel()
                self.date_detection_thread.quit()
                self.date_detection_thread.wait()
                self.date_detection_thread = None
                self.date_detection_worker = None
                self.clip_list_widget.set_date_detecting(False)
            if self.blank_detection_thread and self.blank_detection_thread.isRunning():
                if self.blank_detection_worker:
                    self.blank_detection_worker.cancel()
                self.blank_detection_thread.quit()
                self.blank_detection_thread.wait()
                self.blank_detection_thread = None
                self.blank_detection_worker = None
                self.clip_list_widget.set_blank_detecting(False)
                self.timeline_widget.set_blank_trimming(False)

        self.job_queue.remove_job(job_id)
        self.queue_widget.refresh()
        self._schedule_autosave()

        if removing_current:
            self.current_job = None
            self._undo_stack.clear()
            self._last_boundaries = None
            self.preview_widget.cleanup()
            self.timeline_widget.clear()
            self.clip_list_widget.clear()
            self._show_empty_layout()
            self.log_widget.set_status("待機中")

    def _on_queue_clip_preview(self, job: VideoJob, start_time: float):
        """キューのツリーでクリップを選んだとき、その動画を表示して頭出しする。

        これはプレビュー操作なので、needs_post_process のバックグラウンド処理は
        起動しない。処理は動画を明示的に開いた時だけ行う。
        """
        if self.current_job is not job:
            self._on_job_selected(job)
        self.preview_widget.seek_to(start_time)

    def _on_detect_all_requested(self):
        """待機中の全動画にシーン検出を一括実行"""
        if self.batch_detection_thread and self.batch_detection_thread.isRunning():
            if self.batch_progress_dialog:
                self.batch_progress_dialog.show()
                self.batch_progress_dialog.raise_()
                self.batch_progress_dialog.activateWindow()
            return

        jobs = [j for j in self.job_queue.get_all_jobs() if j.status == JobStatus.WAITING]
        if not jobs:
            QMessageBox.information(
                self, "一括シーン検出",
                "検出対象（待機中）の動画がありません。\n"
                "既に開いた動画はそれぞれの画面で検出してください。"
            )
            return

        self.log_widget.clear_log()
        self.log_widget.set_status("一括シーン検出中")
        self.log_widget.append_log(f"{len(jobs)} 本の動画をシーン検出します...")
        self.queue_widget.set_detect_all_enabled(False)
        self._batch_cancel_requested = False
        self._batch_error = False

        if self.batch_progress_dialog:
            self.batch_progress_dialog.close()
            self.batch_progress_dialog.deleteLater()
        self.batch_progress_dialog = BatchProgressDialog(len(jobs), self)
        self.batch_progress_dialog.cancel_requested.connect(self._on_batch_detect_cancel)
        self.batch_progress_dialog.show()

        self.batch_detection_thread = QThread()
        self.batch_detection_worker = BatchSceneDetectionWorker(
            jobs, settings=self.timeline_widget.get_detection_settings()
        )
        self.batch_detection_worker.moveToThread(self.batch_detection_thread)

        self.batch_detection_thread.started.connect(self.batch_detection_worker.run)
        self.batch_detection_worker.progress.connect(self._on_batch_detect_progress)
        self.batch_detection_worker.progress_percent.connect(self._on_batch_detect_percent)
        self.batch_detection_worker.video_done.connect(self._on_batch_video_done)
        self.batch_detection_worker.error.connect(self._on_batch_detect_error)
        self.batch_detection_worker.finished.connect(self._on_batch_detect_finished)

        self.batch_detection_thread.start()

    def _on_bulk_metadata_requested(self):
        jobs = self.job_queue.get_all_jobs()
        if not jobs:
            return
        selected = self.queue_widget.get_selected_job()
        selected_id = selected.id if selected else (
            self.current_job.id if self.current_job else None
        )
        dialog = BulkMetadataDialog(jobs, selected_id, self)
        if dialog.exec() != QDialog.Accepted:
            return
        selected_ids = set(dialog.selected_job_ids())
        selected_jobs = [
            job for job in jobs if job.id in selected_ids
        ]
        current_before = (
            JobEditSnapshot.capture(self.current_job)
            if self.current_job is not None
            and self.current_job.id in selected_ids
            else None
        )
        changed = apply_bulk_metadata(selected_jobs, dialog.metadata_update())
        if not changed:
            return
        if current_before is not None:
            self._append_edit_snapshot(current_before)
            self.clip_list_widget.set_job(self.current_job)
        self.queue_widget.refresh()
        self.log_widget.append_log(f"{changed}本の動画へ情報をまとめて反映しました")
        self._schedule_autosave()

    def _on_batch_detect_progress(self, message: str):
        self._on_progress(message)
        if self.batch_progress_dialog:
            self.batch_progress_dialog.set_current_message(message)

    def _on_batch_detect_percent(self, percent: int):
        self.log_widget.set_progress_bar(percent, 100)
        self.log_widget.set_detail(f"一括シーン検出中: {percent}%")
        if self.batch_progress_dialog:
            self.batch_progress_dialog.set_progress(percent)

    def _on_batch_video_done(self, job_id: int, scene_count: int):
        job = self.job_queue.get_job_by_id(job_id)
        name = job.filename if job else f"job {job_id}"
        message = f"検出完了: {name} → {scene_count}本"
        self.log_widget.append_log(message)
        if self.batch_progress_dialog:
            self.batch_progress_dialog.add_result(message)
        self.queue_widget.refresh()
        self._schedule_autosave()

    def _on_batch_detect_error(self, message: str):
        self._batch_error = True
        self.log_widget.append_log(f"[ERROR] {message}")
        if self.batch_progress_dialog:
            self.batch_progress_dialog.add_result(f"[ERROR] {message}")
        self.queue_widget.refresh()
        self._schedule_autosave()

    def _on_batch_detect_cancel(self):
        self._batch_cancel_requested = True
        self.log_widget.append_log("一括シーン検出をキャンセルしています...")
        if self.batch_detection_worker:
            self.batch_detection_worker.cancel()

    def _on_batch_detect_finished(self):
        if self.sender() is not self.batch_detection_worker:
            return
        self.log_widget.hide_progress()
        if self._batch_error:
            finished_message = "一括シーン検出完了（一部エラー）"
        elif self._batch_cancel_requested:
            finished_message = "一括シーン検出をキャンセルしました"
        else:
            finished_message = "一括シーン検出完了"
        self.log_widget.set_status(finished_message)
        if self.batch_detection_thread:
            self.batch_detection_thread.quit()
            self.batch_detection_thread.wait()
            self.batch_detection_thread = None
            self.batch_detection_worker = None
        self.queue_widget.set_detect_all_enabled(True)
        self.queue_widget.refresh()
        self._schedule_autosave()
        if self.batch_progress_dialog:
            self.batch_progress_dialog.set_finished(finished_message)

    def _on_open_video(self, job: VideoJob):
        """動画を開いて編集開始"""
        if not job:
            return

        self._stop_boundary_preview_worker()
        self._stop_media_signal_worker()

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

        will_finish_detection = job.needs_post_process
        if will_finish_detection:
            self._begin_deferred_thumbnails()

        self.log_widget.append_log(f"動画の長さ: {format_seconds(duration)}")

        # 一括検出済みなどで既にシーンがある場合はそれを保持し、
        # 無い場合のみ動画全体を1シーンとして初期化する
        if not job.scenes:
            job.scenes = [Scene(index=1, start_time=0.0, end_time=duration, keep=True)]
        job.status = JobStatus.REVIEW
        self.current_job = job
        self._show_editor_layout()

        boundaries = [s.start_time for s in job.scenes]
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._last_boundaries = list(boundaries)

        # UIを更新
        self.queue_widget.refresh()
        self.clip_list_widget.set_job(job)
        self.preview_widget.load_video(job.source_path)
        self._update_timeline(job)

        # サムネイルはバックグラウンドで生成（UIをブロックしない）
        self._regenerate_thumbnails()

        self.log_widget.append_log("編集を開始しました")
        if len(job.scenes) > 1:
            self.log_widget.append_log(f"検出済みクリップ: {len(job.scenes)}本")
        else:
            self.log_widget.append_log(
                "「分割 [S]」ボタンまたはタイムライン右クリックで境界を追加"
            )

        # 一括検出済みの動画も補正モーダルでは遮らず、日付検出だけ裏で続ける。
        if job.needs_post_process:
            job.needs_post_process = False
            self.log_widget.append_log(
                "単色区間はタイムラインの「単色区間をトリミング」、"
                "結合などは「補正ツール」から確認できます"
            )
            if not self._start_date_detection(auto=True):
                self._finish_deferred_thumbnails()
        self._schedule_autosave()

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
        if self._last_boundaries is not None and _boundaries_equal(boundaries, self._last_boundaries):
            return

        duration = self.current_job.scenes[-1].end_time if self.current_job.scenes else 0

        # タイムラインはUI側が先に変わるため、モデル再構築前に履歴を保存する。
        self._push_edit_snapshot()
        self._last_boundaries = list(boundaries)

        # シーンを再構築
        self.current_job.rebuild_scenes_from_boundaries(boundaries, duration)
        remaining_candidates = [
            candidate
            for candidate in self.current_job.suggested_boundaries
            if not any(abs(candidate - boundary) < 0.05 for boundary in boundaries)
        ]
        if remaining_candidates != self.current_job.suggested_boundaries:
            self.current_job.suggested_boundaries = remaining_candidates
            self.timeline_widget.set_boundary_candidates(remaining_candidates)

        # クリップリストを更新
        self.clip_list_widget.refresh_clips()

        # サムネイルを再生成
        self._regenerate_thumbnails()

        self.log_widget.append_log(
            f"クリップ数: {len(self.current_job.scenes)}"
        )
        self._on_job_edited()

    def _stop_thumbnail_worker(self):
        """サムネイルワーカーを停止して破棄"""
        if self.thumbnail_thread and self.thumbnail_thread.isRunning():
            if self.thumbnail_worker:
                self.thumbnail_worker.cancel()
            self.thumbnail_thread.quit()
            self.thumbnail_thread.wait()

        self.thumbnail_thread = None
        self.thumbnail_worker = None

    def _stop_boundary_preview_worker(self):
        if self.boundary_preview_thread and self.boundary_preview_thread.isRunning():
            if self.boundary_preview_worker:
                self.boundary_preview_worker.cancel()
            self.boundary_preview_thread.quit()
            self.boundary_preview_thread.wait()
        self.boundary_preview_thread = None
        self.boundary_preview_worker = None

    def _stop_media_signal_worker(self):
        """音声・フェード解析を停止し、ジョブ切替後の結果混入を防ぐ。"""
        if self.media_signal_thread and self.media_signal_thread.isRunning():
            if self.media_signal_worker:
                self.media_signal_worker.cancel()
            self.media_signal_thread.quit()
            self.media_signal_thread.wait()
        self.media_signal_thread = None
        self.media_signal_worker = None
        self.clip_list_widget.set_media_signal_analyzing(False)

    def _on_boundary_review_requested(self, boundary_time: float):
        if not self.current_job or not self.current_job.scenes:
            return
        self._stop_boundary_preview_worker()
        duration = self.current_job.scenes[-1].end_time
        self.boundary_preview_thread = QThread()
        self.boundary_preview_worker = BoundaryPreviewWorker(
            self.current_job,
            boundary_time,
            duration,
            self.temp_dir,
        )
        self.boundary_preview_worker.moveToThread(self.boundary_preview_thread)
        self.boundary_preview_thread.started.connect(
            self.boundary_preview_worker.run
        )
        self.boundary_preview_worker.preview_ready.connect(
            self.timeline_widget.show_boundary_preview
        )
        self.boundary_preview_worker.error.connect(
            self.timeline_widget.boundary_review_status.setText
        )
        self.boundary_preview_worker.finished.connect(
            self._on_boundary_preview_finished
        )
        self.boundary_preview_thread.start()

    def _on_boundary_preview_finished(self):
        if self.sender() is not self.boundary_preview_worker:
            return
        if self.boundary_preview_thread:
            self.boundary_preview_thread.quit()
            self.boundary_preview_thread.wait()
        self.boundary_preview_thread = None
        self.boundary_preview_worker = None

    def _on_media_signal_requested(self):
        """無音・フェード解析を開始し、結果は未適用候補として扱う。"""
        if not self.current_job or not self.current_job.scenes:
            return
        if self.media_signal_thread and self.media_signal_thread.isRunning():
            return

        duration = self.current_job.scenes[-1].end_time
        self.log_widget.append_log("音声・フェード解析を開始しました")
        self.log_widget.set_status("音声・フェード解析中")
        self.clip_list_widget.set_media_signal_analyzing(True)

        self.media_signal_thread = QThread()
        self.media_signal_worker = MediaSignalWorker(self.current_job, duration)
        self.media_signal_worker.moveToThread(self.media_signal_thread)
        self.media_signal_thread.started.connect(self.media_signal_worker.run)
        self.media_signal_worker.progress.connect(self._on_progress)
        self.media_signal_worker.progress_percent.connect(
            self._on_media_signal_percent
        )
        self.media_signal_worker.analysis_complete.connect(
            self._on_media_signal_complete
        )
        self.media_signal_worker.error.connect(self._on_media_signal_error)
        self.media_signal_worker.finished.connect(self._on_media_signal_finished)
        self.media_signal_thread.start()

    def _on_media_signal_cancel_requested(self):
        if self.media_signal_worker:
            self.media_signal_worker.cancel()
            self.log_widget.append_log("音声・フェード解析を中止しています…")

    def _on_media_signal_percent(self, percent: int):
        self.log_widget.set_progress_bar(percent, 100)
        self.log_widget.set_detail(f"音声・フェード解析中: {percent}%")

    def _on_media_signal_complete(self, result):
        """解析結果をタイムラインを変えず、確認理由と境界候補へ反映する。"""
        sender = self.sender()
        if (
            isinstance(sender, MediaSignalWorker)
            and sender is not self.media_signal_worker
        ):
            return
        if not self.current_job:
            return

        before = JobEditSnapshot.capture(self.current_job)
        apply_media_signal_result(self.current_job, result)
        if JobEditSnapshot.capture(self.current_job) != before:
            self._append_edit_snapshot(before)

        self.timeline_widget.set_boundary_candidates(
            self.current_job.suggested_boundaries
        )
        self._sync_filmstrip_candidates()
        self.clip_list_widget.refresh_clips()
        self.queue_widget.refresh()
        self.log_widget.append_log(
            "音声・フェード解析: "
            f"長い無音 {len(result.silence_ranges)}件、"
            f"フェード {len(result.fade_times)}件、"
            f"境界候補 {len(result.candidate_times)}件"
        )
        self._schedule_autosave()

    def _on_media_signal_error(self, message: str):
        self.log_widget.append_log(f"[ERROR] {message}")

    def _on_media_signal_finished(self):
        if self.sender() is not self.media_signal_worker:
            return
        self.log_widget.hide_progress()
        if self.media_signal_thread:
            self.media_signal_thread.quit()
            self.media_signal_thread.wait()
        self.media_signal_thread = None
        self.media_signal_worker = None
        self.clip_list_widget.set_media_signal_analyzing(False)
        if self.current_job:
            self.log_widget.set_status(f"編集中: {self.current_job.filename}")

    def _on_boundary_candidates_applied(self, candidates: List[float]):
        if not self.current_job:
            return
        self.current_job.suggested_boundaries = []
        self._sync_filmstrip_candidates()
        self.log_widget.append_log(
            f"音声・フェードの境界候補 {len(candidates)}件を追加しました"
        )
        self._schedule_autosave()

    def _begin_deferred_thumbnails(self):
        """自動後処理中はサムネイル生成を止め、最後に1回だけ再生成する"""
        self._defer_thumbnail_regen = True
        self._thumbnail_regen_pending = False
        self._stop_thumbnail_worker()

    def _finish_deferred_thumbnails(self):
        """保留していたサムネイル再生成を必要なら実行する"""
        should_regenerate = self._thumbnail_regen_pending
        self._defer_thumbnail_regen = False
        self._thumbnail_regen_pending = False
        if should_regenerate:
            self._regenerate_thumbnails()

    def _regenerate_thumbnails(self):
        """バックグラウンドでサムネイルを再生成（生成済みシーンはスキップ）"""
        if not self.current_job:
            return
        if self._defer_thumbnail_regen:
            self._thumbnail_regen_pending = True
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
        self.filmstrip_review_widget.update_thumbnail(scene_index, path)

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

    def _on_blank_preview_requested(self, start_time: float, end_time: float):
        """単色候補だけを再生し、候補終端で停止する。"""
        self.preview_widget.play_range(start_time, end_time)

    def _on_blank_trim_confirmed(self, segments: list):
        """一覧で確認した単色候補をトリミング対象へ反映する。"""
        self.preview_widget.pause()
        self._apply_blank_segments(segments)

    def _on_blank_trim_cancelled(self):
        """一覧の単色候補をすべて残す。"""
        self.preview_widget.pause()
        self.log_widget.append_log("単色候補はトリミングせず残しました")

    def _on_merge_scenes_requested(self, scene_indexes: List[int]):
        """選択された連続シーンを1つに結合"""
        if not self.current_job or len(scene_indexes) < 2:
            return

        boundaries = self.timeline_widget.get_boundaries()
        # シーン#i（1始まり）の開始境界は boundaries[i-1]。
        # 先頭以外の選択シーンの開始境界を取り除くと1つに結合される
        remove_positions = {i - 1 for i in scene_indexes[1:]}
        new_boundaries = [
            b for pos, b in enumerate(boundaries) if pos not in remove_positions
        ]

        # replace_boundaries が boundaries_changed を発火し、
        # シーン再構築・Undo履歴・サムネイル再利用まで既存フローに乗る
        self.timeline_widget.replace_boundaries(new_boundaries)
        self.log_widget.append_log(
            f"シーン #{scene_indexes[0]}〜#{scene_indexes[-1]} を結合しました"
        )

    def _on_auto_detect_requested(self):
        """シーン境界の自動検出を開始"""
        if not self.current_job or not self.current_job.scenes:
            return

        if self.blank_detection_thread and self.blank_detection_thread.isRunning():
            QMessageBox.warning(self, "警告", "単色区間を検出中です")
            return

        if self.scene_detection_thread and self.scene_detection_thread.isRunning():
            QMessageBox.warning(self, "警告", "シーン検出中です")
            return

        duration = self.current_job.scenes[-1].end_time
        self._scene_detection_result_received = False
        self.log_widget.append_log("シーン検出を準備中...")
        self.log_widget.set_status("シーン検出中")
        self.timeline_widget.set_detecting(True)

        self.scene_detection_thread = QThread()
        self.scene_detection_worker = SceneDetectionWorker(
            self.current_job,
            duration,
            settings=self.timeline_widget.get_detection_settings(),
        )
        self.scene_detection_worker.moveToThread(self.scene_detection_thread)

        self.scene_detection_thread.started.connect(self.scene_detection_worker.run)
        self.scene_detection_worker.progress.connect(self._on_progress)
        self.scene_detection_worker.progress_percent.connect(self._on_detection_percent)
        self.scene_detection_worker.detection_complete.connect(self._on_scene_detection_complete)
        self.scene_detection_worker.error.connect(self._on_scene_detection_error)
        self.scene_detection_worker.finished.connect(self._on_scene_detection_finished)

        self.scene_detection_thread.start()

    def _on_auto_detect_cancel(self):
        """シーン自動検出の中止リクエスト"""
        if self.scene_detection_worker:
            self.scene_detection_worker.cancel()
            self.log_widget.append_log("シーン検出を中止しています...")

    def _on_detection_percent(self, percent: int):
        """シーン自動検出の進捗表示"""
        self.log_widget.set_progress_bar(percent, 100)
        self.log_widget.set_detail(f"シーン検出中: {percent}%")

    def _on_scene_detection_complete(self, detected_boundaries: list):
        """検出結果を確定せず、タイムライン上の候補として表示する。"""
        self._scene_detection_result_received = True
        if not self.current_job or not self.current_job.scenes:
            self._finish_scene_detection()
            return

        self.timeline_widget.set_detection_preview(detected_boundaries)
        self._sync_filmstrip_candidates()
        added_count = len(self.timeline_widget.detection_preview_times)

        if added_count > 0:
            self.log_widget.append_log(
                f"シーン検出: {added_count}個の分割候補をプレビュー中"
            )
        else:
            self.log_widget.append_log("シーン検出: 新しい分割候補はありませんでした")

        self.log_widget.set_status(f"編集中: {self.current_job.filename}")
        self._finish_scene_detection()

    def _on_scene_detection_preview_applied(self, candidates: list):
        """確認済みのシーン検出候補を反映した後の処理。"""
        if not self.current_job:
            return
        self.log_widget.append_log(
            f"シーン検出: 確認した分割候補 {len(candidates)}個を反映しました"
        )
        self.log_widget.append_log(
            "単色区間は「単色区間をトリミング」、"
            "結合などは「補正ツール」から確認できます"
        )
        self._start_date_detection(auto=True)

    def _on_blank_detect_requested(self):
        """タイムラインから単色区間の検出とトリミングを開始する。"""
        self._start_blank_detection()

    def _on_blank_detect_cancel(self):
        """単色区間検出の中止リクエスト。"""
        if self.blank_detection_worker:
            self.blank_detection_worker.cancel()
            self.log_widget.append_log("単色区間の検出を中止しています...")

    def _start_blank_detection(self):
        """単色区間を検出し、確認後に書き出し対象から除外する。"""
        if not self.current_job or not self.current_job.scenes:
            return False

        if self.scene_detection_thread and self.scene_detection_thread.isRunning():
            QMessageBox.warning(self, "警告", "シーン検出中です")
            return False

        if self.blank_detection_thread and self.blank_detection_thread.isRunning():
            QMessageBox.warning(self, "警告", "単色区間を検出中です")
            return False

        self._pending_blank_segments = None
        self.clip_list_widget.clear_blank_candidates()
        self.log_widget.append_log("トリミング対象の単色区間を検出中...")
        self.log_widget.set_status("単色区間を検出中")
        self.clip_list_widget.set_blank_detecting(True)
        self.timeline_widget.set_blank_trimming(True)

        self.blank_detection_thread = QThread()
        self.blank_detection_worker = BlankDetectionWorker(self.current_job)
        self.blank_detection_worker.moveToThread(self.blank_detection_thread)

        self.blank_detection_thread.started.connect(self.blank_detection_worker.run)
        self.blank_detection_worker.progress.connect(self._on_progress)
        self.blank_detection_worker.progress_percent.connect(self._on_blank_detect_percent)
        self.blank_detection_worker.detection_complete.connect(self._on_blank_detect_complete)
        self.blank_detection_worker.error.connect(self._on_blank_detect_error)
        self.blank_detection_worker.finished.connect(self._on_blank_detect_finished)

        self.blank_detection_thread.start()
        return True

    def _on_blank_detect_percent(self, percent: int):
        self.log_widget.set_progress_bar(percent, 100)
        self.log_widget.set_detail(f"単色区間を検出中: {percent}%")

    def _on_blank_detect_complete(self, segments: list):
        """単色区間の検出結果を受け取る（保持のみ）。

        ワーカースレッドを片付けてから確認画面を出せるよう、ここでは保持する。
        """
        self._pending_blank_segments = segments
        if segments:
            self.log_widget.append_log(
                f"単色区間を {len(segments)} 件検出しました。右の一覧で確認できます"
            )
        else:
            self.log_widget.append_log("トリミング対象の単色区間は見つかりませんでした")

    def _apply_blank_segments(self, segments: list):
        """確認後、単色区間を切り出して書き出し対象から除外する。"""
        if not self.current_job or not self.current_job.scenes or not segments:
            return

        duration = self.current_job.scenes[-1].end_time
        segs = [
            (max(0.0, s), min(duration, e), label)
            for s, e, label in segments
            if min(duration, e) - max(0.0, s) > 0.05
        ]
        if not segs:
            return

        # 境界追加と除外指定を1回のUndoで戻せるよう、操作全体の前を保存する。
        self._push_edit_snapshot()

        # 単色区間の端に境界を追加して、区間だけを独立したシーンに切り出す
        boundaries = set(self.timeline_widget.get_boundaries())
        for s, e, _label in segs:
            for edge in (s, e):
                edge = round(edge, 3)
                if 0.0 < edge < duration:
                    boundaries.add(edge)
        self.timeline_widget.replace_boundaries(sorted(boundaries))

        # 単色区間内に入るシーンを除外（keepオフ）
        dropped = 0
        for scene in self.current_job.scenes:
            mid = (scene.start_time + scene.end_time) / 2
            if any(s - 1e-3 <= mid <= e + 1e-3 for s, e, _ in segs):
                if scene.keep:
                    scene.keep = False
                    dropped += 1

        self.clip_list_widget.refresh_clips()
        self.log_widget.append_log(
            f"単色区間 {dropped} 件をトリミング対象にしました"
        )
        self._on_job_edited()

    def _on_blank_detect_error(self, message: str):
        self.log_widget.append_log(f"[ERROR] {message}")

    def _on_blank_detect_finished(self):
        """スレッドを片付けてから、単色区間のトリミングを確認する。"""
        if self.sender() is not self.blank_detection_worker:
            return
        self.log_widget.hide_progress()
        if self.blank_detection_thread:
            self.blank_detection_thread.quit()
            self.blank_detection_thread.wait()
            self.blank_detection_thread = None
            self.blank_detection_worker = None
        self.clip_list_widget.set_blank_detecting(False)
        self.timeline_widget.set_blank_trimming(False)
        if self.current_job:
            self.log_widget.set_status(f"編集中: {self.current_job.filename}")

        segments = self._pending_blank_segments
        self._pending_blank_segments = None

        # モードレスな一覧へ候補を出し、再生確認後にユーザーが確定する。
        if segments:
            self.clip_list_widget.show_blank_candidates(segments)

    def _protected_boundaries_from_clip_state(self) -> List[float]:
        """公開可否や出力設定が変わる境界を自動結合から保護する。"""
        if not self.current_job or not self.current_job.scenes:
            return []
        scenes = self.current_job.scenes
        duration = scenes[-1].end_time
        protected = set()
        previous_key = None
        for scene in scenes:
            event_name, event_date = self.current_job.get_scene_metadata(scene.index)
            state_key = (
                scene.keep,
                scene.is_sensitive,
                event_name,
                event_date,
                scene.filename_override,
            )
            if previous_key is not None and state_key != previous_key:
                protected.add(scene.start_time)
            previous_key = state_key

            if not scene.keep:
                protected.add(scene.start_time)
                if scene.end_time < duration:
                    protected.add(scene.end_time)
        return sorted(protected)

    def _propose_short_scene_merge(self):
        """補正ツールから、短いシーンが残っていれば結合を提案する。"""
        if not self.current_job or not self.current_job.scenes:
            return

        duration = self.current_job.scenes[-1].end_time
        boundaries = self.timeline_widget.get_boundaries()
        protected = self._protected_boundaries_from_clip_state()

        # 検出設定の最小シーン長より少し広めの初期値で提案する
        initial = max(3.0, self.timeline_widget.min_scene_spin.value())
        if len(absorb_short_scenes(boundaries, duration, initial, protected)) >= len(boundaries):
            QMessageBox.information(
                self, "短いシーンの結合",
                "この長さで結合できる短いシーンはありませんでした。\n"
                "（設定の最小シーン長を上げてから、もう一度確認できます）"
            )
            return

        dialog = MergeProposalDialog(
            boundaries, duration, initial, self, protected_times=protected
        )
        if dialog.exec() == MergeProposalDialog.Accepted:
            merged_count = dialog.merge_count()
            self.timeline_widget.replace_boundaries(dialog.merged_boundaries())
            self.log_widget.append_log(
                f"短いシーン {merged_count} 個を隣のシーンに統合しました"
            )

    def _on_short_merge_requested(self):
        """クリップ一覧から手動で結合提案を出す"""
        if not self.current_job or not self.current_job.scenes:
            QMessageBox.information(self, "短いシーンの結合", "先に動画を開いてください。")
            return
        self._propose_short_scene_merge()

    def _on_scene_detection_error(self, message: str):
        """シーン自動検出エラー"""
        self._scene_detection_result_received = True
        self.log_widget.append_log(f"[ERROR] {message}")
        self.log_widget.set_status("シーン検出エラー")
        self.timeline_widget.set_detection_status(
            f"シーン検出に失敗しました: {message}"
        )
        QMessageBox.warning(self, "シーン検出エラー", message)
        self._finish_scene_detection()

    def _on_scene_detection_finished(self):
        """シーン自動検出の終了処理（キャンセル時もここで後始末する）"""
        # complete/errorハンドラが先に後始末を済ませた場合は何もしない
        if self.sender() is not self.scene_detection_worker:
            return
        if not self._scene_detection_result_received:
            self.timeline_widget.set_detection_status(
                "シーン検出を中止しました。設定を変えて再実行できます"
            )
        if self.current_job:
            self.log_widget.set_status(f"編集中: {self.current_job.filename}")
        self._finish_scene_detection()

    def _finish_scene_detection(self):
        """シーン自動検出スレッドを片付ける"""
        self.log_widget.hide_progress()
        if self.scene_detection_thread:
            self.scene_detection_thread.quit()
            self.scene_detection_thread.wait()
            self.scene_detection_thread = None
            self.scene_detection_worker = None
        self.timeline_widget.set_detecting(False)
        self.timeline_widget.set_auto_detect_enabled(self.current_job is not None)

    def _on_date_detect_requested(self):
        """焼き込み日付の検出を開始（手動）"""
        self._start_date_detection(auto=False)

    def _start_date_detection(self, auto: bool):
        """焼き込み日付の検出を開始

        auto=True の場合は自動実行（完了・エラーをログのみで通知し、
        ダイアログは出さない）
        """
        if not self.current_job or not self.current_job.scenes:
            return False

        if self.date_detection_thread and self.date_detection_thread.isRunning():
            if not auto:
                QMessageBox.warning(self, "警告", "日付検出中です")
            return False

        self._date_detect_auto = auto
        self.log_widget.append_log("焼き込み日付の検出を開始します...")
        self.log_widget.set_status("日付検出中")
        self.clip_list_widget.set_date_detecting(True)

        self.date_detection_thread = QThread()
        self.date_detection_worker = DateDetectionWorker(self.current_job)
        self.date_detection_worker.moveToThread(self.date_detection_thread)

        self.date_detection_thread.started.connect(self.date_detection_worker.run)
        self.date_detection_worker.progress.connect(self._on_progress)
        self.date_detection_worker.progress_percent.connect(self._on_date_detect_percent)
        self.date_detection_worker.detection_complete.connect(self._on_date_detect_complete)
        self.date_detection_worker.error.connect(self._on_date_detect_error)
        self.date_detection_worker.finished.connect(self._on_date_detect_finished)

        self.date_detection_thread.start()
        return True

    def _on_date_detect_cancel(self):
        """日付検出の中止リクエスト"""
        if self.date_detection_worker:
            self.date_detection_worker.cancel()
            self.log_widget.append_log("日付検出を中止しています...")

    def _on_date_detect_percent(self, percent: int):
        self.log_widget.set_progress_bar(percent, 100)
        self.log_widget.set_detail(f"日付検出中: {percent}%")

    def _on_date_detect_complete(self, results: dict):
        """日付検出完了。完全な日付→年月(日補完)→前後推定の順で各シーンに設定する"""
        if not self.current_job:
            return

        from datetime import date
        from app.core.date_detector import infer_missing_dates

        full = results.get("full", {})
        year_months = results.get("ym", {})
        scenes = self.current_job.scenes
        before = JobEditSnapshot.capture(self.current_job)
        for scene in scenes:
            clear_date_review_acknowledgements(scene)

        # 1) 完全な日付を設定
        applied = 0
        for scene in scenes:
            if scene.index in full:
                scene.event_date = full[scene.index]
                scene.date_source = "detected"
                applied += 1

        # 2) 年月だけ読めたシーンは日を補完（同年月の検出済みシーンの日があれば
        #    それを、無ければ1日）。月が読めている分、前後推定より確度が高い。
        day_by_ym: dict[tuple[int, int], int] = {}
        for d in full.values():
            day_by_ym.setdefault((d.year, d.month), d.day)
        ym_applied = 0
        for scene in scenes:
            if scene.index in full or scene.index not in year_months:
                continue
            y, m = year_months[scene.index]
            scene.event_date = date(y, m, day_by_ym.get((y, m), 1))
            scene.date_source = "inferred"
            ym_applied += 1

        # 3) まだ日付が無いシーンを前後のシーンから補完
        anchors = {s.index: s.event_date for s in scenes if s.event_date is not None}
        scene_indices = [s.index for s in scenes]
        inferred = infer_missing_dates(scene_indices, anchors) if anchors else {}
        for scene in scenes:
            if scene.event_date is None and scene.index in inferred:
                scene.event_date = inferred[scene.index]
                scene.date_source = "inferred"

        total = len(scenes)
        set_count = sum(1 for s in scenes if s.event_date is not None)
        approx = ym_applied + len(inferred)
        changed = JobEditSnapshot.capture(self.current_job) != before
        if changed:
            self._append_edit_snapshot(before)
            self.clip_list_widget.refresh_clips()
            self._on_job_edited()

        if set_count > 0:
            msg = (
                f"日付検出: {applied}/{total} シーンを検出"
                + (f"、{approx} シーンを月/前後から推定" if approx else "")
                + "。確認事項から映像と照合してください"
            )
            self.log_widget.append_log(msg)
        else:
            self.log_widget.append_log("日付検出: 日付スタンプは見つかりませんでした")

    def _on_date_detect_error(self, message: str):
        self.log_widget.append_log(f"[ERROR] {message}")
        if not self._date_detect_auto:
            QMessageBox.warning(self, "日付検出エラー", message)

    def _on_date_detect_finished(self):
        """日付検出スレッドを片付ける"""
        if self.sender() is not self.date_detection_worker:
            return
        self.log_widget.hide_progress()
        if self.current_job:
            self.log_widget.set_status(f"編集中: {self.current_job.filename}")
        if self.date_detection_thread:
            self.date_detection_thread.quit()
            self.date_detection_thread.wait()
            self.date_detection_thread = None
            self.date_detection_worker = None
        self.clip_list_widget.set_date_detecting(False)
        if self._date_detect_auto:
            self._finish_deferred_thumbnails()

    def _update_timeline(self, job: VideoJob):
        """タイムラインを更新"""
        if not job.scenes:
            return
        scene_start_times = [scene.start_time for scene in job.scenes]
        duration = job.scenes[-1].end_time
        self.timeline_widget.set_scenes(scene_start_times, duration)
        self.timeline_widget.set_boundary_candidates(job.suggested_boundaries)
        self.filmstrip_review_widget.set_job(job)
        self._sync_filmstrip_candidates()

    def _on_export_requested(self, job: VideoJob, output_dir: Path, export_preset: str):
        """書き出しリクエスト"""
        if self.export_thread and self.export_thread.isRunning():
            QMessageBox.warning(self, "警告", "書き出し中です")
            return

        self.log_widget.clear_log()
        self.log_widget.set_status(f"書き出し中: {job.filename}")
        self.log_widget.hide_progress()
        self.clip_list_widget.set_exporting(True)
        self._schedule_autosave()

        # ワーカーとスレッドを作成
        self.export_thread = QThread()
        self.export_worker = ExportWorker(
            job, output_dir, export_preset=export_preset
        )
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

    def _on_export_cancel_requested(self):
        if self.export_worker is None:
            return
        self.export_worker.cancel()
        self.clip_list_widget.set_export_cancelling()
        self.log_widget.set_status("書き出しを中止しています")
        self.log_widget.append_log("書き出しを中止しています...")

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
        self.clip_list_widget.set_exporting(False)

        self.queue_widget.refresh()
        self._schedule_autosave()

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
        self.clip_list_widget.set_exporting(False)

        self.queue_widget.refresh()
        self._schedule_autosave()

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
            QPushButton:focus {
                border: 2px solid #4f9ddf;
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
            QPushButton#btn_export,
            QPushButton[recommended="true"] {
                background-color: #2d4a7a;
                border-color: #4a7abc;
                font-weight: bold;
            }
            QPushButton#btn_export:hover,
            QPushButton[recommended="true"]:hover {
                background-color: #3a5a8a;
            }
            QPushButton#btn_split:disabled,
            QPushButton#btn_export:disabled,
            QPushButton[recommended="true"]:disabled {
                background-color: #2a2a2a;
                color: #666;
                border-color: #444;
                font-weight: normal;
            }
            QFrame#filmstripHeader,
            QFrame#filmstripLegend {
                background-color: #24272b;
                border: 1px solid #3b4047;
                border-radius: 5px;
            }
            QLabel#filmstripTitle {
                color: #ffffff;
                font-size: 15px;
                font-weight: bold;
            }
            QLabel#filmstripSummary,
            QLabel#filmstripHint {
                color: #aeb4bc;
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
            QLineEdit:disabled,
            QComboBox:disabled,
            QDoubleSpinBox:disabled,
            QSpinBox:disabled,
            QDateEdit:disabled {
                background-color: #2a2a2a;
                color: #666;
                border-color: #444;
            }
            QComboBox {
                background-color: #333;
                color: #d4d4d4;
                border: 1px solid #555;
                border-radius: 2px;
                padding: 3px 6px;
            }
            QComboBox:focus, QDateEdit:focus {
                border: 2px solid #4f9ddf;
            }
            QDoubleSpinBox, QSpinBox {
                background-color: #333;
                color: #d4d4d4;
                border: 1px solid #555;
                border-radius: 2px;
                padding: 2px 4px;
            }
            QDoubleSpinBox:focus, QSpinBox:focus {
                border-color: #007acc;
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
            QCheckBox:disabled {
                color: #666;
            }
            QCheckBox:focus {
                color: #ffffff;
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
        self._media_shortcuts = []

        # Space: 再生/一時停止
        s = QShortcut(QKeySequence(Qt.Key_Space), self)
        s.activated.connect(self._shortcut_play_pause)
        self._media_shortcuts.append(s)

        # S: ここで分割
        s = QShortcut(QKeySequence(Qt.Key_S), self)
        s.activated.connect(self._shortcut_split)
        self._media_shortcuts.append(s)

        # 左矢印: コマ戻し
        s = QShortcut(QKeySequence(Qt.Key_Left), self)
        s.activated.connect(self.preview_widget.step_back)
        self._media_shortcuts.append(s)

        # 右矢印: コマ送り
        s = QShortcut(QKeySequence(Qt.Key_Right), self)
        s.activated.connect(self.preview_widget.step_forward)
        self._media_shortcuts.append(s)

        # OS標準のUndo/Redo（macOSではCommand、Windows/LinuxではCtrl）
        s = QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self)
        s.activated.connect(self._shortcut_undo)

        s = QShortcut(QKeySequence(QKeySequence.StandardKey.Redo), self)
        s.activated.connect(self._shortcut_redo)

        QApplication.instance().focusChanged.connect(self._on_focus_changed)
        self._on_focus_changed(None, QApplication.focusWidget())

    @staticmethod
    def _focus_uses_standard_keys(widget: QWidget) -> bool:
        """Space・左右キーなどの標準操作を持つコントロールか判定する"""
        return isinstance(
            widget,
            (
                QAbstractButton,
                QAbstractItemView,
                QAbstractSlider,
                QAbstractSpinBox,
                QComboBox,
                QLineEdit,
                QTextEdit,
            ),
        )

    def _on_focus_changed(self, _old: QWidget, current: QWidget):
        """フォーム操作中はメディア用ショートカットにキーを奪わせない"""
        enabled = not self._focus_uses_standard_keys(current)
        for shortcut in self._media_shortcuts:
            shortcut.setEnabled(enabled)

    def _shortcut_play_pause(self):
        """Space: 再生/一時停止（テキスト入力中は無視）"""
        if self.preview_widget.current_video_path:
            self.preview_widget.toggle_play()

    def _shortcut_split(self):
        """S: 分割（テキスト入力中は無視）"""
        self.preview_widget.request_split()

    def _shortcut_undo(self):
        """Ctrl+Z: 直前の編集を取り消す。"""
        if not self._undo_stack or self.current_job is None:
            return
        self._redo_stack.append(JobEditSnapshot.capture(self.current_job))
        prev = self._undo_stack.pop()
        self._restore_edit_snapshot(prev)

    def _shortcut_redo(self):
        """Ctrl+Shift+Z / Ctrl+Y: 取り消した編集をやり直す。"""
        if not self._redo_stack or self.current_job is None:
            return
        self._undo_stack.append(JobEditSnapshot.capture(self.current_job))
        next_snapshot = self._redo_stack.pop()
        self._restore_edit_snapshot(next_snapshot)

    def _on_player_error(self, message: str):
        """プレイヤーエラーをログに表示"""
        self.log_widget.append_log(f"[ERROR] {message}")
        self.log_widget.set_status("再生エラー")

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

        if self.date_detection_thread and self.date_detection_thread.isRunning():
            if self.date_detection_worker:
                self.date_detection_worker.cancel()
            self.date_detection_thread.quit()
            self.date_detection_thread.wait()

        if self.blank_detection_thread and self.blank_detection_thread.isRunning():
            if self.blank_detection_worker:
                self.blank_detection_worker.cancel()
            self.blank_detection_thread.quit()
            self.blank_detection_thread.wait()

        if self.batch_detection_thread and self.batch_detection_thread.isRunning():
            if self.batch_detection_worker:
                self.batch_detection_worker.cancel()
            self.batch_detection_thread.quit()
            self.batch_detection_thread.wait()
        if self.batch_progress_dialog:
            self.batch_progress_dialog.set_finished("一括シーン検出を終了しました")
            self.batch_progress_dialog.close()
            self.batch_progress_dialog = None

        if self.thumbnail_thread and self.thumbnail_thread.isRunning():
            if self.thumbnail_worker:
                self.thumbnail_worker.cancel()
            self.thumbnail_thread.quit()
            self.thumbnail_thread.wait()

        self._stop_boundary_preview_worker()
        self._stop_media_signal_worker()

        self._autosave_timer.stop()
        self._flush_autosave()
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
