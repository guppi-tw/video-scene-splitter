"""
分割・書き出し処理
"""
from datetime import date
from pathlib import Path
from typing import Callable, Optional, List

from app.core.jobs import VideoJob, Scene, Clip, group_clips_by_metadata
from app.core.ffmpeg_runner import FFmpegRunner


class Exporter:
    """動画の分割・書き出しを行うクラス"""
    
    MAX_CLIP_DURATION = 595  # 9分55秒
    MIN_REMAINDER_DURATION = 30  # 30秒未満は前のクリップに吸収
    
    def __init__(self, ffmpeg_runner: FFmpegRunner, auto_split: bool = True):
        self.ffmpeg = ffmpeg_runner
        self.auto_split = auto_split
    
    def calculate_clips(self, job: VideoJob) -> list[Clip]:
        """
        keepシーンからクリップを計算
        595秒超のシーンは分割、短い余りは前に吸収
        シーンごとのメタデータを考慮してグループ化
        """
        all_clips = []
        
        # メタデータでグループ化されたシーンを取得
        groups = job.get_scenes_grouped_by_metadata()
        
        for event_name, event_date, is_sensitive, scenes in groups:
            # グループ内でクリップを生成
            group_clips = self._calculate_clips_for_group(
                scenes, event_name, event_date, is_sensitive
            )
            all_clips.extend(group_clips)
        
        return all_clips
    
    def _calculate_clips_for_group(
        self,
        scenes: List[Scene],
        event_name: str,
        event_date: Optional[date],
        is_sensitive: bool
    ) -> List[Clip]:
        """
        同じメタデータを持つシーングループからクリップを計算
        """
        clips = []
        clip_index = 1
        
        for scene in scenes:
            scene_clips = self._split_scene_to_clips(
                scene, clip_index, event_name, event_date, is_sensitive
            )
            clips.extend(scene_clips)
            clip_index += len(scene_clips)
        
        # 短い余りを前のクリップに吸収
        clips = self._merge_short_remainders(clips)
        
        # インデックスを振り直し
        for i, clip in enumerate(clips):
            clip.index = i + 1
        
        return clips
    
    def _split_scene_to_clips(
        self,
        scene: Scene,
        start_index: int,
        event_name: str,
        event_date: Optional[date],
        is_sensitive: bool = False
    ) -> list[Clip]:
        """シーンを595秒単位で分割（auto_split=Falseの場合は分割しない）"""
        if not self.auto_split:
            clip = Clip(
                index=start_index,
                start_time=scene.start_time,
                end_time=scene.end_time,
                source_scene_indices=[scene.index],
                event_name=event_name,
                event_date=event_date,
                is_sensitive=is_sensitive,
                filename_override=scene.filename_override
            )
            return [clip]

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
                    source_scene_indices=[scene.index],
                    event_name=event_name,
                    event_date=event_date,
                    is_sensitive=is_sensitive
                )
                clips.append(clip)
                break
            else:
                # 最大長で分割
                clip = Clip(
                    index=current_index,
                    start_time=current_start,
                    end_time=current_start + self.MAX_CLIP_DURATION,
                    source_scene_indices=[scene.index],
                    event_name=event_name,
                    event_date=event_date,
                    is_sensitive=is_sensitive
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
        
        # メタデータでグループ化して出力
        # 同じメタデータのクリップは同じフォルダに出力
        clips_by_metadata = group_clips_by_metadata(clips)
        
        total_clips = len(clips)
        success_count = 0
        current_clip_num = 0
        
        for (event_name, event_date, is_sensitive), group_clips in clips_by_metadata.items():
            # 出力ディレクトリを作成
            output_dir = job.get_output_dir(
                output_base_dir, event_name, event_date, is_sensitive
            )
            output_dir.mkdir(parents=True, exist_ok=True)
            
            if progress_callback:
                progress_callback(f"出力先: {output_dir}")
            
            # グループ内のクリップを書き出し
            for clip in group_clips:
                current_clip_num += 1
                
                if progress_callback:
                    progress_callback(f"書き出し中: {current_clip_num}/{total_clips}")
                
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
            progress_callback(f"書き出し完了: {success_count}/{total_clips} クリップ")
        
        return success_count > 0
