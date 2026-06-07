#!/bin/bash
# Video Scene Splitter - macOS 起動スクリプト
# このファイルをダブルクリックするとアプリを起動します

set -e

cd "$(dirname "$0")"

echo "=================================="
echo "Video Scene Splitter - macOS 起動"
echo "=================================="
echo ""

source scripts/macos_bootstrap.sh

python_bin="$(ensure_macos_venv)"

if [ ! -x "vendor/ffmpeg/ffmpeg" ] || [ ! -x "vendor/ffmpeg/ffprobe" ]; then
    echo ""
    echo "ffmpegをセットアップ中..."
    "$python_bin" scripts/setup_ffmpeg.py
fi

echo ""
echo "アプリを起動します..."
"$python_bin" -m app
