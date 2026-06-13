"""
単色つなぎ目シーンの除外提案ダイアログ

昔のテープの映像間に入る青一色・黒一色のつなぎ目を検出した結果を提示し、
まとめて除外（Keepオフ）するか確認する。
"""
from typing import List, Tuple

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)

from app.core.time_format import format_seconds


class BlankCutDialog(QDialog):
    """単色つなぎ目区間の除外を提案するダイアログ"""

    def __init__(self, segments: List[Tuple[float, float, str]], parent=None):
        """segments: (開始秒, 終了秒, ラベル) のリスト"""
        super().__init__(parent)
        self._segments = segments

        self.setWindowTitle("つなぎ目の除外")
        self.setModal(True)
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        total_seconds = sum(e - s for s, e, _ in segments)
        labels = sorted({label for _, _, label in segments})
        kinds = "・".join(labels) if labels else "単色"

        intro = QLabel(
            f"映像のつなぎ目とみられる{kinds}一色の区間を "
            f"{len(segments)} 個（合計 {format_seconds(total_seconds)}）"
            "検出しました。\n書き出し対象から除外しますか？"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        detail = QLabel(
            "、".join(
                f"{format_seconds(s)}〜{format_seconds(e)}（{label}）"
                for s, e, label in segments[:10]
            )
            + ("…" if len(segments) > 10 else "")
        )
        detail.setWordWrap(True)
        detail.setStyleSheet("color: #aaa; font-size: 11px;")
        layout.addWidget(detail)

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.btn_skip = QPushButton("残す")
        self.btn_skip.clicked.connect(self.reject)
        button_layout.addWidget(self.btn_skip)

        self.btn_cut = QPushButton("除外する")
        self.btn_cut.setObjectName("btn_export")
        self.btn_cut.setDefault(True)
        self.btn_cut.clicked.connect(self.accept)
        button_layout.addWidget(self.btn_cut)

        layout.addLayout(button_layout)
