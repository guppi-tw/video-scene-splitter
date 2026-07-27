# Video Scene Splitter

Video Scene Splitter は、長尺の家庭用動画や VHS 取り込み動画をローカル環境で確認しながら、必要な位置で分割して MP4 として書き出すためのデスクトップアプリです。

動画ファイルを外部サービスへアップロードせず、手元の PC 上でプレビュー、タイムライン編集、クリップ管理、書き出しまで行えます。

## Intended Use

このアプリは、古いビデオカメラや VHS から取り込んだ長尺動画を、家族で見返しやすい単位に分割・整理するために作りました。

特に、家族向け共有アプリ（例: みてね）へアップロードしやすいよう、イベント名・日付ごとにフォルダ分けし、必要に応じて 595 秒単位で MP4 を書き出せます。595 秒分割は、10 分制限のある動画アップロード先でも扱いやすいよう、少し余裕を持たせた長さです。

## Features

- MP4 ファイルやフォルダをキューに追加
- 1 回の追加操作で読み込む動画数を最大 100 本に制限
- 複数動画の一括シーン検出（「一括検出」）。専用の進捗ウィンドウで現在の動画・全体進捗・完了結果を確認可能。キューは動画ごとのツリーで、各動画の分割クリップと状態バッジを表示。一括検出した動画を開くと、つなぎ目カット → 結合提案 → 日付検出を自動で順に実行
- キューの状態フィルター（待機中 / 確認が必要 / 書き出し可能 / エラー / 完了）
- 編集内容とキューを自動保存し、次回起動時に復元
- アプリ内プレビュー再生
- PySceneDetect によるシーン境界の自動検出候補追加
  - 感度（閾値）と最小シーン長を UI から調整可能
  - 検出中の進捗表示と途中中止
- 検出後の自動ワークフロー: つなぎ目検出 → 短いシーンの結合提案 → 日付検出
- 単色のつなぎ目（青一色 / 黒一色 / 白一色）の検出と除外提案（昔のテープの無信号区間など）。シーン全体が単色の場合に加え、映像の前後に残る単色のリードイン／アウトも切り出して除外できます。検出直後だけでなく「つなぎ目検出」ボタンで後からも実行可能（一括検出した動画にも）
- 短いシーンをまとめて結合する提案ダイアログ（結合後のシーン数をプレビュー）。検出直後だけでなく「短いシーンを結合」ボタンで後からも実行可能（一括検出した動画にも）
- クリップ一覧から連続シーンを選択してまとめて結合
- 焼き込み日付（昔のビデオカメラの日付スタンプ）の OCR 検出とクリップ日付への自動設定（macOS）。日が読めず年月だけ取れた場合は同月の日や前後のクリップから日を補完
- タイムライン上での分割位置の追加、移動、削除
- クリップごとの「書き出す」切り替え
- クラウド共有前に確認したいクリップの「別フォルダ」マーキング
- イベント名、日付、ファイル名のメタデータ設定
- メタデータ、クリップ設定、境界編集の Undo / Redo
- 書き出し時に日付を動画の作成日時（creation_time）メタデータとファイル更新日時へ書き込み
- 595 秒単位の自動分割書き出し
- ffmpeg によるサムネイル生成と MP4 書き出し
- Windows EXE / macOS アプリ用の PyInstaller ビルドスクリプト

## Requirements

- Python 3.11 or later
- ffmpeg
  - `scripts/setup_ffmpeg.py` で `vendor/ffmpeg/` に配置できます
  - または、システムの PATH にある ffmpeg を使用できます
  - macOS では Apple Silicon ネイティブ（arm64）バイナリを取得します
- 焼き込み日付の OCR 検出は macOS の Vision フレームワークを使用します（`pyobjc-framework-Vision`、macOS のみ。他機能は全プラットフォームで動作します）

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

1. 中央へ MP4 / フォルダをドロップするか、「動画を追加」メニューからキューへ追加します。1 回に追加できる動画は最大 100 本です。
2. キューから動画を開くと、動画全体が 1 つのシーンとして読み込まれます。
3. プレビューの「分割 [S]」ボタン、タイムライン操作、またはタイムラインの「自動検出」で分割位置を追加します。感度と最小シーン長は自動検出の前に調整できます。
4. 自動検出が終わると、続けて次の処理が走ります。
   - 単色のつなぎ目（青 / 黒 / 白一色）を検出し、除外するか提案します。
   - 短いシーンをまとめて結合するか提案します（結合する長さの上限はシーン数のプレビューを見ながら調整できます）。
   - 焼き込み日付を検出し、見つかればクリップの日付に設定します（macOS）。
5. 右側のクリップ一覧で書き出し対象、イベント名、日付、ファイル名を調整します。ファイル名は表示をダブルクリックするか F2 で編集できます。「クリップを結合」を選ぶと連続シーンをまとめられます。
6. 子供のプールなどクラウド共有前に確認したいクリップは「別フォルダ」にします。
7. 「書き出し」から出力先フォルダを選択します。処理中は同じボタンから中止できます。

### Timeline Controls

| 操作 | 動作 |
| --- | --- |
| タイムラインをクリック | その位置へシーク |
| 境界線をドラッグ | 分割位置を移動 |
| 空白部分を右クリック | 新しい境界を追加 |
| 境界線を右クリック | 境界を削除 |
| Ctrl+Z | 直前の編集を取り消し |

### Keyboard Shortcuts

| キー | 動作 |
| --- | --- |
| Space | 再生 / 一時停止 |
| S | 現在位置で分割 |
| Left | コマ戻し |
| Right | コマ送り |
| F2 | 選択中の出力ファイル名を編集 |
| Ctrl+Z | 直前の編集を取り消し |
| Ctrl+Shift+Z / Ctrl+Y | 取り消した編集をやり直し |

## Output

書き出し時は、keep 対象のシーンがメタデータごとにフォルダ分けされます。自動分割が有効な場合、長いシーンは 595 秒単位に分割されます。クリップに日付が設定されている場合は、動画の作成日時（creation_time）メタデータとファイルの更新日時にも反映されるため、写真アプリや Finder で日付順に並びます。

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

ビルド時には以下が自動で行われます。

- `assets/icon.icns` があればアプリアイコンとして埋め込み（`python scripts/generate_icon.py` で再生成できます）
- ad-hoc コード署名（Apple Silicon では署名がないと起動できない場合があるため）。プロジェクトが iCloud 同期フォルダ内にある場合も、同期外の一時ディレクトリで署名してから戻すことで対応します

Developer ID による署名・公証は行っていないため、初回起動時に macOS の Gatekeeper 警告が出る場合があります。その場合は Finder で右クリックして「開く」を選択してください。

## ffmpeg

このアプリはサムネイル生成、動画の長さ取得、クリップ書き出しに ffmpeg を使用します。

書き出しは再エンコードなしのコーデックコピー（`-c copy`）で行うため高速で画質劣化がありませんが、切り出し位置は直近のキーフレームに丸められます。ソース動画の GOP 長によっては、指定した分割位置から数秒前後にずれることがあります。

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
      scene_detector.py     # PySceneDetect boundary detection and short-scene merging
      blank_detector.py     # Solid-color (blue/black/white) join detection
      date_detector.py      # Burned-in date stamp OCR (macOS Vision)
    ui/
      main_window.py        # Main window
      queue_widget.py       # Video queue
      preview_widget.py     # Video preview
      timeline_widget.py    # Timeline editor
      clip_list_widget.py   # Clip list and metadata editor
      merge_dialog.py       # Short-scene merge proposal dialog
      blank_dialog.py       # Solid-color join removal proposal dialog
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
