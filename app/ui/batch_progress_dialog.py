"""
一括シーン検出の進捗ダイアログ
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextEdit
)


class BatchProgressDialog(QDialog):
    """一括処理中の状況を独立して見せるモデルレスダイアログ"""

    cancel_requested = Signal()

    def __init__(self, total_videos: int, parent=None):
        super().__init__(parent)
        self._running = True

        self.setWindowTitle("一括シーン検出")
        self.setModal(False)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.summary_label = QLabel(
            f"{total_videos} 本の動画を順番にシーン検出しています。"
        )
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.current_label = QLabel("準備中...")
        self.current_label.setStyleSheet("font-weight: bold;")
        self.current_label.setWordWrap(True)
        layout.addWidget(self.current_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        layout.addWidget(self.progress_bar)

        self.result_log = QTextEdit()
        self.result_log.setReadOnly(True)
        self.result_log.setMinimumHeight(120)
        self.result_log.setStyleSheet("""
            QTextEdit {
                background-color: #202020;
                color: #d4d4d4;
                font-family: monospace;
                font-size: 12px;
            }
        """)
        layout.addWidget(self.result_log)

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.btn_cancel = QPushButton("キャンセル")
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        button_layout.addWidget(self.btn_cancel)

        self.btn_close = QPushButton("閉じる")
        self.btn_close.clicked.connect(self.accept)
        self.btn_close.setEnabled(False)
        button_layout.addWidget(self.btn_close)

        layout.addLayout(button_layout)

    def set_current_message(self, message: str):
        self.current_label.setText(message)

    def set_progress(self, percent: int):
        value = max(0, min(100, int(percent)))
        self.progress_bar.setValue(value)

    def add_result(self, message: str):
        self.result_log.append(message)
        scrollbar = self.result_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def set_cancelling(self):
        self.current_label.setText("キャンセルしています...")
        self.btn_cancel.setEnabled(False)

    def set_finished(self, message: str):
        self._running = False
        self.current_label.setText(message)
        self.progress_bar.setValue(100)
        self.btn_cancel.setEnabled(False)
        self.btn_close.setEnabled(True)
        self.btn_close.setDefault(True)

    def _on_cancel_clicked(self):
        self.set_cancelling()
        self.cancel_requested.emit()

    def closeEvent(self, event):
        if self._running:
            self.hide()
            event.ignore()
            return
        super().closeEvent(event)
