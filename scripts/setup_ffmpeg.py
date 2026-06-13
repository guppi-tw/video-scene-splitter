#!/usr/bin/env python3
"""
ffmpegバイナリのダウンロード・セットアップスクリプト

各プラットフォーム向けのffmpegスタティックビルドをダウンロードして
vendor/ffmpeg/ に配置します。

使用方法:
    python scripts/setup_ffmpeg.py

対応プラットフォーム:
    - Windows (x64)
    - macOS (x64, arm64 / Apple Silicon)
    - Linux (x64)
"""
import os
import sys
import platform
import urllib.request
import zipfile
import tarfile
import shutil
from pathlib import Path


# ffmpeg静的ビルドのダウンロードURL
# https://github.com/BtbN/FFmpeg-Builds (Windows/Linux)
# https://ffmpeg.martin-riedl.de/ (macOS: amd64/arm64 それぞれネイティブビルド)
# 注意: evermeet.cx は x86_64 専用ビルドのみで、Apple Siliconでは
# Rosetta経由の実行になるため使用しない（macOS 28以降はRosetta廃止予定）
FFMPEG_URLS = {
    "Windows": {
        "x86_64": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
    },
    "Linux": {
        "x86_64": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz",
    },
    "Darwin": {
        "x86_64": {
            "ffmpeg": "https://ffmpeg.martin-riedl.de/redirect/latest/macos/amd64/release/ffmpeg.zip",
            "ffprobe": "https://ffmpeg.martin-riedl.de/redirect/latest/macos/amd64/release/ffprobe.zip",
        },
        "arm64": {
            "ffmpeg": "https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/ffmpeg.zip",
            "ffprobe": "https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/ffprobe.zip",
        },
    },
}


def get_project_root() -> Path:
    """プロジェクトルートを取得"""
    return Path(__file__).parent.parent


def get_vendor_dir() -> Path:
    """vendorディレクトリを取得"""
    return get_project_root() / "vendor" / "ffmpeg"


def get_platform_info() -> tuple[str, str]:
    """プラットフォーム情報を取得"""
    system = platform.system()
    machine = platform.machine().lower()
    
    # アーキテクチャの正規化
    if machine in ("x86_64", "amd64"):
        machine = "x86_64"
    elif machine in ("arm64", "aarch64"):
        machine = "arm64"
    
    return system, machine


def download_file(url: str, dest: Path, desc: str = "Downloading") -> bool:
    """ファイルをダウンロード"""
    print(f"{desc}: {url}")
    
    try:
        # プログレス表示付きダウンロード
        def report_progress(block_num, block_size, total_size):
            if total_size > 0:
                percent = min(100, block_num * block_size * 100 // total_size)
                print(f"\r  Progress: {percent}%", end="", flush=True)
        
        urllib.request.urlretrieve(url, dest, reporthook=report_progress)
        print()  # 改行
        return True
    except Exception as e:
        print(f"\n  Error: {e}")
        return False


def extract_archive(archive_path: Path, dest_dir: Path) -> bool:
    """アーカイブを展開"""
    print(f"Extracting: {archive_path.name}")
    
    try:
        if archive_path.suffix == ".zip":
            with zipfile.ZipFile(archive_path, 'r') as zf:
                zf.extractall(dest_dir)
        elif archive_path.name.endswith(".tar.xz"):
            with tarfile.open(archive_path, 'r:xz') as tf:
                tf.extractall(dest_dir)
        elif archive_path.name.endswith(".tar.gz"):
            with tarfile.open(archive_path, 'r:gz') as tf:
                tf.extractall(dest_dir)
        else:
            print(f"  Unknown archive format: {archive_path.suffix}")
            return False
        return True
    except Exception as e:
        print(f"  Error: {e}")
        return False


def find_binary(search_dir: Path, binary_name: str, system: str) -> Path | None:
    """展開されたディレクトリからバイナリを探す"""
    if system == "Windows":
        target_name = f"{binary_name}.exe"
    else:
        target_name = binary_name
    
    for path in search_dir.rglob("*"):
        if path.is_file() and path.name == target_name:
            return path
    
    return None


def setup_ffmpeg_macos(vendor_dir: Path, arch_urls: dict) -> bool:
    """macOS用のffmpegセットアップ（ffmpegとffprobeを別々にダウンロード）"""
    import tempfile
    
    binaries = ["ffmpeg", "ffprobe"]
    
    for binary in binaries:
        url = arch_urls[binary]
        dest_path = vendor_dir / binary
        
        if dest_path.exists():
            print(f"{binary} already exists: {dest_path}")
            continue
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            archive_path = tmp_path / f"{binary}.zip"
            
            if not download_file(url, archive_path, f"Downloading {binary}"):
                return False
            
            # 展開
            extract_dir = tmp_path / "extracted"
            extract_dir.mkdir()
            if not extract_archive(archive_path, extract_dir):
                return False
            
            # バイナリを探す
            binary_path = find_binary(extract_dir, binary, "Darwin")
            if not binary_path:
                print(f"Could not find {binary} binary in archive")
                return False
            
            print(f"Found: {binary_path}")
            
            # vendorディレクトリにコピー
            shutil.copy2(binary_path, dest_path)
            os.chmod(dest_path, 0o755)
            print(f"Installed: {dest_path}")
    
    return True


def setup_ffmpeg_other(vendor_dir: Path, url: str, system: str) -> bool:
    """Windows/Linux用のffmpegセットアップ"""
    import tempfile
    
    ffmpeg_name = "ffmpeg.exe" if system == "Windows" else "ffmpeg"
    ffprobe_name = "ffprobe.exe" if system == "Windows" else "ffprobe"
    
    existing_ffmpeg = vendor_dir / ffmpeg_name
    if existing_ffmpeg.exists():
        print(f"ffmpeg already exists: {existing_ffmpeg}")
        response = input("Overwrite? [y/N]: ").strip().lower()
        if response != 'y':
            print("Skipped.")
            return True
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        
        # ダウンロード
        if url.endswith(".zip"):
            archive_name = "ffmpeg.zip"
        elif url.endswith(".tar.xz"):
            archive_name = "ffmpeg.tar.xz"
        else:
            archive_name = "ffmpeg.zip"
        
        archive_path = tmp_path / archive_name
        if not download_file(url, archive_path, "Downloading ffmpeg"):
            return False
        
        # 展開
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        if not extract_archive(archive_path, extract_dir):
            return False
        
        # ffmpegバイナリを探してコピー
        for binary_name in ["ffmpeg", "ffprobe"]:
            binary_path = find_binary(extract_dir, binary_name, system)
            if binary_path:
                if system == "Windows":
                    dest_name = f"{binary_name}.exe"
                else:
                    dest_name = binary_name
                
                dest_path = vendor_dir / dest_name
                shutil.copy2(binary_path, dest_path)
                
                if system != "Windows":
                    os.chmod(dest_path, 0o755)
                
                print(f"Installed: {dest_path}")
            else:
                print(f"Warning: Could not find {binary_name}")
    
    return True


def setup_ffmpeg() -> bool:
    """ffmpegをセットアップ"""
    system, machine = get_platform_info()
    print(f"Platform: {system} ({machine})")
    
    # URLを取得
    if system not in FFMPEG_URLS:
        print(f"Unsupported platform: {system}")
        return False
    
    arch_urls = FFMPEG_URLS[system]
    if machine not in arch_urls:
        print(f"Unsupported architecture: {machine}")
        # x86_64にフォールバック
        if "x86_64" in arch_urls:
            print("Falling back to x86_64")
            machine = "x86_64"
        else:
            return False
    
    # vendorディレクトリを準備
    vendor_dir = get_vendor_dir()
    vendor_dir.mkdir(parents=True, exist_ok=True)
    
    # プラットフォーム別のセットアップ
    if system == "Darwin":
        return setup_ffmpeg_macos(vendor_dir, arch_urls[machine])
    else:
        return setup_ffmpeg_other(vendor_dir, arch_urls[machine], system)


def main():
    print("=" * 50)
    print("ffmpeg Setup Script for Video Scene Splitter")
    print("=" * 50)
    print()
    
    success = setup_ffmpeg()
    
    if success:
        print()
        print("=" * 50)
        print("Setup completed successfully!")
        print("=" * 50)
        print(f"ffmpeg location: {get_vendor_dir()}")
        
        # インストールされたバイナリを表示
        vendor_dir = get_vendor_dir()
        print("\nInstalled binaries:")
        for f in vendor_dir.iterdir():
            if f.is_file() and not f.name.startswith('.'):
                print(f"  - {f.name}")
    else:
        print()
        print("Setup failed.")
        print("Please install ffmpeg manually and add it to PATH.")
        sys.exit(1)


if __name__ == "__main__":
    main()
