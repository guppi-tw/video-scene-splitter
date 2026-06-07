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
