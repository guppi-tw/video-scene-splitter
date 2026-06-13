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
from app.ui.merge_dialog import MergeProposalDialog
from app.ui.blank_dialog import BlankCutDialog
from app.ui.preview_widget import PreviewWidget
from app.ui.timeline_widget import TimelineWidget
from app.ui.workers import (
    ThumbnailWorker, ExportWorker, SceneDetectionWorker,
    DateDetectionWorker, BlankDetectionWorker, BatchSceneDetectionWorker,
)
from app.core.scene_detector import absorb_short_scenes, merge_boundaries


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
        self.date_detection_thread: QThread = None
        self.date_detection_worker: DateDetectionWorker = None
        self._date_detect_auto = False
        self.blank_detection_thread: QThread = None
        self.blank_detection_worker: BlankDetectionWorker = None
        self._propose_merge_after_blank = False
        self._blank_protected_times: List[float] = []
        self.batch_detection_thread: QThread = None
        self.batch_detection_worker: BatchSceneDetectionWorker = None

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
        self.queue_widget.detect_all_requested.connect(self._on_detect_all_requested)
        self.queue_widget.clip_preview_requested.connect(self._on_queue_clip_preview)

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
        self.timeline_widget.auto_detect_cancel_requested.connect(self._on_auto_detect_cancel)

        # クリップリスト → プレビュー
        self.clip_list_widget.clip_preview_requested.connect(self._on_clip_preview)

        # クリップリスト → 書き出し
        self.clip_list_widget.export_requested.connect(self._on_export_requested)

        # クリップリスト → シーン結合
        self.clip_list_widget.merge_requested.connect(self._on_merge_scenes_requested)
        self.clip_list_widget.short_merge_requested.connect(self._on_short_merge_requested)

        # クリップリスト → 日付検出
        self.clip_list_widget.date_detect_requested.connect(self._on_date_detect_requested)
        self.clip_list_widget.date_detect_cancel_requested.connect(self._on_date_detect_cancel)

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

    def _on_queue_clip_preview(self, job: VideoJob, start_time: float):
        """キューのツリーでクリップを選んだとき、その動画を開いて頭出しする"""
        if self.current_job is not job:
            self._on_open_video(job)
        self.preview_widget.seek_to(start_time)

    def _on_detect_all_requested(self):
        """待機中の全動画にシーン検出を一括実行"""
        if self.batch_detection_thread and self.batch_detection_thread.isRunning():
            QMessageBox.warning(self, "警告", "一括検出を実行中です")
            return

        jobs = [j for j in self.job_queue.get_all_jobs() if j.status == JobStatus.WAITING]
        if not jobs:
            QMessageBox.information(
                self, "一括検出",
                "検出対象（待機中）の動画がありません。\n"
                "既に開いた動画はそれぞれの画面で検出してください。"
            )
            return

        self.log_widget.clear_log()
        self.log_widget.set_status("一括シーン検出中")
        self.log_widget.append_log(f"{len(jobs)} 本の動画をシーン検出します...")
        self.queue_widget.set_detect_all_enabled(False)

        self.batch_detection_thread = QThread()
        self.batch_detection_worker = BatchSceneDetectionWorker(
            jobs, settings=self.timeline_widget.get_detection_settings()
        )
        self.batch_detection_worker.moveToThread(self.batch_detection_thread)

        self.batch_detection_thread.started.connect(self.batch_detection_worker.run)
        self.batch_detection_worker.progress.connect(self._on_progress)
        self.batch_detection_worker.progress_percent.connect(self._on_batch_detect_percent)
        self.batch_detection_worker.video_done.connect(self._on_batch_video_done)
        self.batch_detection_worker.error.connect(self._on_batch_detect_error)
        self.batch_detection_worker.finished.connect(self._on_batch_detect_finished)

        self.batch_detection_thread.start()

    def _on_batch_detect_percent(self, percent: int):
        self.log_widget.set_progress_bar(percent, 100)
        self.log_widget.set_detail(f"一括検出中: {percent}%")

    def _on_batch_video_done(self, job_id: int, scene_count: int):
        job = self.job_queue.get_job_by_id(job_id)
        name = job.filename if job else f"job {job_id}"
        self.log_widget.append_log(f"検出完了: {name} → {scene_count}本")
        self.queue_widget.refresh()

    def _on_batch_detect_error(self, message: str):
        self.log_widget.append_log(f"[ERROR] {message}")

    def _on_batch_detect_finished(self):
        if self.sender() is not self.batch_detection_worker:
            return
        self.log_widget.hide_progress()
        self.log_widget.set_status("一括検出完了")
        if self.batch_detection_thread:
            self.batch_detection_thread.quit()
            self.batch_detection_thread.wait()
            self.batch_detection_thread = None
            self.batch_detection_worker = None
        self.queue_widget.set_detect_all_enabled(True)
        self.queue_widget.refresh()

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

        # 一括検出済みなどで既にシーンがある場合はそれを保持し、
        # 無い場合のみ動画全体を1シーンとして初期化する
        if not job.scenes:
            job.scenes = [Scene(index=1, start_time=0.0, end_time=duration, keep=True)]
        job.status = JobStatus.REVIEW
        self.current_job = job

        boundaries = [s.start_time for s in job.scenes]
        self._undo_stack.clear()
        self._last_boundaries = list(boundaries)

        # UIを更新
        self.queue_widget.refresh()
        self.clip_list_widget.set_job(job)
        self.preview_widget.load_video(job.source_path)
        self.timeline_widget.set_scenes(boundaries, duration)

        # サムネイルはバックグラウンドで生成（UIをブロックしない）
        self._regenerate_thumbnails()

        self.log_widget.append_log("編集を開始しました")
        if len(job.scenes) > 1:
            self.log_widget.append_log(f"検出済みクリップ: {len(job.scenes)}本")
        else:
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

        if self.scene_detection_thread and self.scene_detection_thread.isRunning():
            QMessageBox.warning(self, "警告", "シーン自動検出中です")
            return

        duration = self.current_job.scenes[-1].end_time
        self.log_widget.append_log("シーン自動検出を準備中...")
        self.log_widget.set_status("シーン自動検出中")
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
            self.log_widget.append_log("シーン自動検出を中止しています...")

    def _on_detection_percent(self, percent: int):
        """シーン自動検出の進捗表示"""
        self.log_widget.set_progress_bar(percent, 100)
        self.log_widget.set_detail(f"シーン自動検出中: {percent}%")

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

        # 検出後の自動パイプライン:
        #   つなぎ目(単色)検出 → 統合提案 → 日付検出
        # つなぎ目検出が終わってから統合提案・日付検出へ連鎖する
        self._propose_merge_after_blank = added_count > 0
        self._start_blank_detection()

    def _start_blank_detection(self):
        """単色つなぎ目シーンの検出を開始（完了後に統合提案・日付検出へ連鎖）"""
        if not self.current_job or not self.current_job.scenes:
            return

        if self.blank_detection_thread and self.blank_detection_thread.isRunning():
            return

        self.log_widget.append_log("つなぎ目（単色）を検出中...")
        self.log_widget.set_status("つなぎ目検出中")

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

    def _on_blank_detect_percent(self, percent: int):
        self.log_widget.set_progress_bar(percent, 100)
        self.log_widget.set_detail(f"つなぎ目検出中: {percent}%")

    def _on_blank_detect_complete(self, segments: list):
        """つなぎ目検出完了。単色区間に境界を入れて除外を提案する。"""
        self._blank_protected_times = []
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

        dialog = BlankCutDialog(segs, self)
        if dialog.exec() != BlankCutDialog.Accepted:
            return

        # 単色区間の端に境界を追加して、区間だけを独立したシーンに切り出す
        boundaries = set(self.timeline_widget.get_boundaries())
        protected = []
        for s, e, _label in segs:
            for edge in (s, e):
                edge = round(edge, 3)
                if 0.0 < edge < duration:
                    boundaries.add(edge)
                    protected.append(edge)
        self.timeline_widget.replace_boundaries(sorted(boundaries))
        self._blank_protected_times = protected

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
            f"単色のつなぎ目 {dropped} 区間を書き出し対象から除外しました"
        )

    def _on_blank_detect_error(self, message: str):
        self.log_widget.append_log(f"[ERROR] {message}")

    def _on_blank_detect_finished(self):
        """つなぎ目検出スレッドを片付け、統合提案・日付検出へ連鎖する"""
        if self.sender() is not self.blank_detection_worker:
            return
        self.log_widget.hide_progress()
        if self.blank_detection_thread:
            self.blank_detection_thread.quit()
            self.blank_detection_thread.wait()
            self.blank_detection_thread = None
            self.blank_detection_worker = None
        if self.current_job:
            self.log_widget.set_status(f"編集中: {self.current_job.filename}")

        # つなぎ目処理が終わってから統合提案 → 日付検出
        if getattr(self, "_propose_merge_after_blank", False):
            self._propose_short_scene_merge()
        self._start_date_detection(auto=True)

    def _protected_boundaries_from_dropped(self) -> List[float]:
        """除外(keep=False)シーンの境界を保護対象として返す。

        統合提案がつなぎ目などの除外シーンを隣の採用クリップに飲み込まないよう、
        現在のシーン構成から動的に求める（自動・手動どちらの呼び出しでも正しい）。
        """
        if not self.current_job or not self.current_job.scenes:
            return []
        scenes = self.current_job.scenes
        duration = scenes[-1].end_time
        protected = []
        for scene in scenes:
            if not scene.keep:
                protected.append(scene.start_time)
                if scene.end_time < duration:
                    protected.append(scene.end_time)
        return protected

    def _propose_short_scene_merge(self, manual: bool = False):
        """短いシーンが残っていれば結合を提案する（manual=Trueで手動起動）"""
        if not self.current_job or not self.current_job.scenes:
            return

        duration = self.current_job.scenes[-1].end_time
        boundaries = self.timeline_widget.get_boundaries()
        protected = self._protected_boundaries_from_dropped()

        # 検出設定の最小シーン長より少し広めの初期値で提案する
        initial = max(3.0, self.timeline_widget.min_scene_spin.value())
        if len(absorb_short_scenes(boundaries, duration, initial, protected)) >= len(boundaries):
            if manual:
                QMessageBox.information(
                    self, "短いシーンの結合",
                    "この長さで結合できる短いシーンはありませんでした。\n"
                    "（提案ダイアログで秒数を上げても確認できます）"
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
        self._propose_short_scene_merge(manual=True)

    def _on_scene_detection_error(self, message: str):
        """シーン自動検出エラー"""
        self.log_widget.append_log(f"[ERROR] {message}")
        self.log_widget.set_status("シーン自動検出エラー")
        QMessageBox.warning(self, "シーン自動検出エラー", message)
        self._finish_scene_detection()

    def _on_scene_detection_finished(self):
        """シーン自動検出の終了処理（キャンセル時もここで後始末する）"""
        # complete/errorハンドラが先に後始末を済ませた場合は何もしない
        if self.sender() is not self.scene_detection_worker:
            return
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
            return

        if self.date_detection_thread and self.date_detection_thread.isRunning():
            if not auto:
                QMessageBox.warning(self, "警告", "日付検出中です")
            return

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

    def _on_date_detect_cancel(self):
        """日付検出の中止リクエスト"""
        if self.date_detection_worker:
            self.date_detection_worker.cancel()
            self.log_widget.append_log("日付検出を中止しています...")

    def _on_date_detect_percent(self, percent: int):
        self.log_widget.set_progress_bar(percent, 100)
        self.log_widget.set_detail(f"日付検出中: {percent}%")

    def _on_date_detect_complete(self, results: dict):
        """日付検出完了。検出した日付を各シーンに設定し、欠損は前後から補完する"""
        if not self.current_job:
            return

        from app.core.date_detector import infer_missing_dates

        applied = 0
        for scene in self.current_job.scenes:
            detected = results.get(scene.index)
            if detected is not None:
                scene.event_date = detected
                applied += 1

        # 検出できなかったシーンを前後のシーンの日付から補完する
        scene_indices = [s.index for s in self.current_job.scenes]
        inferred = infer_missing_dates(scene_indices, results) if applied > 0 else {}
        for scene in self.current_job.scenes:
            if scene.index in inferred:
                scene.event_date = inferred[scene.index]

        total = len(self.current_job.scenes)
        inferred_count = len(inferred)

        if applied > 0:
            self.clip_list_widget.refresh_clips()
            msg = f"日付検出: {applied}/{total} シーンで日付を検出して設定しました"
            if inferred_count > 0:
                nums = "、".join(f"#{i}" for i in sorted(inferred))
                msg += f"（さらに {inferred_count} シーンを前後から推定: {nums}）"
            self.log_widget.append_log(msg)
            if not self._date_detect_auto:
                extra = (
                    f"\n\n検出できなかった {inferred_count} シーンは前後のクリップから\n"
                    "日付を推定して設定しました（必要なら手動で修正できます）。"
                    if inferred_count > 0 else ""
                )
                QMessageBox.information(
                    self,
                    "日付検出完了",
                    f"{applied}/{total} シーンで焼き込み日付を検出し、\n"
                    f"クリップの日付に設定しました。{extra}\n\n"
                    f"ファイル名のプレビューで確認できます。",
                )
        else:
            self.log_widget.append_log("日付検出: 日付スタンプは見つかりませんでした")
            if not self._date_detect_auto:
                QMessageBox.information(
                    self,
                    "日付検出",
                    "焼き込み日付は見つかりませんでした。\n"
                    "日付表示が映像に映っているかご確認ください。",
                )

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
