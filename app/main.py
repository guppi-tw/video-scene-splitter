"""
Video Scene Splitter - メインエントリーポイント
"""
import sys
import os

# PyInstallerでビルドした場合のパス対応
if getattr(sys, 'frozen', False):
    # PyInstallerでビルドされた場合
    application_path = os.path.dirname(sys.executable)
    # 一時展開ディレクトリをパスに追加
    if hasattr(sys, '_MEIPASS'):
        sys.path.insert(0, sys._MEIPASS)
else:
    # 通常のPython実行
    application_path = os.path.dirname(os.path.abspath(__file__))
    # appディレクトリの親をパスに追加
    parent_path = os.path.dirname(application_path)
    if parent_path not in sys.path:
        sys.path.insert(0, parent_path)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

# PyInstaller対応: 絶対インポートを使用
from app.ui.main_window import MainWindow


def main():
    """アプリケーションのメインエントリーポイント"""
    # High DPI対応
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    app.setApplicationName("Video Scene Splitter")
    app.setOrganizationName("VideoSceneSplitter")
    
    # スタイル設定
    app.setStyle("Fusion")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
