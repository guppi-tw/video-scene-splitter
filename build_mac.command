#!/bin/bash
# Video Scene Splitter - macOS ビルドスクリプト
# このファイルをダブルクリックするとビルドが開始されます

set -e

# スクリプトのディレクトリに移動
cd "$(dirname "$0")"

echo "=================================="
echo "Video Scene Splitter - macOS ビルド"
echo "=================================="
echo ""

source scripts/macos_bootstrap.sh

if ! python_bin="$(ensure_macos_venv)"; then
    read -p "Enterキーを押して終了..."
    exit 1
fi

if ! "$python_bin" -c "import PyInstaller" 2>/dev/null; then
    echo "PyInstallerをインストール中..."
    "$python_bin" -m pip install pyinstaller
fi

# ffmpegがなければダウンロード
if [ ! -x "vendor/ffmpeg/ffmpeg" ] || [ ! -x "vendor/ffmpeg/ffprobe" ]; then
    echo ""
    echo "ffmpegをダウンロード中..."
    "$python_bin" scripts/setup_ffmpeg.py
fi

# ビルド実行
echo ""
"$python_bin" scripts/build_mac.py

echo ""
echo "=================================="
echo "ビルド完了"
echo "=================================="
echo ""
read -p "Enterキーを押して終了..."
