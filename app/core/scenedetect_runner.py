"""
PySceneDetectによるシーン検知
"""
import csv
from pathlib import Path
from typing import Callable, Optional

from scenedetect import detect, ContentDetector, open_video
from scenedetect.scene_manager import SceneManager

from .jobs import Scene


class SceneDetectRunner:
    """シーン検知を実行するクラス"""
    
    def __init__(self, threshold: float = 27.0, min_scene_len: int = 15):
        """
        Args:
            threshold: コンテンツ検出の閾値（デフォルト27.0）
            min_scene_len: 最小シーン長（フレーム数）
        """
        self.threshold = threshold
        self.min_scene_len = min_scene_len
    
    def detect_scenes(
        self,
        video_path: Path,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> list[Scene]:
        """
        動画からシーンを検出
        
        Args:
            video_path: 動画ファイルパス
            progress_callback: 進捗コールバック
            
        Returns:
            検出されたシーンのリスト
        """
        if progress_callback:
            progress_callback(f"シーン検知開始: {video_path.name}")
        
        try:
            # 動画を開く
            video = open_video(str(video_path))
            
            # シーンマネージャーを作成
            scene_manager = SceneManager()
            scene_manager.add_detector(
                ContentDetector(
                    threshold=self.threshold,
                    min_scene_len=self.min_scene_len
                )
            )
            
            if progress_callback:
                progress_callback("動画を解析中...")
            
            # シーン検出を実行
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
            
            return scenes
            
        except Exception as e:
            if progress_callback:
                progress_callback(f"エラー: {str(e)}")
            raise
    
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
