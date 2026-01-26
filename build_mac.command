#!/bin/bash
# Video Scene Splitter - macOS ビルドスクリプト
# このファイルをダブルクリックするとビルドが開始されます

# スクリプトのディレクトリに移動
cd "$(dirname "$0")"

echo "=================================="
echo "Video Scene Splitter - macOS ビルド"
echo "=================================="
echo ""

# Python3が利用可能か確認
if ! command -v python3 &> /dev/null; then
    echo "エラー: Python3が見つかりません"
    echo "Homebrewでインストールしてください: brew install python3"
    read -p "Enterキーを押して終了..."
    exit 1
fi

# 仮想環境があれば有効化
if [ -d "venv" ]; then
    echo "仮想環境を有効化中..."
    source venv/bin/activate
fi

# 依存関係をインストール（初回のみ）
if ! python3 -c "import PySide6" 2>/dev/null; then
    echo "依存パッケージをインストール中..."
    pip3 install -r requirements.txt
fi

if ! python3 -c "import PyInstaller" 2>/dev/null; then
    echo "PyInstallerをインストール中..."
    pip3 install pyinstaller
fi

# ffmpegがなければダウンロード
if [ ! -f "vendor/ffmpeg/ffmpeg" ]; then
    echo ""
    echo "ffmpegをダウンロード中..."
    python3 scripts/setup_ffmpeg.py
fi

# ビルド実行
echo ""
python3 scripts/build_mac.py

echo ""
echo "=================================="
echo "ビルド完了"
echo "=================================="
echo ""
read -p "Enterキーを押して終了..."
