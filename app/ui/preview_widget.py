"""
動画プレビューウィジェット - Qt Multimediaベース
"""
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QSlider, QLabel, QStyle, QSizePolicy, QComboBox
)
from PySide6.QtCore import Qt, QUrl, Signal, Slot
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

from app.core.time_format import format_ms_tenths


class PreviewWidget(QWidget):
    """動画プレビューウィジェット"""
    
    # シグナル
    position_changed = Signal(float)  # 再生位置が変わった（秒）
    split_requested = Signal(float)   # ここで分割（秒）
    error_occurred = Signal(str)      # 再生エラー
    
    def __init__(self):
        super().__init__()
        self.current_video_path: Optional[Path] = None
        self._duration_ms = 0
        self._setup_ui()
        self._setup_player()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        
        # ビデオ表示エリア
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumSize(320, 180)
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_widget.setStyleSheet("background-color: #000;")
        layout.addWidget(self.video_widget, stretch=1)
        
        # コントロールバー（1行目: 再生操作）
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(5)

        # 再生/一時停止ボタン
        self.btn_play = QPushButton()
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.btn_play.setAccessibleName("再生または一時停止")
        self.btn_play.setToolTip("再生／一時停止 (Space)")
        self.btn_play.setFixedSize(32, 32)
        self.btn_play.clicked.connect(self._on_play_clicked)
        self.btn_play.setEnabled(False)
        controls_layout.addWidget(self.btn_play)

        # 停止ボタン
        self.btn_stop = QPushButton()
        self.btn_stop.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.btn_stop.setAccessibleName("停止")
        self.btn_stop.setToolTip("再生を停止")
        self.btn_stop.setFixedSize(32, 32)
        self.btn_stop.clicked.connect(self._on_stop_clicked)
        self.btn_stop.setEnabled(False)
        controls_layout.addWidget(self.btn_stop)

        controls_layout.addSpacing(10)

        # ここで分割ボタン
        self.btn_split = QPushButton("ここで分割 [S]")
        self.btn_split.setObjectName("btn_split")
        self.btn_split.setToolTip("現在の再生位置に分割点を追加 (S)")
        self.btn_split.clicked.connect(self._on_split_clicked)
        self.btn_split.setEnabled(False)
        controls_layout.addWidget(self.btn_split)

        controls_layout.addSpacing(10)

        # 時間表示
        self.time_label = QLabel("00:00.0 / 00:00.0")
        self.time_label.setMinimumWidth(140)
        controls_layout.addWidget(self.time_label)

        controls_layout.addStretch()

        # 音量スライダー
        self.btn_volume = QPushButton()
        self.btn_volume.setIcon(self.style().standardIcon(QStyle.SP_MediaVolume))
        self.btn_volume.setAccessibleName("ミュート切り替え")
        self.btn_volume.setToolTip("音声のミュートを切り替え")
        self.btn_volume.setFixedSize(32, 32)
        self.btn_volume.clicked.connect(self._on_mute_clicked)
        controls_layout.addWidget(self.btn_volume)

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setAccessibleName("音量")
        self.volume_slider.setFixedWidth(80)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        controls_layout.addWidget(self.volume_slider)

        layout.addLayout(controls_layout)

        # コントロールバー（2行目: 送り（幅切替）+ 再生速度）
        controls2_layout = QHBoxLayout()
        controls2_layout.setSpacing(5)

        # 戻すボタン（移動幅はセレクタで切替）
        self.btn_step_back = QPushButton()
        self.btn_step_back.setIcon(self.style().standardIcon(QStyle.SP_MediaSeekBackward))
        self.btn_step_back.setAccessibleName("選択した幅だけ戻る")
        self.btn_step_back.setFixedSize(32, 24)
        self.btn_step_back.clicked.connect(self._on_step_back)
        self.btn_step_back.setEnabled(False)
        self.btn_step_back.setToolTip("選択した幅だけ戻る（←）")
        controls2_layout.addWidget(self.btn_step_back)

        # 移動幅セレクタ（コマ送り〜数秒ジャンプまで兼用）
        self.step_combo = QComboBox()
        self.step_combo.setFixedHeight(24)
        self._step_values = [0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0]
        for v in self._step_values:
            if v >= 1.0:
                self.step_combo.addItem(f"{v:.0f}秒")
            else:
                self.step_combo.addItem(f"{v:.2f}秒")
        self.step_combo.setCurrentIndex(2)  # 0.5秒デフォルト
        self.step_combo.setAccessibleName("戻る／進むの移動幅")
        self.step_combo.setToolTip("戻る／進むの移動幅")
        controls2_layout.addWidget(self.step_combo)

        # 進むボタン（移動幅はセレクタで切替）
        self.btn_step_forward = QPushButton()
        self.btn_step_forward.setIcon(self.style().standardIcon(QStyle.SP_MediaSeekForward))
        self.btn_step_forward.setAccessibleName("選択した幅だけ進む")
        self.btn_step_forward.setFixedSize(32, 24)
        self.btn_step_forward.clicked.connect(self._on_step_forward)
        self.btn_step_forward.setEnabled(False)
        self.btn_step_forward.setToolTip("選択した幅だけ進む（→）")
        controls2_layout.addWidget(self.btn_step_forward)

        controls2_layout.addSpacing(20)

        # 再生速度
        speed_label = QLabel("速度:")
        speed_label.setFixedHeight(24)
        controls2_layout.addWidget(speed_label)

        self.speed_combo = QComboBox()
        self.speed_combo.setFixedHeight(24)
        self._speed_values = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
        for v in self._speed_values:
            self.speed_combo.addItem(f"x{v:.2f}" if v != int(v) else f"x{v:.1f}")
        self.speed_combo.setCurrentIndex(3)  # x1.0デフォルト
        self.speed_combo.setAccessibleName("再生速度")
        self.speed_combo.currentIndexChanged.connect(self._on_speed_changed)
        self.speed_combo.setToolTip("再生速度")
        controls2_layout.addWidget(self.speed_combo)

        controls2_layout.addStretch()

        layout.addLayout(controls2_layout)
    
    def _setup_player(self):
        """メディアプレイヤーをセットアップ"""
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        
        self.player.setVideoOutput(self.video_widget)
        self.player.setAudioOutput(self.audio_output)
        
        # 初期音量
        self.audio_output.setVolume(0.7)
        
        # シグナル接続
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.errorOccurred.connect(self._on_error)
    
    def load_video(self, video_path: Path):
        """動画を読み込む"""
        if not video_path or not video_path.exists():
            return
        
        self.current_video_path = video_path
        self.player.setSource(QUrl.fromLocalFile(str(video_path)))
        
        # コントロールを有効化
        self.btn_play.setEnabled(True)
        self.btn_stop.setEnabled(True)
        self.btn_split.setEnabled(True)
        self.btn_step_back.setEnabled(True)
        self.btn_step_forward.setEnabled(True)
    
    def play(self):
        """再生"""
        self.player.play()

    def toggle_play(self):
        """再生/一時停止を切り替え"""
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def play_from(self, position_sec: float):
        """指定位置から再生（一時停止中でも再生を開始する）"""
        self.seek_to(position_sec)
        self.player.play()

    def step_back(self):
        """コマ戻し（公開API）"""
        self._on_step_back()

    def step_forward(self):
        """コマ送り（公開API）"""
        self._on_step_forward()

    def request_split(self):
        """現在位置での分割を要求（公開API）"""
        self._on_split_clicked()

    def pause(self):
        """一時停止"""
        self.player.pause()
    
    def stop(self):
        """停止"""
        self.player.stop()
    
    def seek_to(self, position_sec: float):
        """指定位置にシーク（秒）"""
        position_ms = int(position_sec * 1000)
        self.player.setPosition(position_ms)
    
    def get_position(self) -> float:
        """現在の再生位置を取得（秒）"""
        return self.player.position() / 1000.0
    
    def get_duration(self) -> float:
        """動画の長さを取得（秒）"""
        return self._duration_ms / 1000.0
    
    def _seek_relative(self, delta_ms: int):
        """相対シーク"""
        new_pos = self.player.position() + delta_ms
        new_pos = max(0, min(new_pos, self._duration_ms))
        self.player.setPosition(new_pos)
    
    def _on_play_clicked(self):
        """再生/一時停止ボタン"""
        self.toggle_play()
    
    def _on_stop_clicked(self):
        """停止ボタン"""
        self.stop()

    def _on_split_clicked(self):
        """ここで分割ボタン"""
        pos = self.get_position()
        if pos > 0:
            self.split_requested.emit(pos)
    
    def _on_step_back(self):
        """コマ戻し"""
        step_sec = self._step_values[self.step_combo.currentIndex()]
        self.player.pause()
        self._seek_relative(int(-step_sec * 1000))

    def _on_step_forward(self):
        """コマ送り"""
        step_sec = self._step_values[self.step_combo.currentIndex()]
        self.player.pause()
        self._seek_relative(int(step_sec * 1000))

    def _on_speed_changed(self, index: int):
        """再生速度変更"""
        rate = self._speed_values[index]
        self.player.setPlaybackRate(rate)

    def _on_mute_clicked(self):
        """ミュートトグル"""
        is_muted = self.audio_output.isMuted()
        self.audio_output.setMuted(not is_muted)
        
        if is_muted:
            self.btn_volume.setIcon(self.style().standardIcon(QStyle.SP_MediaVolume))
        else:
            self.btn_volume.setIcon(self.style().standardIcon(QStyle.SP_MediaVolumeMuted))
    
    def _on_volume_changed(self, value: int):
        """音量変更"""
        self.audio_output.setVolume(value / 100.0)
    
    def _on_playback_state_changed(self, state):
        """再生状態変更"""
        if state == QMediaPlayer.PlayingState:
            self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        else:
            self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
    
    def _on_position_changed(self, position_ms: int):
        """再生位置変更"""
        self._update_time_label(position_ms)
        self.position_changed.emit(position_ms / 1000.0)

    def _on_duration_changed(self, duration_ms: int):
        """動画長さ変更"""
        self._duration_ms = duration_ms
        self._update_time_label(self.player.position())
    
    def _update_time_label(self, position_ms: int):
        """時間表示を更新"""
        current = self._format_time(position_ms)
        total = self._format_time(self._duration_ms)
        self.time_label.setText(f"{current} / {total}")
    
    @staticmethod
    def _format_time(ms: int) -> str:
        """ミリ秒を MM:SS.f 形式に変換"""
        return format_ms_tenths(ms)

    def _on_error(self, error, error_string):
        """エラー発生"""
        self.error_occurred.emit(f"動画の再生に失敗しました: {error_string}")

    def cleanup(self):
        """クリーンアップ（停止してコントロールを無効化）"""
        self.player.stop()
        self.player.setSource(QUrl())
        self.current_video_path = None
        self._duration_ms = 0
        self._update_time_label(0)
        for btn in (
            self.btn_play, self.btn_stop,
            self.btn_split, self.btn_step_back, self.btn_step_forward,
        ):
            btn.setEnabled(False)
