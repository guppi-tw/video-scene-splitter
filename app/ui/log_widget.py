"""
ログ表示ウィジェット
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLabel, QProgressBar,
    QPushButton,
)


class LogWidget(QWidget):
    """ログ・進捗表示ウィジェット"""
    
    def __init__(self):
        super().__init__()
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # ステータス行は常設し、詳細ログだけを必要時に開く。
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 0, 0, 0)
        self.status_label = QLabel("待機中")
        self.status_label.setStyleSheet("font-weight: bold;")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        self.btn_toggle_details = QPushButton("詳細")
        self.btn_toggle_details.setToolTip("処理ログを表示")
        self.btn_toggle_details.setAccessibleName("処理ログの詳細を表示")
        self.btn_toggle_details.clicked.connect(self._toggle_details)
        status_layout.addWidget(self.btn_toggle_details)
        layout.addLayout(status_layout)

        # プログレスバー
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p% (%v / %m)")
        self.progress_bar.hide()  # 初期状態では非表示
        layout.addWidget(self.progress_bar)
        
        # 詳細進捗ラベル
        self.detail_label = QLabel("")
        self.detail_label.setStyleSheet("color: #666; font-size: 11px;")
        self.detail_label.hide()
        layout.addWidget(self.detail_label)
        
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
        self.log_text.hide()
        layout.addWidget(self.log_text)

    def _toggle_details(self):
        visible = self.log_text.isHidden()
        self.log_text.setVisible(visible)
        self.btn_toggle_details.setText("閉じる" if visible else "詳細")
        self.btn_toggle_details.setToolTip(
            "処理ログを閉じる" if visible else "処理ログを表示"
        )
    
    def set_status(self, status: str):
        """ステータスを設定"""
        self.status_label.setText(status)

    def set_progress_bar(self, current: int, total: int, show: bool = True):
        """プログレスバーを更新"""
        if show:
            self.progress_bar.show()
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
            self.progress_bar.setFormat(f"%p% ({current:,} / {total:,})")
        else:
            self.progress_bar.hide()

    def set_detail(self, detail: str, show: bool = True):
        """詳細進捗を設定"""
        if show and detail:
            self.detail_label.setText(detail)
            self.detail_label.show()
        else:
            self.detail_label.hide()
    
    def hide_progress(self):
        """プログレスバーと詳細を非表示"""
        self.progress_bar.hide()
        self.detail_label.hide()
    
    def append_log(self, message: str):
        """ログを追加"""
        self.log_text.append(message)
        # 自動スクロール
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def clear_log(self):
        """ログをクリア"""
        self.log_text.clear()
