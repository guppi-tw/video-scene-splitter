"""
ジョブ管理とデータモデル
"""
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, List, Tuple, Dict, TYPE_CHECKING
from datetime import date

if TYPE_CHECKING:
    from app.core.jobs import Clip

# 型エイリアス
MetadataKey = Tuple[str, Optional[date], bool]


class JobStatus(Enum):
    WAITING = "WAITING"
    PROCESSING = "PROCESSING"
    REVIEW = "REVIEW"
    DONE = "DONE"
    ERROR = "ERROR"


@dataclass
class Scene:
    """シーン情報"""
    index: int
    start_time: float  # 秒
    end_time: float    # 秒
    thumbnail_path: Optional[Path] = None
    keep: bool = True
    is_sensitive: bool = False
    
    # シーン別メタデータ（Noneの場合は前のシーンから引き継ぎ）
    event_name: Optional[str] = None  # イベント名（Noneで引き継ぎ）
    event_date: Optional[date] = None  # 日付（Noneで引き継ぎ）
    filename_override: Optional[str] = None  # ファイル名の直接指定
    
    @property
    def duration(self) -> float:
        return self.end_time - self.start_time
    
    def has_metadata(self) -> bool:
        """このシーンに独自のメタデータが設定されているか"""
        return self.event_name is not None or self.event_date is not None
    
    def __str__(self) -> str:
        return f"Scene {self.index}: {self.start_time:.2f}s - {self.end_time:.2f}s ({self.duration:.2f}s)"


@dataclass
class Clip:
    """書き出し用クリップ情報"""
    index: int
    start_time: float
    end_time: float
    source_scene_indices: list[int] = field(default_factory=list)
    event_name: str = ""  # このクリップのイベント名
    event_date: Optional[date] = None  # このクリップの日付
    is_sensitive: bool = False
    output_path: Optional[Path] = None
    filename_override: Optional[str] = None  # ファイル名の直接指定

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


def group_clips_by_metadata(
    clips: List[Clip]
) -> Dict[MetadataKey, List[Clip]]:
    """
    クリップをメタデータ（イベント名、日付、要注意フラグ）でグループ化

    Args:
        clips: グループ化するクリップのリスト

    Returns:
        {(event_name, event_date, is_sensitive): [clips]} の辞書
    """
    groups: Dict[MetadataKey, List[Clip]] = {}

    for clip in clips:
        key: MetadataKey = (clip.event_name or "", clip.event_date, clip.is_sensitive)
        if key not in groups:
            groups[key] = []
        groups[key].append(clip)

    return groups


@dataclass
class VideoJob:
    """動画処理ジョブ"""
    id: int
    source_path: Path
    status: JobStatus = JobStatus.WAITING
    
    # デフォルトのメタデータ（シーンに設定がない場合に使用）
    default_event_name: str = ""
    default_event_date: Optional[date] = None
    
    scenes: list[Scene] = field(default_factory=list)
    clips: list[Clip] = field(default_factory=list)
    output_dir: Optional[Path] = None
    error_message: str = ""
    
    @property
    def filename(self) -> str:
        return self.source_path.name
    
    @property
    def kept_scenes(self) -> list[Scene]:
        return [s for s in self.scenes if s.keep]
    
    def get_scene_metadata(self, scene_index: int) -> Tuple[str, Optional[date]]:
        """
        指定シーンの有効なメタデータを取得（引き継ぎを考慮）
        
        Returns:
            (event_name, event_date)
        """
        current_name = self.default_event_name
        current_date = self.default_event_date
        
        for scene in self.scenes:
            if scene.index > scene_index:
                break
            
            # シーンに設定があれば更新
            if scene.event_name is not None:
                current_name = scene.event_name
            if scene.event_date is not None:
                current_date = scene.event_date
        
        return current_name, current_date
    
    def get_scenes_grouped_by_metadata(self) -> List[Tuple[str, Optional[date], bool, List['Scene']]]:
        """
        メタデータでグループ化されたシーンリストを取得
        
        Returns:
            [(event_name, event_date, is_sensitive, [scenes]), ...]
        """
        groups = []
        current_name = self.default_event_name
        current_date = self.default_event_date
        current_sensitive = False
        current_scenes = []
        
        for scene in self.kept_scenes:
            # メタデータが変わったら新しいグループを開始
            scene_name, scene_date = self.get_scene_metadata(scene.index)
            
            if current_scenes and (
                scene_name != current_name
                or scene_date != current_date
                or scene.is_sensitive != current_sensitive
            ):
                # 前のグループを保存
                groups.append((current_name, current_date, current_sensitive, current_scenes))
                current_scenes = []
            
            current_name = scene_name
            current_date = scene_date
            current_sensitive = scene.is_sensitive
            current_scenes.append(scene)
        
        # 最後のグループを追加
        if current_scenes:
            groups.append((current_name, current_date, current_sensitive, current_scenes))
        
        return groups
    
    def propagate_metadata_from_scene(self, scene_index: int):
        """
        指定シーンのメタデータを後続のシーンに伝播
        （後続シーンに独自の設定がない場合のみ）
        
        これは主にUI側で使用し、ユーザーが入力した値を
        視覚的に後続シーンに反映させるために使う
        """
        source_scene = None
        for scene in self.scenes:
            if scene.index == scene_index:
                source_scene = scene
                break
        
        if not source_scene:
            return
        
        # 後続シーンで、独自の設定がないものに伝播
        found_source = False
        for scene in self.scenes:
            if scene.index == scene_index:
                found_source = True
                continue
            
            if found_source:
                # 後続シーンに独自の設定がある場合は伝播を停止
                if scene.has_metadata():
                    break
    
    def rebuild_scenes_from_boundaries(self, boundaries: List[float], duration: float):
        """
        境界時刻リストからシーンを再構築。
        旧シーンのメタデータは開始時刻が近いものから引き継ぐ。
        """
        if not boundaries:
            return

        sorted_boundaries = sorted(boundaries)
        old_scenes = self.scenes.copy()

        new_scenes = []
        for i in range(len(sorted_boundaries)):
            start_time = sorted_boundaries[i]
            end_time = sorted_boundaries[i + 1] if i + 1 < len(sorted_boundaries) else duration

            scene = Scene(index=i + 1, start_time=start_time, end_time=end_time)

            # 旧シーンからメタデータを引き継ぎ（開始時刻が近いもの）
            for old_scene in old_scenes:
                if abs(old_scene.start_time - start_time) < 5.0:
                    scene.event_name = old_scene.event_name
                    scene.event_date = old_scene.event_date
                    scene.keep = old_scene.keep
                    scene.is_sensitive = old_scene.is_sensitive
                    scene.thumbnail_path = old_scene.thumbnail_path
                    scene.filename_override = old_scene.filename_override
                    break

            new_scenes.append(scene)

        self.scenes = new_scenes

    def get_output_folder_name(self, event_name: str = None, event_date: date = None) -> str:
        """出力フォルダ名を生成"""
        name = event_name or self.default_event_name or "untitled"
        d = event_date or self.default_event_date
        date_str = d.strftime("%Y-%m-%d") if d else "unknown"
        return f"{date_str}_{name}"

    def get_output_dir(
        self,
        output_base_dir: Path,
        event_name: str = None,
        event_date: date = None,
        is_sensitive: bool = False,
    ) -> Path:
        """出力ディレクトリを生成。要注意クリップは sensitive 配下へ分離する。"""
        folder_name = self.get_output_folder_name(event_name, event_date)
        if is_sensitive:
            return output_base_dir / "sensitive" / folder_name
        return output_base_dir / folder_name
    
    def get_clip_filename(self, clip: Clip) -> str:
        """クリップファイル名を生成"""
        if clip.filename_override:
            name = clip.filename_override
            if not name.endswith('.mp4'):
                name += '.mp4'
            return name
        name = clip.event_name or self.default_event_name or "untitled"
        d = clip.event_date or self.default_event_date
        date_str = d.strftime("%Y-%m-%d") if d else "unknown"
        # ファイル名に使えない文字を置換
        safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in name)
        return f"{date_str}_{safe_name}_{clip.index:03d}.mp4"


class JobQueue:
    """ジョブキュー管理"""
    
    def __init__(self):
        self._jobs: list[VideoJob] = []
        self._next_id = 1
    
    def add_file(self, path: Path) -> Optional[VideoJob]:
        """単一ファイルをキューに追加"""
        if not path.exists() or path.suffix.lower() != '.mp4':
            return None
        
        # 重複チェック
        for job in self._jobs:
            if job.source_path.resolve() == path.resolve():
                return None
        
        job = VideoJob(id=self._next_id, source_path=path)
        self._next_id += 1
        self._jobs.append(job)
        return job
    
    def add_folder(self, folder: Path) -> list[VideoJob]:
        """フォルダから再帰的にmp4を追加"""
        added = []
        if not folder.is_dir():
            return added
        
        for mp4_path in sorted(folder.rglob("*.mp4")):
            job = self.add_file(mp4_path)
            if job:
                added.append(job)
        
        return added
    
    def get_all_jobs(self) -> list[VideoJob]:
        return self._jobs.copy()
    
    def get_job_by_id(self, job_id: int) -> Optional[VideoJob]:
        for job in self._jobs:
            if job.id == job_id:
                return job
        return None
    
    def get_next_waiting(self) -> Optional[VideoJob]:
        """次の待機中ジョブを取得"""
        for job in self._jobs:
            if job.status == JobStatus.WAITING:
                return job
        return None
    
    def remove_job(self, job_id: int) -> bool:
        """ジョブを削除"""
        for i, job in enumerate(self._jobs):
            if job.id == job_id:
                self._jobs.pop(i)
                return True
        return False
    
    def clear(self):
        """全ジョブをクリア"""
        self._jobs.clear()
        self._next_id = 1
