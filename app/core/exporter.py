"""
分割・書き出し処理
"""
from pathlib import Path
from typing import Callable, Optional

from app.core.jobs import VideoJob, Scene, Clip
from app.core.ffmpeg_runner import FFmpegRunner


class Exporter:
    """動画の分割・書き出しを行うクラス"""
    
    MAX_CLIP_DURATION = 595  # 9分55秒
    MIN_REMAINDER_DURATION = 30  # 30秒未満は前のクリップに吸収
    
    def __init__(self, ffmpeg_runner: FFmpegRunner):
        self.ffmpeg = ffmpeg_runner
    
    def calculate_clips(self, job: VideoJob) -> list[Clip]:
        """
        keepシーンからクリップを計算
        595秒超のシーンは分割、短い余りは前に吸収
        """
        clips = []
        clip_index = 1
        
        kept_scenes = job.kept_scenes
        if not kept_scenes:
            return clips
        
        for scene in kept_scenes:
            scene_clips = self._split_scene_to_clips(scene, clip_index)
            clips.extend(scene_clips)
            clip_index += len(scene_clips)
        
        # 短い余りを前のクリップに吸収
        clips = self._merge_short_remainders(clips)
        
        # インデックスを振り直し
        for i, clip in enumerate(clips):
            clip.index = i + 1
        
        return clips
    
    def _split_scene_to_clips(self, scene: Scene, start_index: int) -> list[Clip]:
        """シーンを595秒単位で分割"""
        clips = []
        current_start = scene.start_time
        current_index = start_index
        
        while current_start < scene.end_time:
            remaining = scene.end_time - current_start
            
            if remaining <= self.MAX_CLIP_DURATION:
                # 残りが最大長以下ならそのまま
                clip = Clip(
                    index=current_index,
                    start_time=current_start,
                    end_time=scene.end_time,
                    source_scene_indices=[scene.index]
                )
                clips.append(clip)
                break
            else:
                # 最大長で分割
                clip = Clip(
                    index=current_index,
                    start_time=current_start,
                    end_time=current_start + self.MAX_CLIP_DURATION,
                    source_scene_indices=[scene.index]
                )
                clips.append(clip)
                current_start += self.MAX_CLIP_DURATION
                current_index += 1
        
        return clips
    
    def _merge_short_remainders(self, clips: list[Clip]) -> list[Clip]:
        """短い余りを前のクリップに吸収"""
        if len(clips) <= 1:
            return clips
        
        merged = []
        i = 0
        
        while i < len(clips):
            current = clips[i]
            
            # 次のクリップがあり、現在のクリップが短すぎる場合
            if current.duration < self.MIN_REMAINDER_DURATION and merged:
                # 前のクリップに吸収（終了時刻を延長）
                prev = merged[-1]
                # 同じシーンからの分割の場合のみ吸収
                if prev.source_scene_indices == current.source_scene_indices:
                    prev.end_time = current.end_time
                    i += 1
                    continue
            
            merged.append(current)
            i += 1
        
        return merged
    
    def export(
        self,
        job: VideoJob,
        output_base_dir: Path,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> bool:
        """
        ジョブの書き出しを実行
        
        Args:
            job: 処理対象のジョブ
            output_base_dir: 出力ベースディレクトリ
            progress_callback: 進捗コールバック
            
        Returns:
            成功したかどうか
        """
        # クリップを計算
        clips = self.calculate_clips(job)
        if not clips:
            if progress_callback:
                progress_callback("書き出し対象のシーンがありません")
            return False
        
        job.clips = clips
        
        # 出力ディレクトリを作成
        folder_name = job.get_output_folder_name()
        output_dir = output_base_dir / folder_name
        output_dir.mkdir(parents=True, exist_ok=True)
        job.output_dir = output_dir
        
        if progress_callback:
            progress_callback(f"出力先: {output_dir}")
            progress_callback(f"クリップ数: {len(clips)}")
        
        # 各クリップを書き出し
        success_count = 0
        for i, clip in enumerate(clips):
            if progress_callback:
                progress_callback(f"書き出し中: {i + 1}/{len(clips)}")
            
            filename = job.get_clip_filename(clip)
            output_path = output_dir / filename
            clip.output_path = output_path
            
            success = self.ffmpeg.extract_clip(
                video_path=job.source_path,
                start_time=clip.start_time,
                end_time=clip.end_time,
                output_path=output_path,
                use_copy=True,
                progress_callback=progress_callback
            )
            
            if success:
                success_count += 1
            else:
                if progress_callback:
                    progress_callback(f"警告: クリップ {clip.index} の書き出しに失敗")
        
        if progress_callback:
            progress_callback(f"書き出し完了: {success_count}/{len(clips)} クリップ")
        
        return success_count > 0
