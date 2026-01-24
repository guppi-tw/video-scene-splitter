"""
設定ウィジェット - シーン検知パラメータの調整
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QDoubleSpinBox, QSlider, QPushButton
)
from PySide6.QtCore import Signal, Qt


class SettingsWidget(QWidget):
    """シーン検知設定ウィジェット"""
    
    settings_changed = Signal()
    
    # デフォルト値
    DEFAULT_THRESHOLD = 27.0
    DEFAULT_MIN_SCENE_LEN = 2.0
    
    # VHS向け推奨値
    VHS_THRESHOLD = 40.0
    VHS_MIN_SCENE_LEN = 5.0
    
    def __init__(self):
        super().__init__()
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # シーン検知設定グループ
        group = QGroupBox("シーン検知設定")
        group_layout = QVBoxLayout(group)
        
        # 閾値設定
        threshold_layout = QHBoxLayout()
        threshold_layout.addWidget(QLabel("閾値:"))
        
        self.threshold_slider = QSlider(Qt.Horizontal)
        self.threshold_slider.setRange(10, 80)
        self.threshold_slider.setValue(int(self.DEFAULT_THRESHOLD))
        self.threshold_slider.setTickPosition(QSlider.TicksBelow)
        self.threshold_slider.setTickInterval(10)
        self.threshold_slider.valueChanged.connect(self._on_threshold_slider_changed)
        threshold_layout.addWidget(self.threshold_slider)
        
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(10.0, 80.0)
        self.threshold_spin.setValue(self.DEFAULT_THRESHOLD)
        self.threshold_spin.setSingleStep(1.0)
        self.threshold_spin.setFixedWidth(70)
        self.threshold_spin.valueChanged.connect(self._on_threshold_spin_changed)
        threshold_layout.addWidget(self.threshold_spin)
        
        group_layout.addLayout(threshold_layout)
        
        # 閾値の説明
        threshold_help = QLabel(
            "低い値 = 敏感（シーン多）　高い値 = 鈍感（シーン少）"
        )
        threshold_help.setStyleSheet("color: #666; font-size: 11px;")
        group_layout.addWidget(threshold_help)
        
        # 最小シーン長設定
        min_len_layout = QHBoxLayout()
        min_len_layout.addWidget(QLabel("最小シーン長:"))
        
        self.min_len_slider = QSlider(Qt.Horizontal)
        self.min_len_slider.setRange(5, 300)  # 0.5秒〜30秒（×10）
        self.min_len_slider.setValue(int(self.DEFAULT_MIN_SCENE_LEN * 10))
        self.min_len_slider.setTickPosition(QSlider.TicksBelow)
        self.min_len_slider.setTickInterval(50)
        self.min_len_slider.valueChanged.connect(self._on_min_len_slider_changed)
        min_len_layout.addWidget(self.min_len_slider)
        
        self.min_len_spin = QDoubleSpinBox()
        self.min_len_spin.setRange(0.5, 30.0)
        self.min_len_spin.setValue(self.DEFAULT_MIN_SCENE_LEN)
        self.min_len_spin.setSingleStep(0.5)
        self.min_len_spin.setSuffix(" 秒")
        self.min_len_spin.setFixedWidth(80)
        self.min_len_spin.valueChanged.connect(self._on_min_len_spin_changed)
        min_len_layout.addWidget(self.min_len_spin)
        
        group_layout.addLayout(min_len_layout)
        
        # 最小シーン長の説明
        min_len_help = QLabel(
            "この長さ未満のシーンは無視されます"
        )
        min_len_help.setStyleSheet("color: #666; font-size: 11px;")
        group_layout.addWidget(min_len_help)
        
        # プリセットボタン
        preset_layout = QHBoxLayout()
        
        self.btn_default = QPushButton("標準設定")
        self.btn_default.clicked.connect(self._apply_default_preset)
        preset_layout.addWidget(self.btn_default)
        
        self.btn_vhs = QPushButton("VHS向け設定")
        self.btn_vhs.clicked.connect(self._apply_vhs_preset)
        self.btn_vhs.setToolTip("ノイズが多い映像向け（閾値40、最小5秒）")
        preset_layout.addWidget(self.btn_vhs)
        
        preset_layout.addStretch()
        
        group_layout.addLayout(preset_layout)
        
        layout.addWidget(group)
    
    def _on_threshold_slider_changed(self, value: int):
        self.threshold_spin.blockSignals(True)
        self.threshold_spin.setValue(float(value))
        self.threshold_spin.blockSignals(False)
        self.settings_changed.emit()
    
    def _on_threshold_spin_changed(self, value: float):
        self.threshold_slider.blockSignals(True)
        self.threshold_slider.setValue(int(value))
        self.threshold_slider.blockSignals(False)
        self.settings_changed.emit()
    
    def _on_min_len_slider_changed(self, value: int):
        self.min_len_spin.blockSignals(True)
        self.min_len_spin.setValue(value / 10.0)
        self.min_len_spin.blockSignals(False)
        self.settings_changed.emit()
    
    def _on_min_len_spin_changed(self, value: float):
        self.min_len_slider.blockSignals(True)
        self.min_len_slider.setValue(int(value * 10))
        self.min_len_slider.blockSignals(False)
        self.settings_changed.emit()
    
    def _apply_default_preset(self):
        self.threshold_spin.setValue(self.DEFAULT_THRESHOLD)
        self.min_len_spin.setValue(self.DEFAULT_MIN_SCENE_LEN)
    
    def _apply_vhs_preset(self):
        self.threshold_spin.setValue(self.VHS_THRESHOLD)
        self.min_len_spin.setValue(self.VHS_MIN_SCENE_LEN)
    
    @property
    def threshold(self) -> float:
        return self.threshold_spin.value()
    
    @property
    def min_scene_len_sec(self) -> float:
        return self.min_len_spin.value()
