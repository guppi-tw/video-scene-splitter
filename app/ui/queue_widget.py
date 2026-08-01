"""
キュー表示ウィジェット
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTreeWidget, QTreeWidgetItem, QHeaderView,
    QFileDialog, QAbstractItemView, QLabel, QMessageBox, QFrame,
    QComboBox, QMenu,
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QBrush, QColor

from app.core import AddBatchResult, JobQueue, VideoJob, JobStatus
from app.core.review import pending_review_count, pending_review_issues
from app.core.time_format import format_seconds


# ツリーアイテムのデータ役割
_ROLE_JOB_ID = Qt.UserRole          # トップレベル（動画）に持たせるjob_id
_ROLE_CLIP_TIME = Qt.UserRole + 1   # 子（クリップ）に持たせる開始秒


def job_status_badge(job: VideoJob) -> tuple[str, str, str]:
    """キューに表示する状態バッジ（テキスト、背景色、文字色）を返す"""
    scene_count = len(job.scenes)

    if job.status == JobStatus.ERROR:
        return ("エラー", "#7a2d2d", "#f4d4d4")
    if job.status == JobStatus.DONE:
        label = f"書き出し済み / {scene_count}本" if scene_count else "書き出し済み"
        return (label, "#2d5a2d", "#d8f0d8")
    if job.status == JobStatus.PROCESSING:
        return ("処理中", "#6a5523", "#f6e6b8")
    if job.needs_post_process:
        return (f"確認待ち / {scene_count}本", "#654a1f", "#ffe3a3")
    review_count = pending_review_count(job)
    if review_count:
        return (
            f"確認事項 {review_count} / {scene_count}本",
            "#654a1f",
            "#ffe3a3",
        )
    if scene_count:
        return (f"書き出し待ち / {scene_count}本", "#2d4a5a", "#d4e8f2")
    return ("未検出", "#3a3a3a", "#d4d4d4")


def next_open_action_text(job: VideoJob) -> str:
    """選択中ジョブを開いたときの次アクション説明を返す"""
    if job.status == JobStatus.ERROR:
        detail = f" / {job.error_message}" if job.error_message else ""
        return f"この動画はエラー状態です{detail}"
    if job.status == JobStatus.DONE:
        return "この動画は書き出し済みです。選択中の内容を確認できます。"
    if job.needs_post_process:
        return "開くと: 検出済みクリップを表示し、日付検出をバックグラウンドで行います"
    review_count = pending_review_count(job)
    if review_count:
        return f"開くと: {review_count}件の確認事項を順番に確認できます"
    if job.scenes:
        return "開くと: 検出済みクリップを確認・編集できます"
    return "開くと: 動画全体を1シーンとして読み込みます"


class QueueWidget(QWidget):
    """ジョブキュー表示・操作ウィジェット"""

    job_selected = Signal(object)     # VideoJob
    open_video = Signal(object)       # VideoJob - 編集開始
    remove_requested = Signal(int)    # job_id - 削除リクエスト（可否はMainWindowが判断）
    detect_all_requested = Signal()   # 全動画の一括シーン検出
    bulk_metadata_requested = Signal()
    clip_preview_requested = Signal(object, float)  # VideoJob, start_time
    queue_changed = Signal()

    def __init__(self, job_queue: JobQueue):
        super().__init__()
        self.job_queue = job_queue
        self._detect_all_available = True
        self.setAcceptDrops(True)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(5)

        # ヘッダー
        header = QLabel("キュー")
        header.setStyleSheet("font-weight: bold; font-size: 13px; padding: 2px 0;")
        layout.addWidget(header)

        # 操作バー
        action_bar = QFrame()
        action_bar.setObjectName("queueActionBar")
        action_bar.setStyleSheet(
            "QFrame#queueActionBar { background-color: #242424; "
            "border: 1px solid #3a3a3a; border-radius: 4px; }"
        )
        btn_layout = QVBoxLayout(action_bar)
        btn_layout.setContentsMargins(8, 5, 8, 5)
        btn_layout.setSpacing(4)

        self.btn_add = QPushButton("動画を追加")
        self.btn_add.setAccessibleName("動画を追加")
        add_menu = QMenu(self.btn_add)
        self.action_add_file = add_menu.addAction("ファイルを選択…")
        self.action_add_folder = add_menu.addAction("フォルダを選択…")
        self.action_add_file.triggered.connect(self._on_add_file)
        self.action_add_folder.triggered.connect(self._on_add_folder)
        self.btn_add.setMenu(add_menu)

        self.btn_detect_all = QPushButton("一括検出")
        self.btn_detect_all.setToolTip("待機中の全動画にシーン検出をまとめて実行します")
        self.btn_detect_all.clicked.connect(self.detect_all_requested.emit)

        self.btn_open = QPushButton("開く")
        self.btn_open.setToolTip("選択した動画を確認・編集します")
        self.btn_open.clicked.connect(self._open_selected)

        # 低頻度・破壊的な操作は常設せず、オーバーフローメニューへまとめる。
        self.btn_more = QPushButton("…")
        self.btn_more.setFixedWidth(38)
        self.btn_more.setStyleSheet(
            "QPushButton::menu-indicator { image: none; width: 0px; }"
        )
        self.btn_more.setAccessibleName("キューのその他の操作")
        self.btn_more.setToolTip("一括設定やキューからの削除")
        queue_menu = QMenu(self.btn_more)
        self.action_bulk_metadata = queue_menu.addAction("一括設定…")
        self.action_bulk_metadata.setToolTip(
            "選択した複数動画へ出力名と日付をまとめて設定します"
        )
        self.action_bulk_metadata.triggered.connect(
            self.bulk_metadata_requested.emit
        )
        queue_menu.addSeparator()
        self.action_remove = queue_menu.addAction("キューから削除")
        self.action_remove.triggered.connect(self._on_remove)
        self.btn_more.setMenu(queue_menu)

        primary_layout = QHBoxLayout()
        primary_layout.setSpacing(5)
        primary_layout.addWidget(self.btn_add, stretch=1)
        primary_layout.addWidget(self.btn_open)
        btn_layout.addLayout(primary_layout)

        secondary_layout = QHBoxLayout()
        secondary_layout.setSpacing(5)
        secondary_layout.addWidget(self.btn_detect_all, stretch=1)
        secondary_layout.addWidget(self.btn_more)
        btn_layout.addLayout(secondary_layout)

        layout.addWidget(action_bar)

        self.filter_combo = QComboBox()
        self.filter_combo.setAccessibleName("キューの表示を絞り込む")
        self.filter_combo.addItem("すべて", "all")
        self.filter_combo.addItem("未検出", "waiting")
        self.filter_combo.addItem("確認が必要", "review")
        self.filter_combo.addItem("書き出し待ち", "export")
        self.filter_combo.addItem("エラー", "error")
        self.filter_combo.addItem("書き出し済み", "done")
        self.filter_combo.currentIndexChanged.connect(lambda _index: self.refresh())
        layout.addWidget(self.filter_combo)

        # ツリー（動画 → 分割クリップ）
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["動画", "状態"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemActivated.connect(self._on_item_activated)
        layout.addWidget(self.tree)
        self._update_action_state()

    def set_detect_all_enabled(self, enabled: bool):
        """一括検出ボタンの有効状態を設定"""
        self._detect_all_available = enabled
        self._update_action_state()

    def _waiting_job_count(self) -> int:
        return sum(
            1 for job in self.job_queue.get_all_jobs()
            if job.status == JobStatus.WAITING
        )

    def _update_action_state(self):
        waiting_count = self._waiting_job_count()
        selected_job = self.get_selected_job()
        has_selection = selected_job is not None
        self.action_remove.setEnabled(has_selection)
        self.btn_open.setEnabled(has_selection)
        self.action_bulk_metadata.setEnabled(bool(self.job_queue.get_all_jobs()))
        if selected_job and selected_job.status == JobStatus.DONE:
            self.btn_open.setText("確認")
        elif selected_job and selected_job.status == JobStatus.WAITING:
            self.btn_open.setText("編集開始")
        else:
            self.btn_open.setText("開く")
        if not self._detect_all_available:
            self.btn_detect_all.setEnabled(True)
            self.btn_detect_all.setText("進捗を表示")
            self.btn_detect_all.setToolTip("実行中の一括検出の進捗画面を表示します")
        elif waiting_count:
            self.btn_detect_all.setEnabled(True)
            self.btn_detect_all.setText(f"一括検出 ({waiting_count})")
            self.btn_detect_all.setToolTip(
                f"待機中の動画 {waiting_count} 本をまとめてシーン検出します"
            )
        else:
            self.btn_detect_all.setEnabled(False)
            self.btn_detect_all.setText("一括検出")
            self.btn_detect_all.setToolTip("待機中の動画がありません")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_paths([Path(url.toLocalFile()) for url in event.mimeData().urls()])
        event.acceptProposedAction()

    def add_paths(self, selected_paths: list[Path]):
        """ファイルとフォルダをまとめてキューへ追加する。"""
        paths = []
        for path in selected_paths:
            if path.is_file() and path.suffix.lower() == '.mp4':
                paths.append(path)
            elif path.is_dir():
                paths.extend(self._collect_mp4_paths(path))
        result = self.job_queue.add_files(paths)
        self.refresh()
        self._show_add_result(result)
        if result.added:
            self.queue_changed.emit()

    def _on_add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "フォルダを選択")
        if folder:
            result = self.job_queue.add_folder(Path(folder))
            self.refresh()
            self._show_add_result(result)
            if result.added:
                self.queue_changed.emit()

    def _on_add_file(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "ファイルを選択", "", "MP4 Files (*.mp4)"
        )
        result = self.job_queue.add_files([Path(f) for f in files])
        self.refresh()
        self._show_add_result(result)
        if result.added:
            self.queue_changed.emit()

    def _collect_mp4_paths(self, folder: Path) -> list[Path]:
        return sorted(
            path for path in folder.rglob("*")
            if path.is_file() and path.suffix.lower() == ".mp4"
        )

    def _show_add_result(self, result: AddBatchResult):
        if result.requested_count == 0:
            return

        if result.was_limited:
            QMessageBox.warning(
                self,
                "読み込み上限",
                f"一度に追加できる動画は {result.limit} 本までです。\n"
                f"追加: {len(result.added)} 本\n"
                f"上限超過でスキップ: {result.skipped_limit} 本\n"
                f"重複または対象外: {result.skipped_duplicate_or_invalid} 本"
            )
        elif not result.added:
            QMessageBox.information(
                self,
                "追加なし",
                "追加できる新しい MP4 ファイルがありませんでした。"
            )

    def _selected_job_item(self) -> QTreeWidgetItem:
        """選択中のトップレベル（動画）アイテムを返す。子選択時は親を返す。"""
        item = self.tree.currentItem()
        if item is None:
            return None
        return item if item.parent() is None else item.parent()

    def _on_remove(self):
        item = self._selected_job_item()
        if item is not None:
            job_id = item.data(0, _ROLE_JOB_ID)
            # 編集中・書き出し中の後始末が必要なためMainWindow側で削除する
            self.remove_requested.emit(job_id)

    def _on_item_activated(self, _item: QTreeWidgetItem, _column: int):
        """ダブルクリックまたはEnterで選択動画を開く。"""
        self._open_selected()

    def _open_selected(self):
        job = self.get_selected_job()
        if job is None:
            return
        if job.status in (JobStatus.WAITING, JobStatus.REVIEW):
            self.open_video.emit(job)
        elif job.status == JobStatus.DONE:
            self.job_selected.emit(job)

    def _on_selection_changed(self):
        item = self.tree.currentItem()
        if item is None:
            self._update_action_state()
            return
        if item.parent() is None:
            job = self.job_queue.get_job_by_id(item.data(0, _ROLE_JOB_ID))
            if job:
                self.job_selected.emit(job)
        else:
            # クリップ選択: 親動画を選択扱いにし、その位置をプレビュー
            job = self.job_queue.get_job_by_id(item.parent().data(0, _ROLE_JOB_ID))
            start = item.data(0, _ROLE_CLIP_TIME)
            if job:
                self.job_selected.emit(job)
                if start is not None:
                    self.clip_preview_requested.emit(job, float(start))
        self._update_action_state()

    def _matches_filter(self, job: VideoJob) -> bool:
        selected_filter = self.filter_combo.currentData()
        if selected_filter == "all":
            return True
        if selected_filter == "waiting":
            return job.status == JobStatus.WAITING
        if selected_filter == "review":
            return (
                job.needs_post_process
                or pending_review_count(job) > 0
                or any(scene.is_sensitive for scene in job.scenes)
            )
        if selected_filter == "export":
            return (
                job.status == JobStatus.REVIEW
                and bool(job.scenes)
                and any(scene.keep for scene in job.scenes)
                and not job.needs_post_process
                and pending_review_count(job) == 0
            )
        if selected_filter == "error":
            return job.status == JobStatus.ERROR
        if selected_filter == "done":
            return job.status == JobStatus.DONE
        return True

    def refresh(self):
        """ツリーを更新（動画 → 分割クリップ）"""
        # 展開状態と選択中ジョブを保持
        expanded = {
            self.tree.topLevelItem(i).data(0, _ROLE_JOB_ID)
            for i in range(self.tree.topLevelItemCount())
            if self.tree.topLevelItem(i).isExpanded()
        }
        selected_item = self._selected_job_item()
        selected_id = selected_item.data(0, _ROLE_JOB_ID) if selected_item else None

        was_blocked = self.tree.blockSignals(True)
        try:
            self.tree.clear()

            for job in self.job_queue.get_all_jobs():
                if not self._matches_filter(job):
                    continue
                scene_count = len(job.scenes)
                status_text, bg_color, fg_color = job_status_badge(job)

                top = QTreeWidgetItem([job.filename, status_text])
                top.setData(0, _ROLE_JOB_ID, job.id)
                top.setToolTip(0, job.filename)
                top.setBackground(1, QBrush(QColor(bg_color)))
                top.setForeground(1, QBrush(QColor(fg_color)))
                top.setToolTip(1, next_open_action_text(job))
                self.tree.addTopLevelItem(top)

                # 分割クリップを子として追加
                for scene in job.scenes:
                    label = (
                        f"#{scene.index}  {format_seconds(scene.start_time)}"
                        f"–{format_seconds(scene.end_time)}"
                    )
                    issues = pending_review_issues(job, scene)
                    states = []
                    if not scene.keep:
                        states.append("除外")
                    if issues:
                        states.append(f"確認{len(issues)}")
                    state = "・".join(states)
                    child = QTreeWidgetItem([label, state])
                    child.setData(0, _ROLE_CLIP_TIME, scene.start_time)
                    if issues:
                        child.setToolTip(
                            1,
                            " / ".join(issue.label for issue in issues),
                        )
                    if not scene.keep:
                        child.setForeground(0, QBrush(QColor("#888")))
                    top.addChild(child)

                # 展開状態を復元（新規検出で子ができた動画は開く）
                if job.id in expanded or (scene_count > 0 and job.id not in expanded
                                          and job.id == selected_id):
                    top.setExpanded(True)

                if job.id == selected_id:
                    self.tree.setCurrentItem(top)
        finally:
            self.tree.blockSignals(was_blocked)

        self._update_action_state()

    def select_job(self, job_id: int):
        """指定IDのジョブを選択"""
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.data(0, _ROLE_JOB_ID) == job_id:
                self.tree.setCurrentItem(item)
                break

    def expand_job(self, job_id: int):
        """指定動画のクリップ一覧を展開"""
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.data(0, _ROLE_JOB_ID) == job_id:
                item.setExpanded(True)
                break

    def get_selected_job(self) -> VideoJob:
        """選択中のジョブを取得"""
        item = self._selected_job_item()
        if item is not None:
            return self.job_queue.get_job_by_id(item.data(0, _ROLE_JOB_ID))
        return None
