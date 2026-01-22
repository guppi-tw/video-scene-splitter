"""
ジョブ管理とデータモデル
"""
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
from datetime import date


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
    title: str = ""
    
    @property
    def duration(self) -> float:
        return self.end_time - self.start_time
    
    def __str__(self) -> str:
        return f"Scene {self.index}: {self.start_time:.2f}s - {self.end_time:.2f}s ({self.duration:.2f}s)"


@dataclass
class Clip:
    """書き出し用クリップ情報"""
    index: int
    start_time: float
    end_time: float
    source_scene_indices: list[int] = field(default_factory=list)
    title: str = ""
    output_path: Optional[Path] = None
    
    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


@dataclass
class VideoJob:
    """動画処理ジョブ"""
    id: int
    source_path: Path
    status: JobStatus = JobStatus.WAITING
    event_name: str = ""
    event_date: Optional[date] = None
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
    
    def get_output_folder_name(self) -> str:
        """出力フォルダ名を生成"""
        date_str = self.event_date.strftime("%Y-%m-%d") if self.event_date else "unknown"
        event = self.event_name or "untitled"
        return f"{date_str}_{event}"
    
    def get_clip_filename(self, clip: Clip) -> str:
        """クリップファイル名を生成"""
        date_str = self.event_date.strftime("%Y-%m-%d") if self.event_date else "unknown"
        event = self.event_name or "untitled"
        base = f"{date_str}_{event}_{clip.index:03d}"
        if clip.title:
            base += f"_{clip.title}"
        return f"{base}.mp4"


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
