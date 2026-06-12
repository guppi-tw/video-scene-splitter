"""
分割・書き出し処理
"""
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Optional, List

from app.core.jobs import VideoJob, Scene, Clip, group_clips_by_metadata
from app.core.ffmpeg_runner import FFmpegRunner


@dataclass
class ExportResult:
    """書き出し結果"""
    total: int = 0
    succeeded: int = 0
    cancelled: bool = False

    @property
    def all_succeeded(self) -> bool:
        return self.total > 0 and self.succeeded == self.total


class Exporter:
    """動画の分割・書き出しを行うクラス"""

    MAX_CLIP_DURATION = 595  # 9分55秒
    MIN_REMAINDER_DURATION = 30  # 30秒未満の余りは最後の2クリップで均等に再配分

    def __init__(self, ffmpeg_runner: FFmpegRunner, auto_split: bool = True):
        self.ffmpeg = ffmpeg_runner
        self.auto_split = auto_split

    def calculate_clips(self, job: VideoJob) -> list[Clip]:
        """
        keepシーンからクリップを計算
        595秒超のシーンは分割（どのクリップも595秒を超えない）
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

        return clips

    def _split_scene_to_clips(
        self,
        scene: Scene,
        start_index: int,
        event_name: str,
        event_date: Optional[date],
        is_sensitive: bool = False
    ) -> list[Clip]:
        """シーンを595秒単位で分割（auto_split=Falseの場合は分割しない）

        最後の断片が MIN_REMAINDER_DURATION 未満になる場合は、
        最後の2クリップを均等長に再配分する。アップロード先の10分制限を
        守るため、どのクリップも MAX_CLIP_DURATION を超えない。
        """
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

        # 分割位置（各クリップの開始時刻）を計算
        starts = [scene.start_time]
        while scene.end_time - starts[-1] > self.MAX_CLIP_DURATION:
            starts.append(starts[-1] + self.MAX_CLIP_DURATION)

        if len(starts) >= 2 and scene.end_time - starts[-1] < self.MIN_REMAINDER_DURATION:
            # 最後の余りが短すぎる場合は、最後の2クリップを均等に再配分
            starts[-1] = starts[-2] + (scene.end_time - starts[-2]) / 2

        clips = []
        for i, start in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else scene.end_time
            clips.append(Clip(
                index=start_index + i,
                start_time=start,
                end_time=end,
                source_scene_indices=[scene.index],
                event_name=event_name,
                event_date=event_date,
                is_sensitive=is_sensitive,
                filename_override=self._part_filename_override(scene, i, len(starts))
            ))
        return clips

    @staticmethod
    def _part_filename_override(scene: Scene, part_index: int, part_count: int) -> Optional[str]:
        """分割後クリップに引き継ぐファイル名指定を返す（複数分割時は連番を付与）"""
        if not scene.filename_override:
            return None
        if part_count == 1:
            return scene.filename_override
        base = scene.filename_override
        if base.endswith('.mp4'):
            base = base[:-4]
        return f"{base}_{part_index + 1:03d}"

    @staticmethod
    def _resolve_unique_path(path: Path) -> Path:
        """既存ファイルを上書きしないよう、空いているファイル名を返す"""
        if not path.exists():
            return path
        counter = 1
        while True:
            candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    def export(
        self,
        job: VideoJob,
        output_base_dir: Path,
        progress_callback: Optional[Callable[[str], None]] = None,
        clip_progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_callback: Optional[Callable[[], bool]] = None
    ) -> ExportResult:
        """
        ジョブの書き出しを実行

        Args:
            job: 処理対象のジョブ
            output_base_dir: 出力ベースディレクトリ
            progress_callback: 進捗メッセージコールバック
            clip_progress_callback: クリップ進捗コールバック (current, total)
            cancel_callback: キャンセル判定コールバック（Trueで中断）

        Returns:
            書き出し結果
        """
        def notify(message: str):
            if progress_callback:
                progress_callback(message)

        def cancelled() -> bool:
            return cancel_callback() if cancel_callback else False

        # クリップを計算
        clips = self.calculate_clips(job)
        result = ExportResult(total=len(clips))
        if not clips:
            notify("書き出し対象のシーンがありません")
            return result

        job.clips = clips

        # メタデータでグループ化して出力
        # 同じメタデータのクリップは同じフォルダに出力
        clips_by_metadata = group_clips_by_metadata(clips)

        # 同一フォルダに出力されるクリップ間で連番が重複しないよう振り直す
        for group_clips in clips_by_metadata.values():
            for i, clip in enumerate(group_clips, start=1):
                clip.index = i

        current_clip_num = 0

        for (event_name, event_date, is_sensitive), group_clips in clips_by_metadata.items():
            if cancelled():
                result.cancelled = True
                return result

            # 出力ディレクトリを作成
            output_dir = job.get_output_dir(
                output_base_dir, event_name, event_date, is_sensitive
            )
            output_dir.mkdir(parents=True, exist_ok=True)

            notify(f"出力先: {output_dir}")

            # グループ内のクリップを書き出し
            for clip in group_clips:
                if cancelled():
                    result.cancelled = True
                    return result

                current_clip_num += 1
                if clip_progress_callback:
                    clip_progress_callback(current_clip_num, result.total)
                notify(f"書き出し中: {current_clip_num}/{result.total}")

                filename = job.get_clip_filename(clip)
                # 既存ファイル（過去の書き出しや別ジョブの出力）を上書きしない
                output_path = self._resolve_unique_path(output_dir / filename)
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
                    result.succeeded += 1
                else:
                    notify(f"警告: クリップ {clip.index} の書き出しに失敗")

        notify(f"書き出し完了: {result.succeeded}/{result.total} クリップ")
        return result
