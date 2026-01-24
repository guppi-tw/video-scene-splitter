"""
単色フレーム（ブランク画面）検出

VHSテープの未録画部分で出る青・グレー・白などの単色画面を検出する
"""
import cv2
import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class BlankFrame:
    """ブランクフレーム情報"""
    frame_num: int
    timestamp: float  # 秒
    color_type: str  # 'blue', 'gray', 'white', 'black', 'solid'
    avg_color: Tuple[int, int, int]  # BGR


class BlankDetector:
    """単色フレーム検出器"""
    
    # VHSでよく見られる単色画面の色範囲（HSV）
    # 青画面: H=100-130, S=100-255, V=50-255
    # グレー: S<30, V=50-200
    # 白: S<30, V>200
    # 黒: V<30
    
    def __init__(
        self,
        variance_threshold: float = 500.0,  # 色の分散閾値（小さいほど単色判定が厳しい）
        min_duration_frames: int = 5,  # 最小継続フレーム数
        sample_interval: int = 1,  # サンプリング間隔（フレーム）
    ):
        self.variance_threshold = variance_threshold
        self.min_duration_frames = min_duration_frames
        self.sample_interval = sample_interval
    
    def is_solid_color(self, frame: np.ndarray) -> Tuple[bool, str, Tuple[int, int, int]]:
        """
        フレームが単色かどうかを判定
        
        Returns:
            (is_solid, color_type, avg_color_bgr)
        """
        if frame is None or frame.size == 0:
            return False, '', (0, 0, 0)
        
        # フレームをリサイズして高速化（判定には十分）
        small = cv2.resize(frame, (160, 90))
        
        # 各チャンネルの分散を計算
        b, g, r = cv2.split(small)
        variance = np.var(b) + np.var(g) + np.var(r)
        
        if variance > self.variance_threshold:
            return False, '', (0, 0, 0)
        
        # 単色と判定された場合、色の種類を特定
        avg_color = (int(np.mean(b)), int(np.mean(g)), int(np.mean(r)))
        color_type = self._classify_color(avg_color)
        
        return True, color_type, avg_color
    
    def _classify_color(self, bgr: Tuple[int, int, int]) -> str:
        """BGR値から色の種類を分類"""
        b, g, r = bgr
        
        # HSVに変換
        pixel = np.uint8([[bgr]])
        hsv = cv2.cvtColor(pixel, cv2.COLOR_BGR2HSV)[0][0]
        h, s, v = int(hsv[0]), int(hsv[1]), int(hsv[2])
        
        # 黒（明度が低い）
        if v < 30:
            return 'black'
        
        # 白（彩度が低く明度が高い）
        if s < 30 and v > 200:
            return 'white'
        
        # グレー（彩度が低い）
        if s < 30:
            return 'gray'
        
        # 青（VHSの未録画部分でよく見られる）
        # H: 100-130 (OpenCVのHは0-180)
        if 90 <= h <= 130 and s > 50:
            return 'blue'
        
        # その他の単色
        return 'solid'
    
    def detect_blank_regions(
        self,
        video_path: str,
        fps: float = None,
        progress_callback=None
    ) -> List[Tuple[float, float, str]]:
        """
        動画内のブランク領域を検出
        
        Args:
            video_path: 動画ファイルパス
            fps: フレームレート（Noneの場合は動画から取得）
            progress_callback: 進捗コールバック(current_frame, total_frames)
            
        Returns:
            [(start_time, end_time, color_type), ...]
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError(f"動画を開けません: {video_path}")
        
        if fps is None:
            fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        blank_regions = []
        current_blank_start = None
        current_blank_type = None
        consecutive_blank = 0
        
        frame_num = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # サンプリング間隔でスキップ
            if frame_num % self.sample_interval != 0:
                frame_num += 1
                continue
            
            is_solid, color_type, _ = self.is_solid_color(frame)
            
            if is_solid:
                if current_blank_start is None:
                    current_blank_start = frame_num
                    current_blank_type = color_type
                    consecutive_blank = 1
                elif color_type == current_blank_type:
                    consecutive_blank += 1
                else:
                    # 色が変わった場合、前のブランク領域を確定
                    if consecutive_blank >= self.min_duration_frames:
                        start_time = current_blank_start / fps
                        end_time = frame_num / fps
                        blank_regions.append((start_time, end_time, current_blank_type))
                    current_blank_start = frame_num
                    current_blank_type = color_type
                    consecutive_blank = 1
            else:
                # 単色でなくなった場合
                if current_blank_start is not None and consecutive_blank >= self.min_duration_frames:
                    start_time = current_blank_start / fps
                    end_time = frame_num / fps
                    blank_regions.append((start_time, end_time, current_blank_type))
                current_blank_start = None
                current_blank_type = None
                consecutive_blank = 0
            
            if progress_callback and frame_num % 100 == 0:
                progress_callback(frame_num, total_frames)
            
            frame_num += 1
        
        # 最後のブランク領域を確定
        if current_blank_start is not None and consecutive_blank >= self.min_duration_frames:
            start_time = current_blank_start / fps
            end_time = frame_num / fps
            blank_regions.append((start_time, end_time, current_blank_type))
        
        cap.release()
        return blank_regions
    
    def merge_with_scenes(
        self,
        scenes: List[Tuple[float, float]],
        blank_regions: List[Tuple[float, float, str]],
        min_scene_duration: float = 2.0
    ) -> List[Tuple[float, float]]:
        """
        シーンリストとブランク領域をマージして新しいシーンリストを生成
        
        ブランク領域でシーンを分割し、ブランク部分自体は除外する
        
        Args:
            scenes: [(start, end), ...] 既存のシーンリスト
            blank_regions: [(start, end, color_type), ...] ブランク領域
            min_scene_duration: 最小シーン長（秒）
            
        Returns:
            新しいシーンリスト [(start, end), ...]
        """
        if not blank_regions:
            return scenes
        
        # すべての境界点を収集
        boundaries = set()
        for start, end in scenes:
            boundaries.add(start)
            boundaries.add(end)
        
        # ブランク領域の境界を追加
        for start, end, _ in blank_regions:
            boundaries.add(start)
            boundaries.add(end)
        
        boundaries = sorted(boundaries)
        
        # ブランク領域をセットに変換（高速な判定用）
        def is_in_blank(time: float) -> bool:
            for start, end, _ in blank_regions:
                if start <= time < end:
                    return True
            return False
        
        # 新しいシーンリストを生成
        new_scenes = []
        i = 0
        while i < len(boundaries) - 1:
            start = boundaries[i]
            end = boundaries[i + 1]
            
            # ブランク領域内のセグメントはスキップ
            mid = (start + end) / 2
            if is_in_blank(mid):
                i += 1
                continue
            
            # 短すぎるシーンは前のシーンに結合
            duration = end - start
            if duration < min_scene_duration and new_scenes:
                # 前のシーンを延長
                prev_start, _ = new_scenes[-1]
                new_scenes[-1] = (prev_start, end)
            else:
                new_scenes.append((start, end))
            
            i += 1
        
        return new_scenes


def detect_and_split_by_blanks(
    video_path: str,
    existing_scenes: List[Tuple[float, float]],
    variance_threshold: float = 500.0,
    min_blank_duration: float = 0.2,  # 最小ブランク継続時間（秒）
    min_scene_duration: float = 2.0,
    fps: float = None,
    progress_callback=None
) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float, str]]]:
    """
    ブランク検出を行い、既存のシーンリストを更新する便利関数
    
    Args:
        video_path: 動画ファイルパス
        existing_scenes: 既存のシーンリスト
        variance_threshold: 単色判定の分散閾値
        min_blank_duration: 最小ブランク継続時間（秒）
        min_scene_duration: 最小シーン長（秒）
        fps: フレームレート
        progress_callback: 進捗コールバック
        
    Returns:
        (new_scenes, blank_regions)
    """
    # FPSを取得
    if fps is None:
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()
    
    min_duration_frames = max(1, int(min_blank_duration * fps))
    
    detector = BlankDetector(
        variance_threshold=variance_threshold,
        min_duration_frames=min_duration_frames,
        sample_interval=2  # 2フレームごとにサンプリング（高速化）
    )
    
    blank_regions = detector.detect_blank_regions(
        video_path,
        fps=fps,
        progress_callback=progress_callback
    )
    
    new_scenes = detector.merge_with_scenes(
        existing_scenes,
        blank_regions,
        min_scene_duration=min_scene_duration
    )
    
    return new_scenes, blank_regions
