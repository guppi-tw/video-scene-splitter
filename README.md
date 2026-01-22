# Video Scene Splitter

家庭用の長尺動画（VHS起こしなど）を、シーン検知・レビュー・分割書き出しまでGUIで行えるローカルアプリケーションです。

## 機能

- **フォルダ/ファイル投入**: MP4ファイルを再帰的に検索してキューに追加
- **シーン検知**: PySceneDetect（Content Detector）による自動シーン境界検出
- **サムネイル生成**: 各シーンの代表フレームをサムネイルとして表示
- **レビューUI**: サムネイル一覧でkeep/dropを切り替え、プレビュー再生
- **9:55分割書き出し**: 595秒（9分55秒）単位で自動分割してMP4出力
- **メタデータ入力**: イベント名・日付を入力して出力ファイル名に反映

## 必要環境

- **Python**: 3.11以上
- **ffmpeg**: 同梱スクリプトで自動ダウンロード可能（または手動インストール）

## インストール

```bash
# リポジトリをクローン
git clone https://github.com/YOUR_USERNAME/video-scene-splitter.git
cd video-scene-splitter

# 仮想環境を作成（推奨）
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 依存パッケージをインストール
pip install -r requirements.txt

# ffmpegをセットアップ（自動ダウンロード）
python scripts/setup_ffmpeg.py
```

### ffmpegについて

アプリはffmpegを使用して動画処理を行います。以下の方法でffmpegを用意できます：

#### 方法1: 自動ダウンロード（推奨）

```bash
python scripts/setup_ffmpeg.py
```

このスクリプトは、お使いのOS（Windows/macOS/Linux）に対応したffmpegバイナリを自動的にダウンロードし、`vendor/ffmpeg/` に配置します。

#### 方法2: 手動インストール

既にffmpegがインストールされている場合、PATHに通っていれば自動的に検出されます。

**macOS (Homebrew):**
```bash
brew install ffmpeg
```

**Windows:**
1. [ffmpeg公式サイト](https://ffmpeg.org/download.html)からダウンロード
2. 解凍してPATHに追加

**Ubuntu/Debian:**
```bash
sudo apt update && sudo apt install ffmpeg
```

### ffmpegの検索優先順位

1. `vendor/ffmpeg/` 内の同梱バイナリ
2. システムPATH上のffmpeg
3. Windows一般的なパス（`C:/ffmpeg/bin/` など）

## 起動方法

```bash
# プロジェクトディレクトリで実行
python -m app
```

## 使い方

### 1. 動画をキューに追加

- **フォルダ追加**: 「フォルダ追加」ボタンでフォルダを選択すると、再帰的にMP4ファイルを検索してキューに追加
- **ファイル追加**: 「ファイル追加」ボタンで個別のMP4ファイルを追加

### 2. 処理開始

- 「処理開始」ボタンをクリックすると、キュー内の動画を順番に処理
- シーン検知 → サムネイル生成 の順で処理が進行
- 処理状況はログエリアに表示

### 3. レビュー

- 処理完了後、右側のレビューエリアにサムネイル一覧が表示
- 各シーンの「Keep」チェックボックスで保持/削除を切り替え
- サムネイルをクリックして選択し、「選択シーンをプレビュー」でOS標準プレイヤーで確認
- 「イベント名」「日付」を入力して出力ファイル名をカスタマイズ

### 4. 書き出し

- 「書き出し」ボタンをクリックして出力先フォルダを選択
- Keep対象のシーンが595秒（9分55秒）単位で分割されてMP4出力
- 出力ファイル名: `YYYY-MM-DD_イベント名_001.mp4`

## 出力構造

```
出力先フォルダ/
  YYYY-MM-DD_イベント名/
    YYYY-MM-DD_イベント名_001.mp4
    YYYY-MM-DD_イベント名_002.mp4
    ...
```

## ステータス一覧

| ステータス | 説明 |
|-----------|------|
| WAITING | 処理待ち |
| PROCESSING | 処理中（シーン検知/サムネイル生成） |
| REVIEW | レビュー待ち |
| DONE | 書き出し完了 |
| ERROR | エラー発生 |

## 技術スタック

- **言語**: Python 3.11+
- **GUI**: PySide6 (Qt for Python)
- **シーン検知**: PySceneDetect
- **動画処理**: ffmpeg（同梱または外部）

## ディレクトリ構成

```
video-scene-splitter/
├── app/
│   ├── __init__.py
│   ├── __main__.py
│   ├── main.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── jobs.py           # ジョブ管理・データモデル
│   │   ├── scenedetect_runner.py  # シーン検知
│   │   ├── ffmpeg_runner.py  # ffmpeg操作
│   │   └── exporter.py       # 分割・書き出し
│   └── ui/
│       ├── __init__.py
│       ├── main_window.py    # メインウィンドウ
│       ├── queue_widget.py   # キュー表示
│       ├── review_widget.py  # レビューUI
│       ├── log_widget.py     # ログ表示
│       └── workers.py        # バックグラウンドワーカー
├── scripts/
│   └── setup_ffmpeg.py       # ffmpegダウンロードスクリプト
├── vendor/
│   └── ffmpeg/               # 同梱ffmpegバイナリ（自動ダウンロード）
├── requirements.txt
├── pyproject.toml
└── README.md
```

## 注意事項

- 処理中に「処理停止」ボタンで中断可能（現在のffmpegプロセスを停止）
- エラーが発生しても次の動画に進める設計
- 一時ファイル（サムネイル等）はアプリ終了時に自動削除

## トラブルシューティング

### ffmpegが見つからない

```
RuntimeError: ffmpegが見つかりません。
```

以下を試してください：
1. `python scripts/setup_ffmpeg.py` を実行してffmpegをダウンロード
2. または手動でffmpegをインストールしてPATHに追加

### macOSでセキュリティ警告が出る

ダウンロードしたffmpegバイナリを初めて実行する際、macOSのGatekeeperによりブロックされる場合があります。

1. システム環境設定 → セキュリティとプライバシー → 一般
2. 「このまま許可」をクリック

または、ターミナルで以下を実行：
```bash
xattr -d com.apple.quarantine vendor/ffmpeg/ffmpeg
```

## ライセンス

MIT License
