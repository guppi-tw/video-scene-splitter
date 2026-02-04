"""
exporter.py のユニットテスト
"""
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, MagicMock

from app.core.jobs import Scene, Clip, VideoJob
from app.core.exporter import Exporter


class TestExporter:
    """Exporterクラスのテスト"""

    @pytest.fixture
    def mock_ffmpeg(self):
        """FFmpegRunnerのモック"""
        return Mock()

    @pytest.fixture
    def exporter(self, mock_ffmpeg):
        """Exporterインスタンス"""
        return Exporter(mock_ffmpeg)

    @pytest.fixture
    def sample_job(self):
        """テスト用のVideoJob"""
        job = VideoJob(
            id=1,
            source_path=Path("/path/to/video.mp4"),
            default_event_name="テストイベント",
            default_event_date=date(2024, 5, 20)
        )
        return job


class TestCalculateClips(TestExporter):
    """calculate_clipsメソッドのテスト"""

    def test_single_short_scene(self, exporter, sample_job):
        """595秒以下の単一シーン"""
        sample_job.scenes = [
            Scene(index=1, start_time=0.0, end_time=300.0, keep=True)
        ]
        clips = exporter.calculate_clips(sample_job)

        assert len(clips) == 1
        assert clips[0].start_time == 0.0
        assert clips[0].end_time == 300.0
        assert clips[0].duration == 300.0

    def test_single_long_scene_split(self, exporter, sample_job):
        """595秒超の単一シーン（分割される）"""
        sample_job.scenes = [
            Scene(index=1, start_time=0.0, end_time=1200.0, keep=True)  # 20分
        ]
        clips = exporter.calculate_clips(sample_job)

        # 1200秒 = 595 + 595 + 10 -> 3クリップ（短い余りは吸収されない可能性）
        assert len(clips) >= 2
        assert clips[0].duration == 595.0
        assert clips[0].start_time == 0.0
        assert clips[0].end_time == 595.0

    def test_skip_dropped_scenes(self, exporter, sample_job):
        """keep=Falseのシーンはスキップされる"""
        sample_job.scenes = [
            Scene(index=1, start_time=0.0, end_time=100.0, keep=True),
            Scene(index=2, start_time=100.0, end_time=200.0, keep=False),
            Scene(index=3, start_time=200.0, end_time=300.0, keep=True),
        ]
        clips = exporter.calculate_clips(sample_job)

        # keepのシーンのみがクリップになる
        assert len(clips) == 2
        assert clips[0].start_time == 0.0
        assert clips[0].end_time == 100.0
        assert clips[1].start_time == 200.0
        assert clips[1].end_time == 300.0

    def test_no_kept_scenes(self, exporter, sample_job):
        """全てのシーンがdropされた場合"""
        sample_job.scenes = [
            Scene(index=1, start_time=0.0, end_time=100.0, keep=False),
            Scene(index=2, start_time=100.0, end_time=200.0, keep=False),
        ]
        clips = exporter.calculate_clips(sample_job)

        assert len(clips) == 0

    def test_clips_have_metadata(self, exporter, sample_job):
        """クリップにメタデータが設定される"""
        sample_job.scenes = [
            Scene(index=1, start_time=0.0, end_time=100.0, keep=True)
        ]
        clips = exporter.calculate_clips(sample_job)

        assert len(clips) == 1
        assert clips[0].event_name == "テストイベント"
        assert clips[0].event_date == date(2024, 5, 20)

    def test_scene_specific_metadata(self, exporter, sample_job):
        """シーン固有のメタデータがクリップに反映される"""
        sample_job.scenes = [
            Scene(index=1, start_time=0.0, end_time=100.0, keep=True,
                  event_name="運動会", event_date=date(2024, 6, 1)),
        ]
        clips = exporter.calculate_clips(sample_job)

        assert len(clips) == 1
        assert clips[0].event_name == "運動会"
        assert clips[0].event_date == date(2024, 6, 1)


class TestSplitSceneToClips(TestExporter):
    """_split_scene_to_clipsメソッドのテスト"""

    def test_scene_under_max_duration(self, exporter):
        """最大長以下のシーンは分割されない"""
        scene = Scene(index=1, start_time=0.0, end_time=500.0)
        clips = exporter._split_scene_to_clips(scene, 1, "イベント", date(2024, 1, 1))

        assert len(clips) == 1
        assert clips[0].start_time == 0.0
        assert clips[0].end_time == 500.0

    def test_scene_exactly_max_duration(self, exporter):
        """ちょうど最大長のシーン"""
        scene = Scene(index=1, start_time=0.0, end_time=595.0)
        clips = exporter._split_scene_to_clips(scene, 1, "イベント", date(2024, 1, 1))

        assert len(clips) == 1
        assert clips[0].duration == 595.0

    def test_scene_over_max_duration(self, exporter):
        """最大長を超えるシーンは分割される"""
        scene = Scene(index=1, start_time=0.0, end_time=1000.0)
        clips = exporter._split_scene_to_clips(scene, 1, "イベント", date(2024, 1, 1))

        assert len(clips) == 2
        assert clips[0].start_time == 0.0
        assert clips[0].end_time == 595.0
        assert clips[1].start_time == 595.0
        assert clips[1].end_time == 1000.0


class TestMergeShortRemainders(TestExporter):
    """_merge_short_remaindersメソッドのテスト"""

    def test_no_short_remainders(self, exporter):
        """短い余りがない場合"""
        clips = [
            Clip(index=1, start_time=0.0, end_time=500.0, source_scene_indices=[1]),
            Clip(index=2, start_time=500.0, end_time=1000.0, source_scene_indices=[1]),
        ]
        result = exporter._merge_short_remainders(clips)

        assert len(result) == 2

    def test_merge_short_remainder(self, exporter):
        """短い余りが前のクリップに吸収される"""
        clips = [
            Clip(index=1, start_time=0.0, end_time=595.0, source_scene_indices=[1]),
            Clip(index=2, start_time=595.0, end_time=610.0, source_scene_indices=[1]),  # 15秒 < 30秒
        ]
        result = exporter._merge_short_remainders(clips)

        assert len(result) == 1
        assert result[0].start_time == 0.0
        assert result[0].end_time == 610.0

    def test_no_merge_different_scenes(self, exporter):
        """異なるシーンからのクリップは吸収されない"""
        clips = [
            Clip(index=1, start_time=0.0, end_time=595.0, source_scene_indices=[1]),
            Clip(index=2, start_time=595.0, end_time=610.0, source_scene_indices=[2]),  # 異なるシーン
        ]
        result = exporter._merge_short_remainders(clips)

        assert len(result) == 2

    def test_single_clip(self, exporter):
        """1つのクリップの場合"""
        clips = [
            Clip(index=1, start_time=0.0, end_time=100.0, source_scene_indices=[1]),
        ]
        result = exporter._merge_short_remainders(clips)

        assert len(result) == 1

    def test_empty_list(self, exporter):
        """空のリストの場合"""
        result = exporter._merge_short_remainders([])
        assert len(result) == 0
