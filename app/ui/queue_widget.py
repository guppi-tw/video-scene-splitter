"""
キュー表示ウィジェット
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTreeWidget, QTreeWidgetItem, QHeaderView,
    QFileDialog, QAbstractItemView, QLabel, QMessageBox, QFrame
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QBrush, QColor

from app.core import AddBatchResult, JobQueue, VideoJob, JobStatus
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
        return (f"後処理待ち / {scene_count}本", "#654a1f", "#ffe3a3")
    if scene_count:
        return (f"確認中 / {scene_count}本", "#2d4a5a", "#d4e8f2")
    return ("未検出", "#3a3a3a", "#d4d4d4")


def next_open_action_text(job: VideoJob) -> str:
    """選択中ジョブを開いたときの次アクション説明を返す"""
    if job.status == JobStatus.ERROR:
        detail = f" / {job.error_message}" if job.error_message else ""
        return f"この動画はエラー状態です{detail}"
    if job.status == JobStatus.DONE:
        return "この動画は書き出し済みです。選択中の内容を確認できます。"
    if job.needs_post_process:
        return "開くと: つなぎ目検出 -> 結合提案 -> 日付検出"
    if job.scenes:
        return "開くと: 検出済みクリップを確認・編集できます"
    return "開くと: 動画全体を1シーンとして読み込みます"


class QueueWidget(QWidget):
    """ジョブキュー表示・操作ウィジェット"""

    job_selected = Signal(object)     # VideoJob
    open_video = Signal(object)       # VideoJob - 編集開始
    remove_requested = Signal(int)    # job_id - 削除リクエスト（可否はMainWindowが判断）
    detect_all_requested = Signal()   # 全動画の一括シーン検出
    clip_preview_requested = Signal(object, float)  # VideoJob, start_time

    def __init__(self, job_queue: JobQueue):
        super().__init__()
        self.job_queue = job_queue
        self._detect_all_available = True
        self.setAcceptDrops(True)
        self._setup_ui()

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("color: #9a9a9a; font-size: 10px; font-weight: bold;")
        return label

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

        self.btn_add_file = QPushButton("+ ファイル")
        self.btn_add_file.clicked.connect(self._on_add_file)

        self.btn_add_folder = QPushButton("+ フォルダ")
        self.btn_add_folder.clicked.connect(self._on_add_folder)

        self.btn_detect_all = QPushButton("全部検出")
        self.btn_detect_all.setToolTip("待機中の全動画にシーン検出をまとめて実行します")
        self.btn_detect_all.clicked.connect(self.detect_all_requested.emit)

        self.btn_remove = QPushButton("削除")
        self.btn_remove.clicked.connect(self._on_remove)

        add_layout = QHBoxLayout()
        add_layout.setSpacing(5)
        add_layout.addWidget(self._section_label("追加"))
        add_layout.addWidget(self.btn_add_file)
        add_layout.addWidget(self.btn_add_folder)
        add_layout.addStretch()
        btn_layout.addLayout(add_layout)

        process_layout = QHBoxLayout()
        process_layout.setSpacing(5)
        process_layout.addWidget(self._section_label("処理"))
        process_layout.addWidget(self.btn_detect_all)
        process_layout.addStretch()
        process_layout.addWidget(self.btn_remove)
        btn_layout.addLayout(process_layout)

        layout.addWidget(action_bar)

        # ツリー（動画 → 分割クリップ）
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["ファイル名 / クリップ", "状態"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.tree)

        # 選択中動画を開いたときの次アクション
        self.next_action_label = QLabel("動画を選択すると、次に起きることを表示します")
        self.next_action_label.setWordWrap(True)
        self.next_action_label.setStyleSheet(
            "background-color: #242424; color: #cfcfcf; "
            "border: 1px solid #3a3a3a; border-radius: 4px; "
            "padding: 6px; font-size: 11px;"
        )
        layout.addWidget(self.next_action_label)

        # D&Dヒント
        self.drop_hint = QLabel("D&Dでファイル追加 / ダブルクリックで編集開始")
        self.drop_hint.setAlignment(Qt.AlignCenter)
        self.drop_hint.setStyleSheet("color: #666; font-size: 10px; padding: 4px;")
        layout.addWidget(self.drop_hint)
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
        self.btn_remove.setEnabled(self._selected_job_item() is not None)
        self.btn_detect_all.setEnabled(self._detect_all_available and waiting_count > 0)
        self.btn_detect_all.setText(
            f"全部検出 ({waiting_count})" if waiting_count else "全部検出"
        )
        if not self._detect_all_available:
            self.btn_detect_all.setToolTip("一括検出を実行中です")
        elif waiting_count:
            self.btn_detect_all.setToolTip(
                f"待機中の動画 {waiting_count} 本をまとめてシーン検出します"
            )
        else:
            self.btn_detect_all.setToolTip("待機中の動画がありません")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file() and path.suffix.lower() == '.mp4':
                paths.append(path)
            elif path.is_dir():
                paths.extend(self._collect_mp4_paths(path))
        result = self.job_queue.add_files(paths)
        self.refresh()
        self._show_add_result(result)

    def _on_add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "フォルダを選択")
        if folder:
            result = self.job_queue.add_folder(Path(folder))
            self.refresh()
            self._show_add_result(result)

    def _on_add_file(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "ファイルを選択", "", "MP4 Files (*.mp4)"
        )
        result = self.job_queue.add_files([Path(f) for f in files])
        self.refresh()
        self._show_add_result(result)

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

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int):
        """ダブルクリックで編集開始（クリップなら親動画を開く）"""
        job_item = item if item.parent() is None else item.parent()
        job_id = job_item.data(0, _ROLE_JOB_ID)
        job = self.job_queue.get_job_by_id(job_id)
        if job and job.status in [JobStatus.WAITING, JobStatus.REVIEW]:
            self.open_video.emit(job)

    def _on_selection_changed(self):
        item = self.tree.currentItem()
        if item is None:
            self._update_next_action(None)
            self._update_action_state()
            return
        if item.parent() is None:
            job = self.job_queue.get_job_by_id(item.data(0, _ROLE_JOB_ID))
            if job:
                self._update_next_action(job)
                self.job_selected.emit(job)
        else:
            # クリップ選択: 親動画を選択扱いにし、その位置をプレビュー
            job = self.job_queue.get_job_by_id(item.parent().data(0, _ROLE_JOB_ID))
            start = item.data(0, _ROLE_CLIP_TIME)
            if job:
                self._update_next_action(job)
                self.job_selected.emit(job)
                if start is not None:
                    self.clip_preview_requested.emit(job, float(start))
        self._update_action_state()

    def _update_next_action(self, job: VideoJob):
        if job is None:
            self.next_action_label.setText("動画を選択すると、次に起きることを表示します")
            return
        self.next_action_label.setText(next_open_action_text(job))

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
                scene_count = len(job.scenes)
                status_text, bg_color, fg_color = job_status_badge(job)

                top = QTreeWidgetItem([job.filename, status_text])
                top.setData(0, _ROLE_JOB_ID, job.id)
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
                    state = "keep" if scene.keep else "除外"
                    child = QTreeWidgetItem([label, state])
                    child.setData(0, _ROLE_CLIP_TIME, scene.start_time)
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

        self._update_next_action(self.get_selected_job())
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
