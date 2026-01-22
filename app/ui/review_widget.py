"""
レビューUI - サムネイル一覧とkeep/drop切り替え
"""
import subprocess
import platform
from pathlib import Path
from datetime import date

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QScrollArea, QFrame,
    QLineEdit, QDateEdit, QGroupBox, QCheckBox,
    QFileDialog, QMessageBox, QSizePolicy
)
from PySide6.QtCore import Signal, Qt, QDate
from PySide6.QtGui import QPixmap

from ..core import VideoJob, Scene, JobStatus


class SceneThumbnail(QFrame):
    """シーンサムネイルウィジェット"""
    
    clicked = Signal(object)  # Scene
    keep_changed = Signal(object, bool)  # Scene, keep
    
    def __init__(self, scene: Scene):
        super().__init__()
        self.scene = scene
        self._setup_ui()
    
    def _setup_ui(self):
        self.setFrameStyle(QFrame.Box | QFrame.Raised)
        self.setLineWidth(2)
        self.setFixedSize(200, 200)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # サムネイル画像
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(180, 120)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet("background-color: #333;")
        layout.addWidget(self.thumb_label)
        
        # シーン情報
        info_text = f"#{self.scene.index} | {self.scene.duration:.1f}s"
        self.info_label = QLabel(info_text)
        self.info_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.info_label)
        
        # 時間情報
        time_text = f"{self._format_time(self.scene.start_time)} - {self._format_time(self.scene.end_time)}"
        self.time_label = QLabel(time_text)
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setStyleSheet("font-size: 10px; color: #666;")
        layout.addWidget(self.time_label)
        
        # Keep/Dropチェックボックス
        self.keep_check = QCheckBox("Keep")
        self.keep_check.setChecked(self.scene.keep)
        self.keep_check.stateChanged.connect(self._on_keep_changed)
        layout.addWidget(self.keep_check, alignment=Qt.AlignCenter)
        
        self._update_style()
    
    def _format_time(self, seconds: float) -> str:
        """秒を MM:SS 形式に変換"""
        m, s = divmod(int(seconds), 60)
        return f"{m:02d}:{s:02d}"
    
    def _on_keep_changed(self, state):
        self.scene.keep = state == Qt.Checked
        self._update_style()
        self.keep_changed.emit(self.scene, self.scene.keep)
    
    def _update_style(self):
        if self.scene.keep:
            self.setStyleSheet("SceneThumbnail { background-color: #e8f5e9; }")
        else:
            self.setStyleSheet("SceneThumbnail { background-color: #ffebee; }")
    
    def set_thumbnail(self, path: Path):
        """サムネイル画像を設定"""
        if path and path.exists():
            pixmap = QPixmap(str(path))
            scaled = pixmap.scaled(180, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.thumb_label.setPixmap(scaled)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.scene)
        super().mousePressEvent(event)


class ReviewWidget(QWidget):
    """レビューUI"""
    
    export_requested = Signal(object, Path)  # VideoJob, output_dir
    
    def __init__(self):
        super().__init__()
        self.current_job: VideoJob = None
        self.scene_widgets: list[SceneThumbnail] = []
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # メタデータ入力
        meta_group = QGroupBox("動画情報")
        meta_layout = QHBoxLayout(meta_group)
        
        meta_layout.addWidget(QLabel("イベント名:"))
        self.event_name_edit = QLineEdit()
        self.event_name_edit.setPlaceholderText("例: 運動会2024")
        self.event_name_edit.textChanged.connect(self._on_meta_changed)
        meta_layout.addWidget(self.event_name_edit)
        
        meta_layout.addWidget(QLabel("日付:"))
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.dateChanged.connect(self._on_meta_changed)
        meta_layout.addWidget(self.date_edit)
        
        layout.addWidget(meta_group)
        
        # シーン一覧（スクロール可能）
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.scenes_container = QWidget()
        self.scenes_layout = QGridLayout(self.scenes_container)
        self.scenes_layout.setSpacing(10)
        self.scroll_area.setWidget(self.scenes_container)
        
        layout.addWidget(self.scroll_area, stretch=1)
        
        # 操作ボタン
        btn_layout = QHBoxLayout()
        
        self.btn_keep_all = QPushButton("全てKeep")
        self.btn_keep_all.clicked.connect(self._on_keep_all)
        btn_layout.addWidget(self.btn_keep_all)
        
        self.btn_drop_all = QPushButton("全てDrop")
        self.btn_drop_all.clicked.connect(self._on_drop_all)
        btn_layout.addWidget(self.btn_drop_all)
        
        btn_layout.addStretch()
        
        self.btn_preview = QPushButton("選択シーンをプレビュー")
        self.btn_preview.clicked.connect(self._on_preview)
        self.btn_preview.setEnabled(False)
        btn_layout.addWidget(self.btn_preview)
        
        self.btn_export = QPushButton("書き出し")
        self.btn_export.clicked.connect(self._on_export)
        self.btn_export.setEnabled(False)
        btn_layout.addWidget(self.btn_export)
        
        layout.addLayout(btn_layout)
        
        self.selected_scene: Scene = None
    
    def set_job(self, job: VideoJob):
        """ジョブを設定してUI更新"""
        self.current_job = job
        self.selected_scene = None
        
        # メタデータを反映
        self.event_name_edit.setText(job.event_name)
        if job.event_date:
            self.date_edit.setDate(QDate(job.event_date.year, job.event_date.month, job.event_date.day))
        
        # シーン一覧をクリア
        for widget in self.scene_widgets:
            widget.deleteLater()
        self.scene_widgets.clear()
        
        # シーンウィジェットを作成
        cols = 4
        for i, scene in enumerate(job.scenes):
            widget = SceneThumbnail(scene)
            widget.clicked.connect(self._on_scene_clicked)
            widget.keep_changed.connect(self._on_scene_keep_changed)
            
            if scene.thumbnail_path:
                widget.set_thumbnail(scene.thumbnail_path)
            
            row = i // cols
            col = i % cols
            self.scenes_layout.addWidget(widget, row, col)
            self.scene_widgets.append(widget)
        
        # ボタン状態更新
        self.btn_export.setEnabled(job.status == JobStatus.REVIEW)
        self.btn_preview.setEnabled(False)
    
    def update_thumbnail(self, scene_index: int, path: str):
        """サムネイルを更新"""
        for widget in self.scene_widgets:
            if widget.scene.index == scene_index:
                widget.set_thumbnail(Path(path))
                break
    
    def _on_meta_changed(self):
        if self.current_job:
            self.current_job.event_name = self.event_name_edit.text()
            qdate = self.date_edit.date()
            self.current_job.event_date = date(qdate.year(), qdate.month(), qdate.day())
    
    def _on_scene_clicked(self, scene: Scene):
        self.selected_scene = scene
        self.btn_preview.setEnabled(True)
        
        # 選択状態を視覚的に表示
        for widget in self.scene_widgets:
            if widget.scene == scene:
                widget.setLineWidth(3)
            else:
                widget.setLineWidth(2)
    
    def _on_scene_keep_changed(self, scene: Scene, keep: bool):
        pass  # 必要に応じて処理
    
    def _on_keep_all(self):
        for widget in self.scene_widgets:
            widget.keep_check.setChecked(True)
    
    def _on_drop_all(self):
        for widget in self.scene_widgets:
            widget.keep_check.setChecked(False)
    
    def _on_preview(self):
        """選択シーンをプレビュー"""
        if not self.selected_scene or not self.current_job:
            return
        
        video_path = self.current_job.source_path
        start_time = self.selected_scene.start_time
        
        # OS標準プレイヤーで開く
        system = platform.system()
        try:
            if system == "Darwin":  # macOS
                # QuickTime Playerで開く（時刻指定は難しいのでファイルを開くのみ）
                subprocess.Popen(["open", str(video_path)])
            elif system == "Windows":
                # Windows Media Playerで開く
                subprocess.Popen(["start", "", str(video_path)], shell=True)
            else:  # Linux
                subprocess.Popen(["xdg-open", str(video_path)])
            
            QMessageBox.information(
                self,
                "プレビュー",
                f"動画を開きました。\n開始位置: {self._format_time(start_time)}\n\n"
                f"※手動でシーク位置を調整してください。"
            )
        except Exception as e:
            QMessageBox.warning(self, "エラー", f"プレビューを開けませんでした: {e}")
    
    def _format_time(self, seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
    
    def _on_export(self):
        """書き出し開始"""
        if not self.current_job:
            return
        
        # 出力先を選択
        output_dir = QFileDialog.getExistingDirectory(self, "出力先フォルダを選択")
        if output_dir:
            self.export_requested.emit(self.current_job, Path(output_dir))
