from pathlib import Path

import app.core.ffmpeg_runner as ffmpeg_runner


def _touch_executable(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)


def test_get_bundled_ffmpeg_path_finds_source_vendor_binary(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    module_path = project_root / "app" / "core" / "ffmpeg_runner.py"
    _touch_executable(project_root / "vendor" / "ffmpeg" / "ffmpeg")
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(ffmpeg_runner, "__file__", str(module_path))
    monkeypatch.delattr(ffmpeg_runner.sys, "frozen", raising=False)
    monkeypatch.delattr(ffmpeg_runner.sys, "_MEIPASS", raising=False)

    assert ffmpeg_runner.get_bundled_ffmpeg_path() == project_root / "vendor" / "ffmpeg" / "ffmpeg"


def test_get_bundled_ffmpeg_path_finds_pyinstaller_vendor_binary(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    module_path = project_root / "app" / "core" / "ffmpeg_runner.py"
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text("", encoding="utf-8")

    meipass = tmp_path / "VideoSceneSplitter.app" / "Contents" / "Frameworks"
    bundled_ffmpeg = meipass / "vendor" / "ffmpeg" / "ffmpeg"
    _touch_executable(bundled_ffmpeg)

    monkeypatch.setattr(ffmpeg_runner, "__file__", str(module_path))
    monkeypatch.setattr(ffmpeg_runner.sys, "frozen", True, raising=False)
    monkeypatch.setattr(ffmpeg_runner.sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(
        ffmpeg_runner.sys,
        "executable",
        str(tmp_path / "VideoSceneSplitter.app" / "Contents" / "MacOS" / "VideoSceneSplitter"),
    )

    assert ffmpeg_runner.get_bundled_ffmpeg_path() == bundled_ffmpeg


def test_extract_clip_writes_creation_time_metadata(tmp_path, monkeypatch):
    from datetime import date

    runner = ffmpeg_runner.FFmpegRunner()
    captured = {}

    class FakeProcess:
        def communicate(self, timeout=None):
            # 成功をシミュレートするため出力ファイルを作る
            Path(captured["cmd"][-1]).write_bytes(b"x")
            return b"", b""

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeProcess()

    monkeypatch.setattr(ffmpeg_runner.subprocess, "Popen", fake_popen)

    output = tmp_path / "clip.mp4"
    ok = runner.extract_clip(
        Path("input.mp4"), 0.0, 1.0, output,
        creation_date=date(2001, 8, 15),
    )

    assert ok
    idx = captured["cmd"].index("-metadata")
    assert captured["cmd"][idx + 1] == "creation_time=2001-08-15T00:00:00"


def test_extract_clip_omits_metadata_without_date(tmp_path, monkeypatch):
    runner = ffmpeg_runner.FFmpegRunner()
    captured = {}

    class FakeProcess:
        def communicate(self, timeout=None):
            Path(captured["cmd"][-1]).write_bytes(b"x")
            return b"", b""

    monkeypatch.setattr(
        ffmpeg_runner.subprocess, "Popen",
        lambda cmd, **kw: (captured.update(cmd=cmd), FakeProcess())[1],
    )

    ok = runner.extract_clip(Path("input.mp4"), 0.0, 1.0, tmp_path / "clip.mp4")

    assert ok
    assert "-metadata" not in captured["cmd"]


def test_extract_clip_exact_mode_uses_quality_transcode_settings(tmp_path, monkeypatch):
    runner = ffmpeg_runner.FFmpegRunner()
    captured = {}

    class FakeProcess:
        def communicate(self, timeout=None):
            Path(captured["cmd"][-1]).write_bytes(b"x")
            return b"", b""

    monkeypatch.setattr(
        ffmpeg_runner.subprocess,
        "Popen",
        lambda cmd, **_kw: (captured.update(cmd=cmd), FakeProcess())[1],
    )

    ok = runner.extract_clip(
        Path("input.mp4"), 1.25, 3.75, tmp_path / "exact.mp4", use_copy=False
    )

    assert ok
    assert ["-c:v", "libx264"] == captured["cmd"][
        captured["cmd"].index("-c:v"):captured["cmd"].index("-c:v") + 2
    ]
    assert "-crf" in captured["cmd"]
    assert "-pix_fmt" in captured["cmd"]
    assert "-c" not in captured["cmd"]


def test_detect_silence_runs_ffmpeg_filter_and_parses_ranges(monkeypatch):
    runner = ffmpeg_runner.FFmpegRunner()
    captured = {}

    class FakeProcess:
        def communicate(self, timeout=None):
            return b"", (
                b"silence_start: 2.5\n"
                b"silence_end: 4.0 | silence_duration: 1.5\n"
            )

    monkeypatch.setattr(
        ffmpeg_runner.subprocess,
        "Popen",
        lambda cmd, **_kw: (captured.update(cmd=cmd), FakeProcess())[1],
    )

    ranges = runner.detect_silence(Path("input.mp4"), duration=10.0)

    assert ranges == [(2.5, 4.0)]
    assert "silencedetect=noise=-35dB:d=1.0" in captured["cmd"]
