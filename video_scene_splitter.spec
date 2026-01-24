# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Video Scene Splitter

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
    # Windows
    ffmpeg_exe = ffmpeg_dir / 'ffmpeg.exe'
    if ffmpeg_exe.exists():
        datas.append((str(ffmpeg_exe), 'ffmpeg'))
    # macOS/Linux
    ffmpeg_bin = ffmpeg_dir / 'ffmpeg'
    if ffmpeg_bin.exists():
        datas.append((str(ffmpeg_bin), 'ffmpeg'))

# 隠しインポート（PyInstallerが自動検出できないモジュール）
hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'scenedetect',
    'scenedetect.detectors',
    'scenedetect.detectors.content_detector',
    'cv2',
    'numpy',
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
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VideoSceneSplitter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUIアプリなのでコンソールは非表示
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # アイコンがあれば指定: icon='assets/icon.ico'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VideoSceneSplitter',
)
