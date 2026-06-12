"""
exporter.py のユニットテスト
"""
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, MagicMock

from app.core.jobs import Scene, Clip, VideoJob
from app.core.exporter import Exporter, ExportResult


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

        # 1200秒 = 595 + 595 + 10 -> 短い余りは最後の2クリップで再配分
        assert len(clips) == 3
        assert clips[0].duration == 595.0
        assert clips[0].start_time == 0.0
        assert clips[0].end_time == 595.0
        # 全クリップが最大長以下で、隙間なく繋がっている
        assert all(c.duration <= Exporter.MAX_CLIP_DURATION for c in clips)
        assert clips[-1].end_time == 1200.0
        for prev, nxt in zip(clips, clips[1:]):
            assert prev.end_time == nxt.start_time

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

    def test_sensitive_scene_flag_is_copied_to_clip(self, exporter, sample_job):
        """要注意フラグがクリップに反映される"""
        sample_job.scenes = [
            Scene(index=1, start_time=0.0, end_time=100.0, keep=True, is_sensitive=True),
        ]
        clips = exporter.calculate_clips(sample_job)

        assert len(clips) == 1
        assert clips[0].is_sensitive is True

    def test_sensitive_scenes_are_separate_groups(self, exporter, sample_job):
        """同じイベントでも要注意フラグが違えば別クリップグループになる"""
        sample_job.scenes = [
            Scene(index=1, start_time=0.0, end_time=100.0, keep=True, event_name="プール"),
            Scene(index=2, start_time=100.0, end_time=200.0, keep=True, event_name="プール", is_sensitive=True),
        ]
        clips = exporter.calculate_clips(sample_job)

        assert len(clips) == 2
        assert clips[0].is_sensitive is False
        assert clips[1].is_sensitive is True


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

    def test_short_remainder_is_rebalanced_not_absorbed(self, exporter):
        """短い余りは前のクリップを延長せず、最後の2クリップで均等に再配分される

        延長吸収だと595秒を超え、アップロード先の10分制限を破ってしまう。
        """
        scene = Scene(index=1, start_time=0.0, end_time=610.0)  # 595 + 15秒
        clips = exporter._split_scene_to_clips(scene, 1, "イベント", date(2024, 1, 1))

        assert len(clips) == 2
        assert clips[0].duration == pytest.approx(305.0)
        assert clips[1].duration == pytest.approx(305.0)
        assert all(c.duration <= Exporter.MAX_CLIP_DURATION for c in clips)

    def test_no_clip_ever_exceeds_max_duration(self, exporter):
        """どんな長さでも595秒を超えるクリップは生成されない"""
        for total in (596.0, 610.0, 624.9, 1190.0, 1200.0, 3600.0):
            scene = Scene(index=1, start_time=0.0, end_time=total)
            clips = exporter._split_scene_to_clips(scene, 1, "イベント", None)
            assert all(
                c.duration <= Exporter.MAX_CLIP_DURATION for c in clips
            ), f"total={total}"
            assert clips[0].start_time == 0.0
            assert clips[-1].end_time == total

    def test_filename_override_kept_for_single_clip(self, exporter):
        """自動分割が有効でも、分割不要ならファイル名指定が引き継がれる"""
        scene = Scene(index=1, start_time=0.0, end_time=100.0,
                      filename_override="うんどうかい")
        clips = exporter._split_scene_to_clips(scene, 1, "イベント", None)

        assert len(clips) == 1
        assert clips[0].filename_override == "うんどうかい"

    def test_filename_override_gets_part_suffix_when_split(self, exporter):
        """分割される場合はファイル名指定に連番が付く"""
        scene = Scene(index=1, start_time=0.0, end_time=1000.0,
                      filename_override="うんどうかい.mp4")
        clips = exporter._split_scene_to_clips(scene, 1, "イベント", None)

        assert len(clips) == 2
        assert clips[0].filename_override == "うんどうかい_001"
        assert clips[1].filename_override == "うんどうかい_002"

    def test_no_auto_split_keeps_override(self, mock_ffmpeg):
        """auto_split=False ではシーンが分割されずファイル名指定も維持される"""
        exporter = Exporter(mock_ffmpeg, auto_split=False)
        scene = Scene(index=1, start_time=0.0, end_time=1000.0,
                      filename_override="ちょうへん")
        clips = exporter._split_scene_to_clips(scene, 1, "イベント", None)

        assert len(clips) == 1
        assert clips[0].duration == 1000.0
        assert clips[0].filename_override == "ちょうへん"


class TestExport(TestExporter):
    """exportメソッドのテスト"""

    def test_sensitive_clip_exports_under_sensitive_folder(self, exporter, mock_ffmpeg, sample_job, tmp_path):
        """要注意クリップは sensitive フォルダ配下に書き出される"""
        mock_ffmpeg.extract_clip.return_value = True
        sample_job.scenes = [
            Scene(index=1, start_time=0.0, end_time=100.0, keep=True, is_sensitive=True),
        ]

        result = exporter.export(sample_job, tmp_path)

        assert result.all_succeeded
        output_path = mock_ffmpeg.extract_clip.call_args.kwargs["output_path"]
        assert output_path.parent == tmp_path / "sensitive" / "2024-05-20_テストイベント"

    def test_export_does_not_overwrite_existing_file(self, exporter, mock_ffmpeg, sample_job, tmp_path):
        """既存ファイル（別ジョブや過去の書き出し）を上書きしない"""
        mock_ffmpeg.extract_clip.return_value = True
        sample_job.scenes = [
            Scene(index=1, start_time=0.0, end_time=100.0, keep=True),
        ]

        existing_dir = tmp_path / "2024-05-20_テストイベント"
        existing_dir.mkdir(parents=True)
        existing = existing_dir / "2024-05-20_テストイベント_001.mp4"
        existing.write_bytes(b"previous export")

        result = exporter.export(sample_job, tmp_path)

        assert result.all_succeeded
        output_path = mock_ffmpeg.extract_clip.call_args.kwargs["output_path"]
        assert output_path != existing
        assert output_path.parent == existing_dir
        # 既存ファイルは無傷
        assert existing.read_bytes() == b"previous export"

    def test_non_contiguous_same_metadata_groups_get_unique_filenames(
        self, exporter, mock_ffmpeg, sample_job, tmp_path
    ):
        """同じメタデータのシーン群が離れていても、出力ファイル名は重複しない"""
        mock_ffmpeg.extract_clip.return_value = True
        sample_job.scenes = [
            Scene(index=1, start_time=0.0, end_time=100.0, keep=True, event_name="A"),
            Scene(index=2, start_time=100.0, end_time=200.0, keep=True, event_name="B"),
            Scene(index=3, start_time=200.0, end_time=300.0, keep=True, event_name="A"),
        ]

        result = exporter.export(sample_job, tmp_path)

        assert result.all_succeeded
        output_paths = [
            call.kwargs["output_path"]
            for call in mock_ffmpeg.extract_clip.call_args_list
        ]
        assert len(output_paths) == 3
        assert len(set(output_paths)) == 3

    def test_partial_failure_is_reported(self, exporter, mock_ffmpeg, sample_job, tmp_path):
        """一部のクリップが失敗した場合、結果に反映される"""
        mock_ffmpeg.extract_clip.side_effect = [True, False]
        sample_job.scenes = [
            Scene(index=1, start_time=0.0, end_time=100.0, keep=True),
            Scene(index=2, start_time=100.0, end_time=200.0, keep=True),
        ]

        result = exporter.export(sample_job, tmp_path)

        assert result.total == 2
        assert result.succeeded == 1
        assert not result.all_succeeded

    def test_export_no_clips(self, exporter, sample_job, tmp_path):
        """書き出し対象がない場合"""
        sample_job.scenes = [
            Scene(index=1, start_time=0.0, end_time=100.0, keep=False),
        ]

        result = exporter.export(sample_job, tmp_path)

        assert result.total == 0
        assert result.succeeded == 0
        assert not result.all_succeeded

    def test_export_cancellation(self, exporter, mock_ffmpeg, sample_job, tmp_path):
        """キャンセルされた場合はffmpegを呼ばずに中断する"""
        sample_job.scenes = [
            Scene(index=1, start_time=0.0, end_time=100.0, keep=True),
        ]

        result = exporter.export(sample_job, tmp_path, cancel_callback=lambda: True)

        assert result.cancelled
        mock_ffmpeg.extract_clip.assert_not_called()
