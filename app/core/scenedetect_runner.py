"""
PySceneDetectによるシーン検知
"""
import csv
from pathlib import Path
from typing import Callable, Optional
from dataclasses import dataclass

from scenedetect import open_video, ContentDetector, SceneManager

from .jobs import Scene


@dataclass
class SceneDetectConfig:
    """シーン検知の設定"""
    threshold: float = 27.0  # コンテンツ検出の閾値（高いほど鈍感）
    min_scene_len_sec: float = 2.0  # 最小シーン長（秒）
    
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
        min_scene_len_sec: float = DEFAULT_MIN_SCENE_LEN_SEC
    ):
        """
        Args:
            threshold: コンテンツ検出の閾値（デフォルト27.0、高いほど鈍感）
            min_scene_len_sec: 最小シーン長（秒、デフォルト2.0秒）
        """
        self.config = SceneDetectConfig(
            threshold=threshold,
            min_scene_len_sec=min_scene_len_sec
        )
    
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
        
        try:
            # 動画を開く
            video = open_video(str(video_path))
            total_frames = video.duration.get_frames()
            fps = video.frame_rate
            
            if progress_callback:
                duration_sec = video.duration.get_seconds()
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
                progress_callback("動画を解析中...")
            
            # カスタム進捗コールバック付きでシーン検出を実行
            if frame_progress_callback:
                # フレームごとの進捗を報告するためにdetect_scenesをカスタマイズ
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
                progress_callback(f"検出完了: {len(scene_list)}シーン")
            
            # Sceneオブジェクトに変換
            scenes = []
            for i, (start, end) in enumerate(scene_list):
                scene = Scene(
                    index=i + 1,
                    start_time=start.get_seconds(),
                    end_time=end.get_seconds()
                )
                scenes.append(scene)
            
            # シーンが検出されなかった場合、動画全体を1シーンとして扱う
            if not scenes:
                duration = video.duration.get_seconds()
                scenes.append(Scene(
                    index=1,
                    start_time=0.0,
                    end_time=duration
                ))
                if progress_callback:
                    progress_callback("シーン境界なし: 動画全体を1シーンとして処理")
            
            # シーン統計を出力
            if progress_callback and scenes:
                durations = [s.duration for s in scenes]
                avg_duration = sum(durations) / len(durations)
                min_duration = min(durations)
                max_duration = max(durations)
                progress_callback(
                    f"シーン長: 平均{avg_duration:.1f}秒, "
                    f"最短{min_duration:.1f}秒, 最長{max_duration:.1f}秒"
                )
            
            return scenes
            
        except Exception as e:
            if progress_callback:
                progress_callback(f"エラー: {str(e)}")
            raise
    
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
