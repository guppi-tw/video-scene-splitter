#!/usr/bin/env python3
"""
macOS用ビルドスクリプト（Apple Silicon対応）
VideoSceneSplitter.appを生成します
"""
import subprocess
import sys
import shutil
import platform
import tempfile
from pathlib import Path

MIN_PYTHON = (3, 11)


def check_python_version():
    """Python 3.11以上で実行されているか確認"""
    if sys.version_info < MIN_PYTHON:
        required = ".".join(str(part) for part in MIN_PYTHON)
        current = platform.python_version()
        print(f"エラー: Python {required} 以上が必要です")
        print(f"現在のPython: {current}")
        print("macOSでは run_mac.command / build_mac.command を使うと対応するPythonを自動検出します")
        sys.exit(1)


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


def resign_app(app_path: Path) -> bool:
    """アプリバンドルに ad-hoc 署名を付け直す

    iCloud同期フォルダ（~/Documents 等）では File Provider が
    com.apple.FinderInfo などの拡張属性を自動付与するため、
    その場での codesign は "detritus not allowed" で失敗する。
    同期外の一時ディレクトリにクリーンコピーを作って署名し、
    元の場所に戻すことで回避する。
    """
    print("\nad-hoc署名を実行中...")
    try:
        with tempfile.TemporaryDirectory(prefix="vss-sign-") as tmp:
            clean_app = Path(tmp) / app_path.name
            subprocess.run(
                ["ditto", "--norsrc", "--noextattr", "--noacl",
                 str(app_path), str(clean_app)],
                check=True,
            )
            subprocess.run(
                ["codesign", "-s", "-", "--force", "--deep", str(clean_app)],
                check=True, capture_output=True,
            )
            subprocess.run(
                ["codesign", "--verify", "--deep", "--strict", str(clean_app)],
                check=True, capture_output=True,
            )
            # 署名済みコピーで置き換え（署名後に付くxattrは検証に影響しない）
            shutil.rmtree(app_path)
            subprocess.run(["ditto", str(clean_app), str(app_path)], check=True)

        # 最終検証は --strict を付けない。iCloud同期フォルダでは置き戻した
        # 直後に File Provider が FinderInfo を再付与し、strict 検証だけが
        # 反応するため（署名自体は有効で、実行にも影響しない）。
        result = subprocess.run(
            ["codesign", "--verify", "--deep", str(app_path)],
            capture_output=True,
        )
        if result.returncode == 0:
            print("✓ ad-hoc署名 完了（署名検証OK）")
            return True
        print("警告: 署名の最終検証に失敗しました")
        print(result.stderr.decode("utf-8", errors="ignore"))
        return False
    except subprocess.CalledProcessError as e:
        print("警告: ad-hoc署名に失敗しました。手動で署名してください:")
        print(f"  codesign -s - --force --deep {app_path}")
        if e.stderr:
            print(e.stderr.decode("utf-8", errors="ignore"))
        return False


def build_app(project_root: Path, arch: str):
    """アプリをビルド"""
    print("\n" + "=" * 50)
    print("ビルド開始")
    print("=" * 50)
    
    # distとbuildディレクトリをクリーンアップ
    dist_dir = project_root / "dist"
    build_dir = project_root / "build"

    def rmtree_with_retry(path: Path, label: str):
        """Spotlight等が削除中にファイルを触ると Directory not empty で
        失敗することがあるため、少し待ってリトライする"""
        import time
        for attempt in range(3):
            if not path.exists():
                return
            print(f"既存の{label}ディレクトリを削除中...")
            try:
                shutil.rmtree(path)
                return
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(1.0)

    rmtree_with_retry(dist_dir, "dist")
    rmtree_with_retry(build_dir, "build")
    
    # ffmpegの同梱データを準備
    ffmpeg_dir = project_root / "vendor" / "ffmpeg"
    add_data_args = []
    
    if (ffmpeg_dir / "ffmpeg").exists() and (ffmpeg_dir / "ffprobe").exists():
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
        # 隠しインポート
        "--hidden-import", "PySide6.QtCore",
        "--hidden-import", "PySide6.QtGui",
        "--hidden-import", "PySide6.QtWidgets",
        "--hidden-import", "PySide6.QtMultimedia",
        "--hidden-import", "PySide6.QtMultimediaWidgets",
        "--hidden-import", "scenedetect",
        "--hidden-import", "scenedetect.detectors",
        "--hidden-import", "scenedetect.detectors.adaptive_detector",
        "--hidden-import", "scenedetect.detectors.content_detector",
        # パス追加
        "--paths", str(project_root),
        # ターゲットアーキテクチャ
        "--target-architecture", arch,
    ]

    # アイコン（あれば）
    icon_path = project_root / "assets" / "icon.icns"
    if icon_path.exists():
        cmd.extend(["--icon", str(icon_path)])
    else:
        print("情報: assets/icon.icns がないためアイコンなしでビルドします")
        print("      python scripts/generate_icon.py で生成できます")

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
        # PyInstallerの署名はiCloud同期フォルダ内では失敗するため付け直す
        resign_app(app_path)

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

    # Pythonバージョン確認
    check_python_version()
    
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
