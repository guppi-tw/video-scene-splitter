#!/usr/bin/env python3
"""
Windows用EXEビルドスクリプト

使用方法:
    python scripts/build_exe.py

出力:
    dist/VideoSceneSplitter/VideoSceneSplitter.exe
"""

import subprocess
import sys
import shutil
from pathlib import Path


def get_project_root() -> Path:
    """プロジェクトルートを取得"""
    return Path(__file__).parent.parent


def check_pyinstaller():
    """PyInstallerがインストールされているか確認"""
    try:
        import PyInstaller
        print(f"PyInstaller version: {PyInstaller.__version__}")
        return True
    except ImportError:
        return False


def install_pyinstaller():
    """PyInstallerをインストール"""
    print("PyInstallerをインストール中...")
    subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)


def check_ffmpeg():
    """ffmpegが同梱されているか確認"""
    project_root = get_project_root()
    ffmpeg_dir = project_root / "vendor" / "ffmpeg"
    
    ffmpeg_exe = ffmpeg_dir / "ffmpeg.exe"
    ffmpeg_bin = ffmpeg_dir / "ffmpeg"
    
    if ffmpeg_exe.exists():
        print(f"ffmpeg found: {ffmpeg_exe}")
        return True
    elif ffmpeg_bin.exists():
        print(f"ffmpeg found: {ffmpeg_bin}")
        return True
    else:
        print("警告: vendor/ffmpeg にffmpegが見つかりません")
        print("EXEにffmpegを同梱する場合は、先に以下を実行してください:")
        print("  python scripts/setup_ffmpeg.py")
        return False


def build():
    """EXEをビルド"""
    project_root = get_project_root()
    spec_file = project_root / "video_scene_splitter.spec"
    
    if not spec_file.exists():
        print(f"エラー: specファイルが見つかりません: {spec_file}")
        return False
    
    print("=" * 50)
    print("Video Scene Splitter - EXE Build")
    print("=" * 50)
    print()
    
    # PyInstallerの確認
    if not check_pyinstaller():
        install_pyinstaller()
    
    # ffmpegの確認
    check_ffmpeg()
    
    print()
    print("ビルド開始...")
    print()
    
    # PyInstallerを実行
    result = subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--clean",
            "--noconfirm",
            str(spec_file)
        ],
        cwd=str(project_root)
    )
    
    if result.returncode != 0:
        print()
        print("ビルドに失敗しました")
        return False
    
    # 出力先を確認
    dist_dir = project_root / "dist" / "VideoSceneSplitter"
    exe_file = dist_dir / "VideoSceneSplitter.exe"
    
    if exe_file.exists():
        print()
        print("=" * 50)
        print("ビルド成功!")
        print("=" * 50)
        print()
        print(f"出力先: {dist_dir}")
        print(f"EXEファイル: {exe_file}")
        print()
        print("実行方法:")
        print(f"  {exe_file}")
        print()
        print("配布する場合は dist/VideoSceneSplitter フォルダ全体をZIPにしてください")
        return True
    else:
        print()
        print("警告: EXEファイルが見つかりません")
        print("macOS/Linuxでビルドした場合は dist/VideoSceneSplitter/VideoSceneSplitter が生成されます")
        return True


def main():
    success = build()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
