"""
短いシーンの結合提案ダイアログ

自動検出の完了後に表示し、閾値を変えて検出をやり直さなくても
細切れシーンをその場でまとめられるようにする。
"""
from typing import List

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QPushButton
)

from app.core.scene_detector import absorb_short_scenes


class MergeProposalDialog(QDialog):
    """N秒未満のシーンを隣に統合する提案ダイアログ"""

    def __init__(
        self,
        boundaries: List[float],
        duration: float,
        initial_min_seconds: float = 3.0,
        parent=None,
    ):
        super().__init__(parent)
        self._boundaries = list(boundaries)
        self._duration = duration

        self.setWindowTitle("短いシーンの結合")
        self.setModal(True)
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        intro = QLabel(
            "短いシーンを隣のシーンに統合できます。\n"
            "秒数を変えると結合後のシーン数がプレビューされます。"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # 秒数指定
        spin_layout = QHBoxLayout()
        spin_layout.addWidget(QLabel("この長さ未満のシーンを統合:"))
        self.min_seconds_spin = QDoubleSpinBox()
        self.min_seconds_spin.setRange(0.5, 60.0)
        self.min_seconds_spin.setSingleStep(0.5)
        self.min_seconds_spin.setDecimals(1)
        self.min_seconds_spin.setSuffix(" 秒")
        self.min_seconds_spin.setValue(initial_min_seconds)
        self.min_seconds_spin.valueChanged.connect(self._update_preview)
        spin_layout.addWidget(self.min_seconds_spin)
        spin_layout.addStretch()
        layout.addLayout(spin_layout)

        # プレビュー表示
        self.preview_label = QLabel()
        self.preview_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.preview_label)

        # ボタン
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.btn_skip = QPushButton("そのまま")
        self.btn_skip.clicked.connect(self.reject)
        button_layout.addWidget(self.btn_skip)

        self.btn_merge = QPushButton("結合する")
        self.btn_merge.setObjectName("btn_export")
        self.btn_merge.setDefault(True)
        self.btn_merge.clicked.connect(self.accept)
        button_layout.addWidget(self.btn_merge)

        layout.addLayout(button_layout)

        self._update_preview()

    def merged_boundaries(self) -> List[float]:
        """現在の秒数設定で結合した境界リストを返す"""
        return absorb_short_scenes(
            self._boundaries, self._duration, self.min_seconds_spin.value()
        )

    def merge_count(self) -> int:
        """結合により減るシーン数"""
        return len(self._boundaries) - len(self.merged_boundaries())

    def _update_preview(self):
        before = len(self._boundaries)
        after = len(self.merged_boundaries())
        if after < before:
            self.preview_label.setText(
                f"シーン数: {before} → {after}（{before - after}個を統合）"
            )
            self.btn_merge.setEnabled(True)
        else:
            self.preview_label.setText(
                f"シーン数: {before}（この長さ未満のシーンはありません）"
            )
            self.btn_merge.setEnabled(False)
