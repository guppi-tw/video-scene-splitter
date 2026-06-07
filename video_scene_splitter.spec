# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Video Scene Splitter (onefile mode)

Usage:
    pyinstaller video_scene_splitter.spec
"""

import sys
from pathlib import Path

block_cipher = None

# プロジェクトルート
project_root = Path(SPECPATH)

# 追加データファイル
datas = []

# vendor/ffmpeg が存在する場合は含める
ffmpeg_dir = project_root / 'vendor' / 'ffmpeg'
if ffmpeg_dir.exists():
    for binary_name in ('ffmpeg', 'ffprobe', 'ffmpeg.exe', 'ffprobe.exe'):
        binary_path = ffmpeg_dir / binary_name
        if binary_path.exists():
            datas.append((str(binary_path), 'vendor/ffmpeg'))

# 隠しインポート（PyInstallerが自動検出できないモジュール）
hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets',
]

a = Analysis(
    ['app/main.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'PIL',
        'scenedetect',
        'cv2',
        'numpy',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# onefile モード - すべてを1つのEXEにまとめる
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='VideoSceneSplitter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUIアプリなのでコンソールは非表示
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # アイコンがあれば指定: icon='assets/icon.ico'
)
