# Video Scene Splitter

Video Scene Splitter は、長尺の家庭用動画や VHS 取り込み動画をローカル環境で確認しながら、必要な位置で分割して MP4 として書き出すためのデスクトップアプリです。

動画ファイルを外部サービスへアップロードせず、手元の PC 上でプレビュー、タイムライン編集、クリップ管理、書き出しまで行えます。

## Intended Use

このアプリは、古いビデオカメラや VHS から取り込んだ長尺動画を、家族で見返しやすい単位に分割・整理するために作りました。

特に、家族向け共有アプリ（例: みてね）へアップロードしやすいよう、イベント名・日付ごとにフォルダ分けし、必要に応じて 595 秒単位で MP4 を書き出せます。595 秒分割は、10 分制限のある動画アップロード先でも扱いやすいよう、少し余裕を持たせた長さです。

## Features

- MP4 ファイルやフォルダをキューに追加
- アプリ内プレビュー再生
- タイムライン上での分割位置の追加、移動、削除
- クリップごとの keep / drop 切り替え
- クラウド共有前に確認したいクリップの「要注意」マーキングと別フォルダ書き出し
- イベント名、日付、ファイル名のメタデータ設定
- 595 秒単位の自動分割書き出し
- ffmpeg によるサムネイル生成と MP4 書き出し
- Windows EXE / macOS アプリ用の PyInstaller ビルドスクリプト

## Requirements

- Python 3.11 or later
- ffmpeg
  - `scripts/setup_ffmpeg.py` で `vendor/ffmpeg/` に配置できます
  - または、システムの PATH にある ffmpeg を使用できます

## Quick Start

### Windows

```powershell
git clone https://github.com/guppi-tw/video-scene-splitter.git
cd video-scene-splitter

python -m venv venv
.\venv\Scripts\Activate.ps1

pip install -r requirements.txt
python scripts\setup_ffmpeg.py
python -m app
```

### macOS

```bash
git clone https://github.com/guppi-tw/video-scene-splitter.git
cd video-scene-splitter
./run_mac.command
```

`run_mac.command` は Python 3.11 以上を探し、必要に応じて `.venv-macos` を作成して依存パッケージと ffmpeg をセットアップしてからアプリを起動します。

手動で起動する場合:

```bash
git clone https://github.com/guppi-tw/video-scene-splitter.git
cd video-scene-splitter

python3.11 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
python scripts/setup_ffmpeg.py
python -m app
```

## Usage

1. 「ファイル追加」または「フォルダ追加」で MP4 をキューに追加します。
2. キューから動画を開くと、動画全体が 1 つのシーンとして読み込まれます。
3. プレビューの「ここで分割」ボタン、またはタイムライン操作で分割位置を追加します。
4. 右側のクリップ一覧で keep / drop、イベント名、日付、ファイル名を調整します。
5. 子供のプールなどクラウド共有前に確認したいクリップは「要注意」にします。
6. 「書き出し」から出力先フォルダを選択します。

### Timeline Controls

| 操作 | 動作 |
| --- | --- |
| タイムラインをクリック | その位置へシーク |
| 境界線をドラッグ | 分割位置を移動 |
| 空白部分を右クリック | 新しい境界を追加 |
| 境界線を右クリック | 境界を削除 |
| Ctrl+Z | 直前の境界操作を取り消し |

### Keyboard Shortcuts

| キー | 動作 |
| --- | --- |
| Space | 再生 / 一時停止 |
| S | 現在位置で分割 |
| Left | コマ戻し |
| Right | コマ送り |
| Ctrl+Z | 境界操作の取り消し |

## Output

書き出し時は、keep 対象のシーンがメタデータごとにフォルダ分けされます。自動分割が有効な場合、長いシーンは 595 秒単位に分割されます。

```text
output/
  2024-05-20_運動会/
    2024-05-20_運動会_001.mp4
    2024-05-20_運動会_002.mp4
  2024-06-15_誕生日会/
    2024-06-15_誕生日会_001.mp4
  sensitive/
    2024-08-01_プール/
      2024-08-01_プール_001.mp4
```

## Building

### Windows EXE

```powershell
.\build.bat
```

または手動で実行します。

```powershell
pip install pyinstaller
python scripts\setup_ffmpeg.py
python scripts\build_exe.py
```

出力:

```text
dist/
  VideoSceneSplitter.exe
```

### macOS App

```bash
./build_mac.command
```

`build_mac.command` も Python 3.11 以上を探し、必要に応じて `.venv-macos` を作成してから `VideoSceneSplitter.app` をビルドします。

または手動で実行します。

```bash
pip install pyinstaller
python scripts/setup_ffmpeg.py
python scripts/build_mac.py
```

出力:

```text
dist/
  VideoSceneSplitter.app
```

コード署名は行っていないため、初回起動時に macOS の Gatekeeper 警告が出る場合があります。その場合は Finder で右クリックして「開く」を選択してください。

## ffmpeg

このアプリはサムネイル生成、動画の長さ取得、クリップ書き出しに ffmpeg を使用します。

検索優先順位:

1. `vendor/ffmpeg/` 内の同梱バイナリ
2. システム PATH 上の ffmpeg
3. Windows の一般的なインストール先

`scripts/setup_ffmpeg.py` は、実行環境に応じた ffmpeg / ffprobe をダウンロードして `vendor/ffmpeg/` に配置します。ダウンロードされる ffmpeg バイナリは、このリポジトリの MIT License とは別に、それぞれの配布元および ffmpeg のライセンス条件に従います。ビルド済みアプリに ffmpeg を同梱して配布する場合は、ffmpeg 側のライセンス表記も確認してください。

## Development

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"
pytest
```

## Project Structure

```text
video-scene-splitter/
  app/
    main.py                 # Application entry point
    core/
      exporter.py           # Clip calculation and export orchestration
      ffmpeg_runner.py      # ffmpeg process wrapper
      jobs.py               # Job, scene, and clip data models
    ui/
      main_window.py        # Main window
      queue_widget.py       # Video queue
      preview_widget.py     # Video preview
      timeline_widget.py    # Timeline editor
      clip_list_widget.py   # Clip list and metadata editor
      workers.py            # Background workers
  scripts/
    setup_ffmpeg.py         # ffmpeg downloader
    build_exe.py            # Windows build helper
    build_mac.py            # macOS build helper
  tests/
  vendor/ffmpeg/            # Downloaded ffmpeg binaries, ignored by git
```

## Troubleshooting

### ffmpeg が見つからない

```text
RuntimeError: ffmpegが見つかりません。
```

以下のどちらかを試してください。

```bash
python scripts/setup_ffmpeg.py
```

または、ffmpeg を手動でインストールして PATH に追加してください。

### macOS で ffmpeg がブロックされる

ダウンロードした ffmpeg に quarantine 属性が付いている場合があります。

```bash
xattr -d com.apple.quarantine vendor/ffmpeg/ffmpeg
xattr -d com.apple.quarantine vendor/ffmpeg/ffprobe
```

### ビルドに失敗する

- 仮想環境が有効になっているか確認してください。
- `pip install -r requirements.txt` を再実行してください。
- PyInstaller がない場合は `pip install pyinstaller` を実行してください。
- ffmpeg 同梱が必要な場合は、先に `python scripts/setup_ffmpeg.py` を実行してください。

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

ffmpeg is not developed by this project. When downloading, bundling, or redistributing ffmpeg binaries, follow the licenses and notices required by ffmpeg and the binary distributor.
