"""
jobs.py のユニットテスト
"""
import pytest
from datetime import date
from pathlib import Path

from app.core.jobs import (
    Scene, Clip, VideoJob, JobQueue, JobStatus,
    MetadataKey, group_clips_by_metadata
)


class TestScene:
    """Sceneクラスのテスト"""

    def test_duration(self):
        """durationプロパティのテスト"""
        scene = Scene(index=1, start_time=10.0, end_time=25.0)
        assert scene.duration == 15.0

    def test_has_metadata_with_name(self):
        """メタデータがある場合のテスト（名前のみ）"""
        scene = Scene(index=1, start_time=0.0, end_time=10.0, event_name="運動会")
        assert scene.has_metadata() is True

    def test_has_metadata_with_date(self):
        """メタデータがある場合のテスト（日付のみ）"""
        scene = Scene(index=1, start_time=0.0, end_time=10.0, event_date=date(2024, 5, 20))
        assert scene.has_metadata() is True

    def test_has_metadata_without_metadata(self):
        """メタデータがない場合のテスト"""
        scene = Scene(index=1, start_time=0.0, end_time=10.0)
        assert scene.has_metadata() is False


class TestClip:
    """Clipクラスのテスト"""

    def test_duration(self):
        """durationプロパティのテスト"""
        clip = Clip(index=1, start_time=0.0, end_time=595.0)
        assert clip.duration == 595.0


class TestGroupClipsByMetadata:
    """group_clips_by_metadata関数のテスト"""

    def test_empty_list(self):
        """空のリストの場合"""
        result = group_clips_by_metadata([])
        assert result == {}

    def test_single_clip(self):
        """1つのクリップの場合"""
        clips = [
            Clip(index=1, start_time=0.0, end_time=100.0, event_name="運動会", event_date=date(2024, 5, 20))
        ]
        result = group_clips_by_metadata(clips)
        assert len(result) == 1
        assert ("運動会", date(2024, 5, 20), False) in result
        assert len(result[("運動会", date(2024, 5, 20), False)]) == 1

    def test_multiple_clips_same_metadata(self):
        """同じメタデータを持つ複数のクリップ"""
        clips = [
            Clip(index=1, start_time=0.0, end_time=100.0, event_name="運動会", event_date=date(2024, 5, 20)),
            Clip(index=2, start_time=100.0, end_time=200.0, event_name="運動会", event_date=date(2024, 5, 20)),
        ]
        result = group_clips_by_metadata(clips)
        assert len(result) == 1
        assert len(result[("運動会", date(2024, 5, 20), False)]) == 2

    def test_multiple_clips_different_metadata(self):
        """異なるメタデータを持つ複数のクリップ"""
        clips = [
            Clip(index=1, start_time=0.0, end_time=100.0, event_name="運動会", event_date=date(2024, 5, 20)),
            Clip(index=2, start_time=100.0, end_time=200.0, event_name="誕生日会", event_date=date(2024, 6, 15)),
        ]
        result = group_clips_by_metadata(clips)
        assert len(result) == 2
        assert ("運動会", date(2024, 5, 20), False) in result
        assert ("誕生日会", date(2024, 6, 15), False) in result

    def test_clip_without_event_name(self):
        """イベント名がない場合は空文字として扱われる"""
        clips = [
            Clip(index=1, start_time=0.0, end_time=100.0, event_name="", event_date=date(2024, 5, 20)),
        ]
        result = group_clips_by_metadata(clips)
        assert ("", date(2024, 5, 20), False) in result

    def test_sensitive_clip_uses_separate_group(self):
        """要注意フラグが違うクリップは別グループになる"""
        clips = [
            Clip(index=1, start_time=0.0, end_time=100.0, event_name="プール", is_sensitive=False),
            Clip(index=2, start_time=100.0, end_time=200.0, event_name="プール", is_sensitive=True),
        ]
        result = group_clips_by_metadata(clips)
        assert len(result) == 2
        assert ("プール", None, False) in result
        assert ("プール", None, True) in result


class TestVideoJob:
    """VideoJobクラスのテスト"""

    def test_filename(self):
        """filenameプロパティのテスト"""
        job = VideoJob(id=1, source_path=Path("/path/to/video.mp4"))
        assert job.filename == "video.mp4"

    def test_kept_scenes(self):
        """kept_scenesプロパティのテスト"""
        job = VideoJob(id=1, source_path=Path("/path/to/video.mp4"))
        job.scenes = [
            Scene(index=1, start_time=0.0, end_time=10.0, keep=True),
            Scene(index=2, start_time=10.0, end_time=20.0, keep=False),
            Scene(index=3, start_time=20.0, end_time=30.0, keep=True),
        ]
        kept = job.kept_scenes
        assert len(kept) == 2
        assert kept[0].index == 1
        assert kept[1].index == 3

    def test_get_scene_metadata_with_default(self):
        """デフォルトメタデータの取得"""
        job = VideoJob(
            id=1,
            source_path=Path("/path/to/video.mp4"),
            default_event_name="デフォルトイベント",
            default_event_date=date(2024, 1, 1)
        )
        job.scenes = [
            Scene(index=1, start_time=0.0, end_time=10.0),
        ]
        name, d = job.get_scene_metadata(1)
        assert name == "デフォルトイベント"
        assert d == date(2024, 1, 1)

    def test_get_scene_metadata_with_override(self):
        """シーン固有のメタデータの取得"""
        job = VideoJob(
            id=1,
            source_path=Path("/path/to/video.mp4"),
            default_event_name="デフォルト",
            default_event_date=date(2024, 1, 1)
        )
        job.scenes = [
            Scene(index=1, start_time=0.0, end_time=10.0, event_name="運動会", event_date=date(2024, 5, 20)),
        ]
        name, d = job.get_scene_metadata(1)
        assert name == "運動会"
        assert d == date(2024, 5, 20)

    def test_get_scene_metadata_inheritance(self):
        """メタデータの引き継ぎ"""
        job = VideoJob(
            id=1,
            source_path=Path("/path/to/video.mp4"),
            default_event_name="デフォルト"
        )
        job.scenes = [
            Scene(index=1, start_time=0.0, end_time=10.0, event_name="運動会"),
            Scene(index=2, start_time=10.0, end_time=20.0),  # メタデータなし
            Scene(index=3, start_time=20.0, end_time=30.0),  # メタデータなし
        ]
        # シーン2はシーン1から引き継ぐ
        name, _ = job.get_scene_metadata(2)
        assert name == "運動会"
        # シーン3もシーン1から引き継ぐ
        name, _ = job.get_scene_metadata(3)
        assert name == "運動会"

    def test_get_output_folder_name(self):
        """出力フォルダ名の生成"""
        job = VideoJob(id=1, source_path=Path("/path/to/video.mp4"))
        folder_name = job.get_output_folder_name("運動会", date(2024, 5, 20))
        assert folder_name == "2024-05-20_運動会"

    def test_get_output_folder_name_without_date(self):
        """日付なしの出力フォルダ名"""
        job = VideoJob(id=1, source_path=Path("/path/to/video.mp4"))
        folder_name = job.get_output_folder_name("運動会", None)
        assert folder_name == "unknown_運動会"

    def test_get_clip_filename(self):
        """クリップファイル名の生成"""
        job = VideoJob(id=1, source_path=Path("/path/to/video.mp4"))
        clip = Clip(index=1, start_time=0.0, end_time=100.0, event_name="運動会", event_date=date(2024, 5, 20))
        filename = job.get_clip_filename(clip)
        assert filename == "2024-05-20_運動会_001.mp4"

    def test_get_output_dir_sensitive(self):
        """要注意クリップは sensitive 配下へ出力される"""
        job = VideoJob(id=1, source_path=Path("/path/to/video.mp4"))
        output_dir = job.get_output_dir(
            Path("/output"), "プール", date(2024, 8, 1), is_sensitive=True
        )
        assert output_dir == Path("/output/sensitive/2024-08-01_プール")

    def test_rebuild_scenes_preserves_sensitive_flag(self):
        """境界再構築時に要注意フラグを引き継ぐ"""
        job = VideoJob(id=1, source_path=Path("/path/to/video.mp4"))
        job.scenes = [
            Scene(index=1, start_time=0.0, end_time=10.0, is_sensitive=True),
            Scene(index=2, start_time=10.0, end_time=20.0, is_sensitive=False),
        ]

        job.rebuild_scenes_from_boundaries([0.0, 10.0], 20.0)

        assert job.scenes[0].is_sensitive is True
        assert job.scenes[1].is_sensitive is False


class TestJobQueue:
    """JobQueueクラスのテスト"""

    def test_add_file(self, tmp_path):
        """ファイル追加のテスト"""
        queue = JobQueue()
        video_file = tmp_path / "test.mp4"
        video_file.touch()

        job = queue.add_file(video_file)
        assert job is not None
        assert job.id == 1
        assert job.source_path == video_file

    def test_add_file_non_mp4(self, tmp_path):
        """非MP4ファイルは追加されない"""
        queue = JobQueue()
        text_file = tmp_path / "test.txt"
        text_file.touch()

        job = queue.add_file(text_file)
        assert job is None

    def test_add_file_duplicate(self, tmp_path):
        """重複ファイルは追加されない"""
        queue = JobQueue()
        video_file = tmp_path / "test.mp4"
        video_file.touch()

        job1 = queue.add_file(video_file)
        job2 = queue.add_file(video_file)
        assert job1 is not None
        assert job2 is None
        assert len(queue.get_all_jobs()) == 1

    def test_get_next_waiting(self, tmp_path):
        """次の待機中ジョブの取得"""
        queue = JobQueue()
        video1 = tmp_path / "video1.mp4"
        video2 = tmp_path / "video2.mp4"
        video1.touch()
        video2.touch()

        queue.add_file(video1)
        queue.add_file(video2)

        next_job = queue.get_next_waiting()
        assert next_job is not None
        assert next_job.source_path == video1

    def test_remove_job(self, tmp_path):
        """ジョブの削除"""
        queue = JobQueue()
        video_file = tmp_path / "test.mp4"
        video_file.touch()

        job = queue.add_file(video_file)
        assert len(queue.get_all_jobs()) == 1

        result = queue.remove_job(job.id)
        assert result is True
        assert len(queue.get_all_jobs()) == 0

    def test_clear(self, tmp_path):
        """全ジョブのクリア"""
        queue = JobQueue()
        video1 = tmp_path / "video1.mp4"
        video2 = tmp_path / "video2.mp4"
        video1.touch()
        video2.touch()

        queue.add_file(video1)
        queue.add_file(video2)
        assert len(queue.get_all_jobs()) == 2

        queue.clear()
        assert len(queue.get_all_jobs()) == 0
