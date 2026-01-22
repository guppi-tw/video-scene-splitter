"""
キュー表示ウィジェット
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QAbstractItemView
)
from PySide6.QtCore import Signal

from ..core import JobQueue, VideoJob, JobStatus


class QueueWidget(QWidget):
    """ジョブキュー表示・操作ウィジェット"""
    
    job_selected = Signal(object)  # VideoJob
    start_processing = Signal()
    
    def __init__(self, job_queue: JobQueue):
        super().__init__()
        self.job_queue = job_queue
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # ボタン行
        btn_layout = QHBoxLayout()
        
        self.btn_add_folder = QPushButton("フォルダ追加")
        self.btn_add_folder.clicked.connect(self._on_add_folder)
        btn_layout.addWidget(self.btn_add_folder)
        
        self.btn_add_file = QPushButton("ファイル追加")
        self.btn_add_file.clicked.connect(self._on_add_file)
        btn_layout.addWidget(self.btn_add_file)
        
        self.btn_remove = QPushButton("削除")
        self.btn_remove.clicked.connect(self._on_remove)
        btn_layout.addWidget(self.btn_remove)
        
        btn_layout.addStretch()
        
        self.btn_start = QPushButton("処理開始")
        self.btn_start.clicked.connect(self.start_processing.emit)
        btn_layout.addWidget(self.btn_start)
        
        layout.addLayout(btn_layout)
        
        # テーブル
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["ID", "ファイル名", "ステータス", "パス"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        
        layout.addWidget(self.table)
    
    def _on_add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "フォルダを選択")
        if folder:
            from pathlib import Path
            added = self.job_queue.add_folder(Path(folder))
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
            self.table.setItem(row, 3, QTableWidgetItem(str(job.source_path)))
            
            # ステータスに応じた色付け
            status_item = self.table.item(row, 2)
            if job.status == JobStatus.DONE:
                status_item.setBackground(Qt.green)
            elif job.status == JobStatus.ERROR:
                status_item.setBackground(Qt.red)
            elif job.status == JobStatus.PROCESSING:
                status_item.setBackground(Qt.yellow)
            elif job.status == JobStatus.REVIEW:
                status_item.setBackground(Qt.cyan)
    
    def select_job(self, job_id: int):
        """指定IDのジョブを選択"""
        for row in range(self.table.rowCount()):
            if int(self.table.item(row, 0).text()) == job_id:
                self.table.selectRow(row)
                break


from PySide6.QtCore import Qt
