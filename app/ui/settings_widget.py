"""
設定ウィジェット - シーン検知パラメータの調整
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QDoubleSpinBox, QSlider, QPushButton, QCheckBox
)
from PySide6.QtCore import Signal, Qt


class SettingsWidget(QWidget):
    """シーン検知設定ウィジェット"""
    
    settings_changed = Signal()
    
    # デフォルト値
    DEFAULT_THRESHOLD = 27.0
    DEFAULT_MIN_SCENE_LEN = 2.0
    DEFAULT_DETECT_BLANKS = True
    DEFAULT_BLANK_VARIANCE = 500.0
    DEFAULT_MIN_BLANK_DURATION = 0.2
    
    # VHS向け推奨値
    VHS_THRESHOLD = 40.0
    VHS_MIN_SCENE_LEN = 5.0
    VHS_DETECT_BLANKS = True
    VHS_BLANK_VARIANCE = 800.0  # VHSはノイズが多いので緩めに
    VHS_MIN_BLANK_DURATION = 0.3
    
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
        
        layout.addWidget(group)
        
        # ブランク検出設定グループ
        blank_group = QGroupBox("ブランク検出（VHS向け）")
        blank_layout = QVBoxLayout(blank_group)
        
        # ブランク検出の有効/無効
        self.detect_blanks_check = QCheckBox("単色画面（青・グレー・白等）で分割")
        self.detect_blanks_check.setChecked(self.DEFAULT_DETECT_BLANKS)
        self.detect_blanks_check.stateChanged.connect(self._on_detect_blanks_changed)
        blank_layout.addWidget(self.detect_blanks_check)
        
        # ブランク検出の説明
        blank_help = QLabel(
            "VHSテープの未録画部分や切り替わりで出る\n"
            "単色画面を検出してシーンを分割します"
        )
        blank_help.setStyleSheet("color: #666; font-size: 11px;")
        blank_layout.addWidget(blank_help)
        
        # 感度設定
        sensitivity_layout = QHBoxLayout()
        sensitivity_layout.addWidget(QLabel("検出感度:"))
        
        self.blank_variance_slider = QSlider(Qt.Horizontal)
        self.blank_variance_slider.setRange(100, 2000)  # 分散閾値
        self.blank_variance_slider.setValue(int(self.DEFAULT_BLANK_VARIANCE))
        self.blank_variance_slider.setTickPosition(QSlider.TicksBelow)
        self.blank_variance_slider.setTickInterval(300)
        self.blank_variance_slider.valueChanged.connect(self._on_blank_variance_changed)
        sensitivity_layout.addWidget(self.blank_variance_slider)
        
        self.blank_variance_label = QLabel(f"{int(self.DEFAULT_BLANK_VARIANCE)}")
        self.blank_variance_label.setFixedWidth(50)
        sensitivity_layout.addWidget(self.blank_variance_label)
        
        blank_layout.addLayout(sensitivity_layout)
        
        # 感度の説明
        sensitivity_help = QLabel(
            "低い値 = 厳密（完全な単色のみ）　高い値 = 緩い（多少のノイズOK）"
        )
        sensitivity_help.setStyleSheet("color: #666; font-size: 11px;")
        blank_layout.addWidget(sensitivity_help)
        
        # 最小ブランク長
        min_blank_layout = QHBoxLayout()
        min_blank_layout.addWidget(QLabel("最小ブランク長:"))
        
        self.min_blank_spin = QDoubleSpinBox()
        self.min_blank_spin.setRange(0.1, 5.0)
        self.min_blank_spin.setValue(self.DEFAULT_MIN_BLANK_DURATION)
        self.min_blank_spin.setSingleStep(0.1)
        self.min_blank_spin.setSuffix(" 秒")
        self.min_blank_spin.setFixedWidth(80)
        self.min_blank_spin.valueChanged.connect(self._on_settings_changed)
        min_blank_layout.addWidget(self.min_blank_spin)
        min_blank_layout.addStretch()
        
        blank_layout.addLayout(min_blank_layout)
        
        layout.addWidget(blank_group)
        
        # プリセットボタン
        preset_group = QGroupBox("プリセット")
        preset_layout = QHBoxLayout(preset_group)
        
        self.btn_default = QPushButton("標準設定")
        self.btn_default.clicked.connect(self._apply_default_preset)
        preset_layout.addWidget(self.btn_default)
        
        self.btn_vhs = QPushButton("VHS向け設定")
        self.btn_vhs.clicked.connect(self._apply_vhs_preset)
        self.btn_vhs.setToolTip(
            "VHSテープ向けの推奨設定\n"
            "・閾値40（ノイズに強い）\n"
            "・最小シーン長5秒\n"
            "・ブランク検出ON"
        )
        preset_layout.addWidget(self.btn_vhs)
        
        preset_layout.addStretch()
        
        layout.addWidget(preset_group)
        
        # 初期状態でブランク設定の有効/無効を設定
        self._update_blank_settings_enabled()
    
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
    
    def _on_detect_blanks_changed(self, state: int):
        self._update_blank_settings_enabled()
        self.settings_changed.emit()
    
    def _on_blank_variance_changed(self, value: int):
        self.blank_variance_label.setText(str(value))
        self.settings_changed.emit()
    
    def _on_settings_changed(self):
        self.settings_changed.emit()
    
    def _update_blank_settings_enabled(self):
        """ブランク検出設定の有効/無効を更新"""
        enabled = self.detect_blanks_check.isChecked()
        self.blank_variance_slider.setEnabled(enabled)
        self.blank_variance_label.setEnabled(enabled)
        self.min_blank_spin.setEnabled(enabled)
    
    def _apply_default_preset(self):
        self.threshold_spin.setValue(self.DEFAULT_THRESHOLD)
        self.min_len_spin.setValue(self.DEFAULT_MIN_SCENE_LEN)
        self.detect_blanks_check.setChecked(self.DEFAULT_DETECT_BLANKS)
        self.blank_variance_slider.setValue(int(self.DEFAULT_BLANK_VARIANCE))
        self.min_blank_spin.setValue(self.DEFAULT_MIN_BLANK_DURATION)
    
    def _apply_vhs_preset(self):
        self.threshold_spin.setValue(self.VHS_THRESHOLD)
        self.min_len_spin.setValue(self.VHS_MIN_SCENE_LEN)
        self.detect_blanks_check.setChecked(self.VHS_DETECT_BLANKS)
        self.blank_variance_slider.setValue(int(self.VHS_BLANK_VARIANCE))
        self.min_blank_spin.setValue(self.VHS_MIN_BLANK_DURATION)
    
    @property
    def threshold(self) -> float:
        return self.threshold_spin.value()
    
    @property
    def min_scene_len_sec(self) -> float:
        return self.min_len_spin.value()
    
    @property
    def detect_blanks(self) -> bool:
        return self.detect_blanks_check.isChecked()
    
    @property
    def blank_variance_threshold(self) -> float:
        return float(self.blank_variance_slider.value())
    
    @property
    def min_blank_duration(self) -> float:
        return self.min_blank_spin.value()
