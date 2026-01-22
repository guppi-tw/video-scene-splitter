"""
ログ表示ウィジェット
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QLabel, QHBoxLayout
from PySide6.QtCore import Qt


class LogWidget(QWidget):
    """ログ・進捗表示ウィジェット"""
    
    def __init__(self):
        super().__init__()
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # ステータス行
        status_layout = QHBoxLayout()
        
        self.status_label = QLabel("待機中")
        self.status_label.setStyleSheet("font-weight: bold;")
        status_layout.addWidget(self.status_label)
        
        status_layout.addStretch()
        
        self.progress_label = QLabel("")
        status_layout.addWidget(self.progress_label)
        
        layout.addLayout(status_layout)
        
        # ログテキスト
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: monospace;
                font-size: 12px;
            }
        """)
        layout.addWidget(self.log_text)
    
    def set_status(self, status: str):
        """ステータスを設定"""
        self.status_label.setText(status)
    
    def set_progress(self, progress: str):
        """進捗を設定"""
        self.progress_label.setText(progress)
    
    def append_log(self, message: str):
        """ログを追加"""
        self.log_text.append(message)
        # 自動スクロール
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def clear_log(self):
        """ログをクリア"""
        self.log_text.clear()
