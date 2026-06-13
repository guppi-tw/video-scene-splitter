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
    """単色つなぎ目シーンの除外を提案するダイアログ"""

    def __init__(self, blank_scenes: List[Tuple[int, str, float]], parent=None):
        """blank_scenes: (シーン番号, ラベル, 長さ秒) のリスト"""
        super().__init__(parent)
        self._blank_scenes = blank_scenes

        self.setWindowTitle("つなぎ目の除外")
        self.setModal(True)
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        total_seconds = sum(d for _, _, d in blank_scenes)
        labels = sorted({label for _, label, _ in blank_scenes})
        kinds = "・".join(labels) if labels else "単色"

        intro = QLabel(
            f"映像のつなぎ目とみられる{kinds}一色のシーンを "
            f"{len(blank_scenes)} 個（合計 {format_seconds(total_seconds)}）"
            "検出しました。\n書き出し対象から除外しますか？"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        detail = QLabel(
            "、".join(
                f"#{index}（{label}・{format_seconds(d)}）"
                for index, label, d in blank_scenes[:12]
            )
            + ("…" if len(blank_scenes) > 12 else "")
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
