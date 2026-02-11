"""
キュー表示ウィジェット
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QAbstractItemView, QLabel
)
from PySide6.QtCore import Signal, Qt

from app.core import JobQueue, VideoJob, JobStatus


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

        # 編集開始ボタン
        self.btn_open = QPushButton("編集を開始")
        self.btn_open.setToolTip("選択した動画を開いて手動で分割編集します (ダブルクリックでも可)")
        self.btn_open.clicked.connect(self._on_open_video)
        self.btn_open.setStyleSheet("font-weight: bold; padding: 6px;")
        layout.addWidget(self.btn_open)

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
        self.drop_hint = QLabel("ここにファイルをドラッグ&ドロップ")
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
        from pathlib import Path
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file() and path.suffix.lower() == '.mp4':
                self.job_queue.add_file(path)
            elif path.is_dir():
                self.job_queue.add_folder(path)
        self.refresh()

    def _on_add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "フォルダを選択")
        if folder:
            from pathlib import Path
            self.job_queue.add_folder(Path(folder))
            self.refresh()

    def _on_add_file(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "ファイルを選択", "", "MP4 Files (*.mp4)"
        )
        for f in files:
            from pathlib import Path
            self.job_queue.add_file(Path(f))
        self.refresh()

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
