"""
PySceneDetectによるシーン検知
"""
import csv
from pathlib import Path
from typing import Callable, Optional, List, Tuple
from dataclasses import dataclass

from scenedetect import open_video, ContentDetector, SceneManager

from app.core.jobs import Scene
from app.core.blank_detector import BlankDetector


@dataclass
class SceneDetectConfig:
    """シーン検知の設定"""
    threshold: float = 27.0  # コンテンツ検出の閾値（高いほど鈍感）
    min_scene_len_sec: float = 2.0  # 最小シーン長（秒）
    
    # ブランク検出設定
    detect_blanks: bool = True  # ブランク（単色画面）検出を有効にする
    blank_variance_threshold: float = 500.0  # 単色判定の分散閾値
    min_blank_duration: float = 0.2  # 最小ブランク継続時間（秒）
    
    @property
    def min_scene_len_frames(self) -> int:
        """最小シーン長をフレーム数に変換（30fps想定）"""
        return int(self.min_scene_len_sec * 30)


class SceneDetectRunner:
    """シーン検知を実行するクラス"""
    
    DEFAULT_THRESHOLD = 27.0
    DEFAULT_MIN_SCENE_LEN_SEC = 2.0
    
    def __init__(
        self,
        threshold: float = DEFAULT_THRESHOLD,
        min_scene_len_sec: float = DEFAULT_MIN_SCENE_LEN_SEC,
        detect_blanks: bool = True,
        blank_variance_threshold: float = 500.0,
        min_blank_duration: float = 0.2
    ):
        """
        Args:
            threshold: コンテンツ検出の閾値（デフォルト27.0、高いほど鈍感）
            min_scene_len_sec: 最小シーン長（秒、デフォルト2.0秒）
            detect_blanks: ブランク（単色画面）検出を有効にする
            blank_variance_threshold: 単色判定の分散閾値
            min_blank_duration: 最小ブランク継続時間（秒）
        """
        self.config = SceneDetectConfig(
            threshold=threshold,
            min_scene_len_sec=min_scene_len_sec,
            detect_blanks=detect_blanks,
            blank_variance_threshold=blank_variance_threshold,
            min_blank_duration=min_blank_duration
        )
        self.detected_blanks: List[Tuple[float, float, str]] = []  # 検出されたブランク領域
    
    def detect_scenes(
        self,
        video_path: Path,
        progress_callback: Optional[Callable[[str], None]] = None,
        frame_progress_callback: Optional[Callable[[int, int, float], None]] = None
    ) -> list[Scene]:
        """
        動画からシーンを検出
        
        Args:
            video_path: 動画ファイルパス
            progress_callback: 進捗メッセージコールバック (message)
            frame_progress_callback: フレーム進捗コールバック (current_frame, total_frames, percent)
            
        Returns:
            検出されたシーンのリスト
        """
        if progress_callback:
            progress_callback(f"シーン検知開始: {video_path.name}")
            progress_callback(f"設定: 閾値={self.config.threshold}, 最小シーン長={self.config.min_scene_len_sec}秒")
            if self.config.detect_blanks:
                progress_callback("ブランク（単色画面）検出: 有効")
        
        try:
            # 動画を開く
            video = open_video(str(video_path))
            total_frames = video.duration.get_frames()
            fps = video.frame_rate
            duration_sec = video.duration.get_seconds()
            
            if progress_callback:
                progress_callback(f"動画情報: {total_frames}フレーム, {duration_sec:.1f}秒, {fps:.2f}fps")
            
            # 実際のfpsに基づいて最小シーン長を計算
            min_scene_len_frames = int(self.config.min_scene_len_sec * fps)
            
            # シーンマネージャーを作成
            scene_manager = SceneManager()
            scene_manager.add_detector(
                ContentDetector(
                    threshold=self.config.threshold,
                    min_scene_len=min_scene_len_frames
                )
            )
            
            if progress_callback:
                progress_callback("動画を解析中（シーン検知）...")
            
            # カスタム進捗コールバック付きでシーン検出を実行
            if frame_progress_callback:
                scene_manager.detect_scenes(
                    video,
                    show_progress=False,
                    callback=lambda frame_img, frame_num: self._on_frame_processed(
                        frame_num, total_frames, frame_progress_callback
                    )
                )
            else:
                scene_manager.detect_scenes(video, show_progress=False)
            
            # 結果を取得
            scene_list = scene_manager.get_scene_list()
            
            if progress_callback:
                progress_callback(f"シーン検知完了: {len(scene_list)}シーン")
            
            # シーンリストを (start, end) のタプルリストに変換
            scene_tuples = [(start.get_seconds(), end.get_seconds()) for start, end in scene_list]
            
            # シーンが検出されなかった場合、動画全体を1シーンとして扱う
            if not scene_tuples:
                scene_tuples = [(0.0, duration_sec)]
                if progress_callback:
                    progress_callback("シーン境界なし: 動画全体を1シーンとして処理")
            
            # ブランク検出を実行
            if self.config.detect_blanks:
                scene_tuples = self._apply_blank_detection(
                    str(video_path),
                    scene_tuples,
                    fps,
                    progress_callback,
                    frame_progress_callback,
                    total_frames
                )
            
            # Sceneオブジェクトに変換
            scenes = []
            for i, (start, end) in enumerate(scene_tuples):
                scene = Scene(
                    index=i + 1,
                    start_time=start,
                    end_time=end
                )
                scenes.append(scene)
            
            # シーン統計を出力
            if progress_callback and scenes:
                durations = [s.duration for s in scenes]
                avg_duration = sum(durations) / len(durations)
                min_duration = min(durations)
                max_duration = max(durations)
                progress_callback(
                    f"最終シーン数: {len(scenes)}, "
                    f"平均{avg_duration:.1f}秒, 最短{min_duration:.1f}秒, 最長{max_duration:.1f}秒"
                )
            
            return scenes
            
        except Exception as e:
            if progress_callback:
                progress_callback(f"エラー: {str(e)}")
            raise
    
    def _apply_blank_detection(
        self,
        video_path: str,
        scene_tuples: List[Tuple[float, float]],
        fps: float,
        progress_callback: Optional[Callable[[str], None]],
        frame_progress_callback: Optional[Callable[[int, int, float], None]],
        total_frames: int
    ) -> List[Tuple[float, float]]:
        """ブランク検出を適用してシーンを分割"""
        
        if progress_callback:
            progress_callback("ブランク（単色画面）を検出中...")
        
        min_duration_frames = max(1, int(self.config.min_blank_duration * fps))
        
        detector = BlankDetector(
            variance_threshold=self.config.blank_variance_threshold,
            min_duration_frames=min_duration_frames,
            sample_interval=3  # 3フレームごとにサンプリング（高速化）
        )
        
        # ブランク領域を検出
        def blank_progress(current, total):
            if frame_progress_callback:
                percent = (current / total) * 100 if total > 0 else 0
                frame_progress_callback(current, total, percent)
        
        self.detected_blanks = detector.detect_blank_regions(
            video_path,
            fps=fps,
            progress_callback=blank_progress if frame_progress_callback else None
        )
        
        if progress_callback:
            if self.detected_blanks:
                progress_callback(f"ブランク領域検出: {len(self.detected_blanks)}箇所")
                # 検出されたブランクの種類をカウント
                color_counts = {}
                for _, _, color_type in self.detected_blanks:
                    color_counts[color_type] = color_counts.get(color_type, 0) + 1
                color_info = ", ".join([f"{k}:{v}" for k, v in color_counts.items()])
                progress_callback(f"  内訳: {color_info}")
            else:
                progress_callback("ブランク領域: なし")
        
        # ブランク領域でシーンを分割
        if self.detected_blanks:
            new_scenes = detector.merge_with_scenes(
                scene_tuples,
                self.detected_blanks,
                min_scene_duration=self.config.min_scene_len_sec
            )
            if progress_callback:
                progress_callback(f"ブランク除去後のシーン数: {len(new_scenes)}")
            return new_scenes
        
        return scene_tuples
    
    def _on_frame_processed(
        self,
        frame_num: int,
        total_frames: int,
        callback: Callable[[int, int, float], None]
    ):
        """フレーム処理時のコールバック"""
        # 100フレームごとに進捗を報告（頻繁すぎるとUIが重くなる）
        if frame_num % 100 == 0 or frame_num == total_frames - 1:
            percent = (frame_num / total_frames) * 100 if total_frames > 0 else 0
            callback(frame_num, total_frames, percent)
    
    def export_to_csv(self, scenes: list[Scene], output_path: Path) -> None:
        """シーン情報をCSVに出力"""
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Index', 'Start (s)', 'End (s)', 'Duration (s)', 'Keep'])
            for scene in scenes:
                writer.writerow([
                    scene.index,
                    f"{scene.start_time:.3f}",
                    f"{scene.end_time:.3f}",
                    f"{scene.duration:.3f}",
                    scene.keep
                ])
    
    def get_detected_blanks(self) -> List[Tuple[float, float, str]]:
        """検出されたブランク領域を取得"""
        return self.detected_blanks
