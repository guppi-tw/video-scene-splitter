"""
レビューUI - サムネイル一覧とkeep/drop切り替え、シーン別メタデータ入力
"""
import subprocess
import platform
from pathlib import Path
from datetime import date

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QScrollArea, QFrame,
    QLineEdit, QDateEdit, QGroupBox, QCheckBox,
    QFileDialog, QMessageBox, QSizePolicy, QToolButton
)
from PySide6.QtCore import Signal, Qt, QDate
from PySide6.QtGui import QPixmap

from app.core import VideoJob, Scene, JobStatus


class SceneThumbnail(QFrame):
    """シーンサムネイルウィジェット（メタデータ入力付き）"""
    
    clicked = Signal(object)  # Scene
    keep_changed = Signal(object, bool)  # Scene, keep
    metadata_changed = Signal(object)  # Scene
    
    def __init__(self, scene: Scene, job: 'VideoJob'):
        super().__init__()
        self.scene = scene
        self.job = job
        self._setup_ui()
    
    def _setup_ui(self):
        self.setFrameStyle(QFrame.Box | QFrame.Raised)
        self.setLineWidth(2)
        self.setFixedWidth(220)
        self.setMinimumHeight(280)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(3)
        
        # サムネイル画像
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(200, 120)
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
        
        # イベント名入力
        name_layout = QHBoxLayout()
        name_layout.setSpacing(2)
        self.event_name_edit = QLineEdit()
        self.event_name_edit.setPlaceholderText("イベント名（空=引継ぎ）")
        self.event_name_edit.setMaximumHeight(24)
        self.event_name_edit.textChanged.connect(self._on_name_changed)
        name_layout.addWidget(self.event_name_edit)
        layout.addLayout(name_layout)
        
        # 日付入力
        date_layout = QHBoxLayout()
        date_layout.setSpacing(2)
        
        self.date_check = QCheckBox()
        self.date_check.setToolTip("日付を設定（チェックなしで前のシーンから引継ぎ）")
        self.date_check.stateChanged.connect(self._on_date_check_changed)
        date_layout.addWidget(self.date_check)
        
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setMaximumHeight(24)
        self.date_edit.setEnabled(False)
        self.date_edit.dateChanged.connect(self._on_date_changed)
        date_layout.addWidget(self.date_edit)
        
        layout.addLayout(date_layout)
        
        # 有効なメタデータ表示（引き継ぎ元を表示）
        self.effective_label = QLabel()
        self.effective_label.setStyleSheet("font-size: 9px; color: #888; font-style: italic;")
        self.effective_label.setWordWrap(True)
        layout.addWidget(self.effective_label)
        
        # Keep/Dropチェックボックス
        self.keep_check = QCheckBox("Keep")
        self.keep_check.setChecked(self.scene.keep)
        self.keep_check.stateChanged.connect(self._on_keep_changed)
        layout.addWidget(self.keep_check, alignment=Qt.AlignCenter)
        
        # 初期値を設定
        self._load_scene_metadata()
        self._update_style()
    
    def _format_time(self, seconds: float) -> str:
        """秒を MM:SS 形式に変換"""
        m, s = divmod(int(seconds), 60)
        return f"{m:02d}:{s:02d}"
    
    def _load_scene_metadata(self):
        """シーンのメタデータをUIに反映"""
        # イベント名
        if self.scene.event_name is not None:
            self.event_name_edit.setText(self.scene.event_name)
        else:
            self.event_name_edit.clear()
        
        # 日付
        if self.scene.event_date is not None:
            self.date_check.setChecked(True)
            self.date_edit.setEnabled(True)
            d = self.scene.event_date
            self.date_edit.setDate(QDate(d.year, d.month, d.day))
        else:
            self.date_check.setChecked(False)
            self.date_edit.setEnabled(False)
        
        self._update_effective_label()
    
    def _update_effective_label(self):
        """有効なメタデータ（引き継ぎを考慮）を表示"""
        name, d = self.job.get_scene_metadata(self.scene.index)
        
        parts = []
        if name:
            # 自分で設定したか引き継ぎか
            if self.scene.event_name is not None:
                parts.append(f"📝 {name}")
            else:
                parts.append(f"↩ {name}")
        
        if d:
            date_str = d.strftime("%Y-%m-%d")
            if self.scene.event_date is not None:
                parts.append(f"📅 {date_str}")
            else:
                parts.append(f"↩ {date_str}")
        
        if parts:
            self.effective_label.setText(" | ".join(parts))
        else:
            self.effective_label.setText("（未設定）")
    
    def _on_name_changed(self, text: str):
        """イベント名が変更された"""
        if text.strip():
            self.scene.event_name = text.strip()
        else:
            self.scene.event_name = None  # 空欄は引き継ぎ
        self._update_effective_label()
        self.metadata_changed.emit(self.scene)
    
    def _on_date_check_changed(self, state):
        """日付チェックボックスが変更された"""
        enabled = state == Qt.Checked
        self.date_edit.setEnabled(enabled)
        
        if enabled:
            qdate = self.date_edit.date()
            self.scene.event_date = date(qdate.year(), qdate.month(), qdate.day())
        else:
            self.scene.event_date = None  # 引き継ぎ
        
        self._update_effective_label()
        self.metadata_changed.emit(self.scene)
    
    def _on_date_changed(self, qdate: QDate):
        """日付が変更された"""
        if self.date_check.isChecked():
            self.scene.event_date = date(qdate.year(), qdate.month(), qdate.day())
            self._update_effective_label()
            self.metadata_changed.emit(self.scene)
    
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
            scaled = pixmap.scaled(200, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.thumb_label.setPixmap(scaled)
    
    def refresh_effective_label(self):
        """有効なメタデータ表示を更新（外部から呼び出し用）"""
        self._update_effective_label()
    
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
        
        # デフォルトメタデータ入力
        meta_group = QGroupBox("デフォルト設定（シーンに設定がない場合に使用）")
        meta_layout = QHBoxLayout(meta_group)
        
        meta_layout.addWidget(QLabel("イベント名:"))
        self.default_name_edit = QLineEdit()
        self.default_name_edit.setPlaceholderText("例: 運動会2024")
        self.default_name_edit.textChanged.connect(self._on_default_meta_changed)
        meta_layout.addWidget(self.default_name_edit)
        
        meta_layout.addWidget(QLabel("日付:"))
        self.default_date_edit = QDateEdit()
        self.default_date_edit.setCalendarPopup(True)
        self.default_date_edit.setDate(QDate.currentDate())
        self.default_date_edit.dateChanged.connect(self._on_default_meta_changed)
        meta_layout.addWidget(self.default_date_edit)
        
        # 一括適用ボタン
        self.btn_apply_to_all = QPushButton("全シーンに適用")
        self.btn_apply_to_all.setToolTip("デフォルト値を全シーンの先頭に設定")
        self.btn_apply_to_all.clicked.connect(self._on_apply_default_to_all)
        meta_layout.addWidget(self.btn_apply_to_all)
        
        layout.addWidget(meta_group)
        
        # 説明ラベル
        help_label = QLabel(
            "💡 各シーンで名前・日付を入力すると、以降のシーンに引き継がれます。"
            "空欄のシーンは前のシーンの値を使用します。"
        )
        help_label.setStyleSheet("color: #666; font-size: 11px; padding: 5px;")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        
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
        
        # デフォルトメタデータを反映
        self.default_name_edit.setText(job.default_event_name)
        if job.default_event_date:
            d = job.default_event_date
            self.default_date_edit.setDate(QDate(d.year, d.month, d.day))
        
        # シーン一覧をクリア
        for widget in self.scene_widgets:
            widget.deleteLater()
        self.scene_widgets.clear()
        
        # シーンウィジェットを作成
        cols = 4
        for i, scene in enumerate(job.scenes):
            widget = SceneThumbnail(scene, job)
            widget.clicked.connect(self._on_scene_clicked)
            widget.keep_changed.connect(self._on_scene_keep_changed)
            widget.metadata_changed.connect(self._on_scene_metadata_changed)
            
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
    
    def _on_default_meta_changed(self):
        """デフォルトメタデータが変更された"""
        if self.current_job:
            self.current_job.default_event_name = self.default_name_edit.text()
            qdate = self.default_date_edit.date()
            self.current_job.default_event_date = date(qdate.year(), qdate.month(), qdate.day())
            
            # 全シーンの有効ラベルを更新
            self._refresh_all_effective_labels()
    
    def _on_apply_default_to_all(self):
        """デフォルト値を最初のシーンに適用"""
        if not self.current_job or not self.current_job.scenes:
            return
        
        # 最初のシーンにデフォルト値を設定
        first_scene = self.current_job.scenes[0]
        first_scene.event_name = self.default_name_edit.text() or None
        
        qdate = self.default_date_edit.date()
        first_scene.event_date = date(qdate.year(), qdate.month(), qdate.day())
        
        # UIを更新
        if self.scene_widgets:
            self.scene_widgets[0]._load_scene_metadata()
        
        self._refresh_all_effective_labels()
        
        QMessageBox.information(
            self,
            "適用完了",
            "デフォルト値を最初のシーンに設定しました。\n"
            "以降のシーンは自動的に引き継がれます。"
        )
    
    def _on_scene_metadata_changed(self, scene: Scene):
        """シーンのメタデータが変更された"""
        # このシーン以降の有効ラベルを更新
        self._refresh_all_effective_labels()
    
    def _refresh_all_effective_labels(self):
        """全シーンの有効メタデータ表示を更新"""
        for widget in self.scene_widgets:
            widget.refresh_effective_label()
    
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
                subprocess.Popen(["open", str(video_path)])
            elif system == "Windows":
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
        
        # keepされているシーンがあるか確認
        kept_scenes = self.current_job.kept_scenes
        if not kept_scenes:
            QMessageBox.warning(
                self,
                "書き出しエラー",
                "書き出すシーンがありません。\n少なくとも1つのシーンを「Keep」にしてください。"
            )
            return
        
        # メタデータのサマリーを表示
        groups = self.current_job.get_scenes_grouped_by_metadata()
        summary_lines = []
        for name, d, scenes in groups:
            date_str = d.strftime("%Y-%m-%d") if d else "日付なし"
            name_str = name or "名前なし"
            scene_indices = [s.index for s in scenes]
            if len(scene_indices) > 3:
                indices_str = f"{scene_indices[0]}-{scene_indices[-1]}"
            else:
                indices_str = ", ".join(map(str, scene_indices))
            summary_lines.append(f"・{date_str} {name_str}: シーン {indices_str}")
        
        summary = "\n".join(summary_lines)
        
        reply = QMessageBox.question(
            self,
            "書き出し確認",
            f"以下の内容で書き出します:\n\n{summary}\n\n"
            f"合計 {len(kept_scenes)} シーン\n\n"
            "続行しますか？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # 出力先を選択
        output_dir = QFileDialog.getExistingDirectory(self, "出力先フォルダを選択")
        if output_dir:
            self.export_requested.emit(self.current_job, Path(output_dir))
