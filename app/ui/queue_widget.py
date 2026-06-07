"""
キュー表示ウィジェット
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QAbstractItemView, QLabel, QMessageBox
)
from PySide6.QtCore import Signal, Qt

from app.core import AddBatchResult, JobQueue, VideoJob, JobStatus


class QueueWidget(QWidget):
    """ジョブキュー表示・操作ウィジェット"""

    job_selected = Signal(object)  # VideoJob
    open_video = Signal(object)    # VideoJob - 編集開始

    def __init__(self, job_queue: JobQueue):
        super().__init__()
        self.job_queue = job_queue
        self.setAcceptDrops(True)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(5)

        # ヘッダー
        header = QLabel("キュー")
        header.setStyleSheet("font-weight: bold; font-size: 13px; padding: 2px 0;")
        layout.addWidget(header)

        # ボタン行
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(4)

        self.btn_add_file = QPushButton("+ ファイル")
        self.btn_add_file.clicked.connect(self._on_add_file)
        btn_layout.addWidget(self.btn_add_file)

        self.btn_add_folder = QPushButton("+ フォルダ")
        self.btn_add_folder.clicked.connect(self._on_add_folder)
        btn_layout.addWidget(self.btn_add_folder)

        self.btn_remove = QPushButton("削除")
        self.btn_remove.clicked.connect(self._on_remove)
        btn_layout.addWidget(self.btn_remove)

        layout.addLayout(btn_layout)

        # テーブル
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["ID", "ファイル名", "ステータス"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setColumnWidth(0, 30)
        self.table.setColumnWidth(2, 80)
        self.table.doubleClicked.connect(self._on_double_click)

        layout.addWidget(self.table)

        # D&Dヒント
        self.drop_hint = QLabel("D&Dでファイル追加 / ダブルクリックで編集開始")
        self.drop_hint.setAlignment(Qt.AlignCenter)
        self.drop_hint.setStyleSheet("color: #666; font-size: 10px; padding: 4px;")
        layout.addWidget(self.drop_hint)

    def _on_double_click(self, index):
        """ダブルクリックで編集開始"""
        self._on_open_video()

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

    def _on_remove(self):
        row = self.table.currentRow()
        if row >= 0:
            job_id = int(self.table.item(row, 0).text())
            self.job_queue.remove_job(job_id)
            self.refresh()

    def _on_open_video(self):
        """編集を開始"""
        row = self.table.currentRow()
        if row >= 0:
            job_id = int(self.table.item(row, 0).text())
            job = self.job_queue.get_job_by_id(job_id)
            if job and job.status in [JobStatus.WAITING, JobStatus.REVIEW]:
                self.open_video.emit(job)
        else:
            job = self.job_queue.get_next_waiting()
            if job:
                self.open_video.emit(job)

    def _on_selection_changed(self):
        row = self.table.currentRow()
        if row >= 0:
            job_id = int(self.table.item(row, 0).text())
            job = self.job_queue.get_job_by_id(job_id)
            if job:
                self.job_selected.emit(job)

    def refresh(self):
        """テーブルを更新"""
        jobs = self.job_queue.get_all_jobs()
        self.table.setRowCount(len(jobs))

        for row, job in enumerate(jobs):
            self.table.setItem(row, 0, QTableWidgetItem(str(job.id)))
            self.table.setItem(row, 1, QTableWidgetItem(job.filename))
            self.table.setItem(row, 2, QTableWidgetItem(job.status.value))

            # ステータスに応じた色付け
            status_item = self.table.item(row, 2)
            if job.status == JobStatus.DONE:
                status_item.setBackground(Qt.green)
            elif job.status == JobStatus.ERROR:
                status_item.setBackground(Qt.red)
            elif job.status == JobStatus.REVIEW:
                status_item.setBackground(Qt.cyan)

    def select_job(self, job_id: int):
        """指定IDのジョブを選択"""
        for row in range(self.table.rowCount()):
            if int(self.table.item(row, 0).text()) == job_id:
                self.table.selectRow(row)
                break

    def get_selected_job(self) -> VideoJob:
        """選択中のジョブを取得"""
        row = self.table.currentRow()
        if row >= 0:
            job_id = int(self.table.item(row, 0).text())
            return self.job_queue.get_job_by_id(job_id)
        return None
