"""動画未選択時の中央ドロップ領域。"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class VideoDropZone(QFrame):
    paths_dropped = Signal(list)
    add_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("videoDropZone")
        self.setStyleSheet(
            "QFrame#videoDropZone {"
            "border: 2px dashed #555; border-radius: 8px; background: #202020;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(10)

        title = QLabel("動画をここにドロップ")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel("MP4ファイルまたは動画を含むフォルダ")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #aaa;")
        layout.addWidget(subtitle)

        button = QPushButton("動画を追加")
        button.setAccessibleName("動画を追加")
        button.clicked.connect(self.add_requested.emit)
        layout.addWidget(button, alignment=Qt.AlignCenter)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        if paths:
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()
