#!/usr/bin/env python3
"""
Windows用EXEビルドスクリプト (onefile mode)

使用方法:
    python scripts/build_exe.py

出力:
    dist/VideoSceneSplitter.exe
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
        print("")
        print("ffmpegなしでビルドを続行します...")
        print("（実行時にシステムのffmpegを使用します）")
        return False


def clean_build():
    """ビルドディレクトリをクリーンアップ"""
    project_root = get_project_root()
    
    build_dir = project_root / "build"
    if build_dir.exists():
        print(f"Cleaning {build_dir}...")
        shutil.rmtree(build_dir)
    
    # distディレクトリは残す（前のビルド結果を保持）


def build():
    """EXEをビルド"""
    project_root = get_project_root()
    spec_file = project_root / "video_scene_splitter.spec"
    
    if not spec_file.exists():
        print(f"エラー: specファイルが見つかりません: {spec_file}")
        return False
    
    print("=" * 50)
    print("Video Scene Splitter - EXE Build (onefile mode)")
    print("=" * 50)
    print()
    
    # PyInstallerの確認
    if not check_pyinstaller():
        install_pyinstaller()
    
    # ffmpegの確認
    check_ffmpeg()
    
    # ビルドディレクトリをクリーンアップ
    clean_build()
    
    print()
    print("ビルド開始...")
    print("（onefileモードのため時間がかかります）")
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
    dist_dir = project_root / "dist"
    exe_file = dist_dir / "VideoSceneSplitter.exe"
    
    # macOS/Linux用
    if not exe_file.exists():
        exe_file = dist_dir / "VideoSceneSplitter"
    
    if exe_file.exists():
        file_size = exe_file.stat().st_size / (1024 * 1024)  # MB
        print()
        print("=" * 50)
        print("ビルド成功!")
        print("=" * 50)
        print()
        print(f"出力ファイル: {exe_file}")
        print(f"ファイルサイズ: {file_size:.1f} MB")
        print()
        print("実行方法:")
        print(f"  {exe_file}")
        print()
        print("配布する場合はこのEXEファイル1つを配布してください")
        print()
        print("注意: ffmpegを同梱していない場合、実行環境にffmpegが")
        print("      インストールされている必要があります")
        return True
    else:
        print()
        print("警告: EXEファイルが見つかりません")
        print(f"dist ディレクトリの内容: {list(dist_dir.iterdir()) if dist_dir.exists() else 'なし'}")
        return False


def main():
    success = build()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
