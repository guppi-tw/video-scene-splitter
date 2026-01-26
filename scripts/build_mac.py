#!/usr/bin/env python3
"""
macOS用ビルドスクリプト（Apple Silicon対応）
VideoSceneSplitter.appを生成します
"""
import subprocess
import sys
import shutil
import platform
from pathlib import Path


def check_platform():
    """macOSで実行されているか確認"""
    if platform.system() != "Darwin":
        print("エラー: このスクリプトはmacOSでのみ実行できます")
        print(f"現在のOS: {platform.system()}")
        sys.exit(1)
    
    # Apple Silicon かどうか
    machine = platform.machine()
    if machine == "arm64":
        print("✓ Apple Silicon (arm64) を検出")
    elif machine == "x86_64":
        print("✓ Intel Mac (x86_64) を検出")
    else:
        print(f"警告: 不明なアーキテクチャ: {machine}")
    
    return machine


def check_dependencies():
    """必要な依存関係を確認"""
    print("\n依存関係を確認中...")
    
    # PyInstallerがインストールされているか確認
    try:
        import PyInstaller
        print(f"✓ PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("PyInstallerをインストール中...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
    
    # PySide6がインストールされているか確認
    try:
        import PySide6
        print(f"✓ PySide6 {PySide6.__version__}")
    except ImportError:
        print("エラー: PySide6がインストールされていません")
        print("pip install -r requirements.txt を実行してください")
        sys.exit(1)


def check_ffmpeg(project_root: Path):
    """ffmpegが同梱されているか確認"""
    ffmpeg_path = project_root / "vendor" / "ffmpeg" / "ffmpeg"
    ffprobe_path = project_root / "vendor" / "ffmpeg" / "ffprobe"
    
    if ffmpeg_path.exists() and ffprobe_path.exists():
        print(f"✓ ffmpegが見つかりました: {ffmpeg_path}")
        return True
    else:
        print("警告: vendor/ffmpeg/ にffmpegが見つかりません")
        print("python scripts/setup_ffmpeg.py を実行してffmpegをダウンロードしてください")
        print("ffmpegなしでもビルドは可能ですが、実行時にシステムのffmpegが必要になります")
        return False


def build_app(project_root: Path, arch: str):
    """アプリをビルド"""
    print("\n" + "=" * 50)
    print("ビルド開始")
    print("=" * 50)
    
    # distとbuildディレクトリをクリーンアップ
    dist_dir = project_root / "dist"
    build_dir = project_root / "build"
    
    if dist_dir.exists():
        print("既存のdistディレクトリを削除中...")
        shutil.rmtree(dist_dir)
    
    if build_dir.exists():
        print("既存のbuildディレクトリを削除中...")
        shutil.rmtree(build_dir)
    
    # ffmpegの同梱データを準備
    ffmpeg_dir = project_root / "vendor" / "ffmpeg"
    add_data_args = []
    
    if ffmpeg_dir.exists():
        # macOSでは : をセパレータとして使用
        add_data_args.extend([
            "--add-data", f"{ffmpeg_dir}:vendor/ffmpeg"
        ])
    
    # PyInstallerコマンドを構築
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "VideoSceneSplitter",
        "--windowed",  # macOSでは.appバンドルを作成
        "--onedir",    # onedirの方がmacOSでは安定
        "--noconfirm",
        # アイコン（あれば）
        # "--icon", "assets/icon.icns",
        # 隠しインポート
        "--hidden-import", "PySide6.QtCore",
        "--hidden-import", "PySide6.QtGui",
        "--hidden-import", "PySide6.QtWidgets",
        "--hidden-import", "PySide6.QtMultimedia",
        "--hidden-import", "PySide6.QtMultimediaWidgets",
        "--hidden-import", "scenedetect",
        "--hidden-import", "scenedetect.detectors",
        "--hidden-import", "scenedetect.detectors.content_detector",
        "--hidden-import", "cv2",
        "--hidden-import", "numpy",
        # パス追加
        "--paths", str(project_root),
        # ターゲットアーキテクチャ
        "--target-architecture", arch,
    ]
    
    # ffmpegデータを追加
    cmd.extend(add_data_args)
    
    # エントリーポイント
    cmd.append(str(project_root / "app" / "main.py"))
    
    print(f"実行コマンド: {' '.join(cmd)}")
    print()
    
    # ビルド実行
    result = subprocess.run(cmd, cwd=project_root)
    
    if result.returncode != 0:
        print("\nエラー: ビルドに失敗しました")
        sys.exit(1)
    
    # 結果を確認
    app_path = dist_dir / "VideoSceneSplitter.app"
    if app_path.exists():
        print("\n" + "=" * 50)
        print("ビルド成功!")
        print("=" * 50)
        print(f"\n出力先: {app_path}")
        print(f"\nアプリを起動するには:")
        print(f"  open {app_path}")
        print(f"\nまたはFinderでダブルクリックしてください。")
        print(f"\n注意: 初回起動時に「開発元を確認できない」警告が出る場合は、")
        print(f"      右クリック → 「開く」を選択してください。")
    else:
        # onedirモードの場合
        app_dir = dist_dir / "VideoSceneSplitter"
        if app_dir.exists():
            print("\n" + "=" * 50)
            print("ビルド成功!")
            print("=" * 50)
            print(f"\n出力先: {app_dir}")
            print(f"\nアプリを起動するには:")
            print(f"  {app_dir}/VideoSceneSplitter")


def main():
    # プロジェクトルートを取得
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    print("=" * 50)
    print("Video Scene Splitter - macOS ビルド")
    print("=" * 50)
    
    # プラットフォーム確認
    arch = check_platform()
    
    # 依存関係確認
    check_dependencies()
    
    # ffmpeg確認
    check_ffmpeg(project_root)
    
    # ビルド
    build_app(project_root, arch)


if __name__ == "__main__":
    main()
