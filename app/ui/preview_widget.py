"""
動画プレビューウィジェット - Qt Multimediaベース
"""
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QSlider, QLabel, QStyle, QSizePolicy
)
from PySide6.QtCore import Qt, QUrl, Signal, Slot
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget


class PreviewWidget(QWidget):
    """動画プレビューウィジェット"""
    
    # シグナル
    position_changed = Signal(float)  # 再生位置が変わった（秒）
    
    def __init__(self):
        super().__init__()
        self.current_video_path: Optional[Path] = None
        self._duration_ms = 0
        self._is_seeking = False
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
        
        # シークバー
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setValue(0)
        self.seek_slider.sliderPressed.connect(self._on_slider_pressed)
        self.seek_slider.sliderReleased.connect(self._on_slider_released)
        self.seek_slider.sliderMoved.connect(self._on_slider_moved)
        layout.addWidget(self.seek_slider)
        
        # コントロールバー
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(5)
        
        # 再生/一時停止ボタン
        self.btn_play = QPushButton()
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.btn_play.setFixedSize(32, 32)
        self.btn_play.clicked.connect(self._on_play_clicked)
        self.btn_play.setEnabled(False)
        controls_layout.addWidget(self.btn_play)
        
        # 停止ボタン
        self.btn_stop = QPushButton()
        self.btn_stop.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.btn_stop.setFixedSize(32, 32)
        self.btn_stop.clicked.connect(self._on_stop_clicked)
        self.btn_stop.setEnabled(False)
        controls_layout.addWidget(self.btn_stop)
        
        # 5秒戻る
        self.btn_back = QPushButton()
        self.btn_back.setIcon(self.style().standardIcon(QStyle.SP_MediaSeekBackward))
        self.btn_back.setFixedSize(32, 32)
        self.btn_back.clicked.connect(lambda: self._seek_relative(-5000))
        self.btn_back.setEnabled(False)
        self.btn_back.setToolTip("5秒戻る")
        controls_layout.addWidget(self.btn_back)
        
        # 5秒進む
        self.btn_forward = QPushButton()
        self.btn_forward.setIcon(self.style().standardIcon(QStyle.SP_MediaSeekForward))
        self.btn_forward.setFixedSize(32, 32)
        self.btn_forward.clicked.connect(lambda: self._seek_relative(5000))
        self.btn_forward.setEnabled(False)
        self.btn_forward.setToolTip("5秒進む")
        controls_layout.addWidget(self.btn_forward)
        
        controls_layout.addSpacing(10)
        
        # 時間表示
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setMinimumWidth(100)
        controls_layout.addWidget(self.time_label)
        
        controls_layout.addStretch()
        
        # 音量スライダー
        self.btn_volume = QPushButton()
        self.btn_volume.setIcon(self.style().standardIcon(QStyle.SP_MediaVolume))
        self.btn_volume.setFixedSize(32, 32)
        self.btn_volume.clicked.connect(self._on_mute_clicked)
        controls_layout.addWidget(self.btn_volume)
        
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setFixedWidth(80)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        controls_layout.addWidget(self.volume_slider)
        
        layout.addLayout(controls_layout)
    
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
        self.btn_back.setEnabled(True)
        self.btn_forward.setEnabled(True)
    
    def play(self):
        """再生"""
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()
    
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
        self.play()
    
    def _on_stop_clicked(self):
        """停止ボタン"""
        self.stop()
    
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
        if not self._is_seeking and self._duration_ms > 0:
            slider_value = int((position_ms / self._duration_ms) * 1000)
            self.seek_slider.blockSignals(True)
            self.seek_slider.setValue(slider_value)
            self.seek_slider.blockSignals(False)
        
        # 時間表示を更新
        self._update_time_label(position_ms)
        
        # シグナル発行
        self.position_changed.emit(position_ms / 1000.0)
    
    def _on_duration_changed(self, duration_ms: int):
        """動画長さ変更"""
        self._duration_ms = duration_ms
        self._update_time_label(self.player.position())
    
    def _on_slider_pressed(self):
        """スライダー押下"""
        self._is_seeking = True
    
    def _on_slider_released(self):
        """スライダー解放"""
        self._is_seeking = False
        if self._duration_ms > 0:
            position_ms = int((self.seek_slider.value() / 1000.0) * self._duration_ms)
            self.player.setPosition(position_ms)
    
    def _on_slider_moved(self, value: int):
        """スライダー移動"""
        if self._duration_ms > 0:
            position_ms = int((value / 1000.0) * self._duration_ms)
            self._update_time_label(position_ms)
    
    def _update_time_label(self, position_ms: int):
        """時間表示を更新"""
        current = self._format_time(position_ms)
        total = self._format_time(self._duration_ms)
        self.time_label.setText(f"{current} / {total}")
    
    def _format_time(self, ms: int) -> str:
        """ミリ秒を MM:SS 形式に変換"""
        total_sec = ms // 1000
        m, s = divmod(total_sec, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
    
    def _on_error(self, error, error_string):
        """エラー発生"""
        print(f"Player error: {error} - {error_string}")
    
    def cleanup(self):
        """クリーンアップ"""
        self.player.stop()
        self.player.setSource(QUrl())
