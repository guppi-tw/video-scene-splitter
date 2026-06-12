"""
アプリアイコン生成スクリプト

PySide6のQPainterでアイコンを描画し、assets/icon.icns を生成します。
デザインはアプリのタイムラインUIがモチーフ:
ダークなスクワークル背景 + フィルムストリップ + 黄色の分割境界線。

使い方:
    python scripts/generate_icon.py
"""
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import PySide6

# 環境によってはQtのプラグインパス解決に失敗するため明示的に指定する
_plugin_dir = Path(PySide6.__file__).parent / "Qt" / "plugins" / "platforms"
if _plugin_dir.is_dir():
    os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(_plugin_dir))

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QGuiApplication, QImage, QLinearGradient, QPainter,
    QPainterPath, QPen, QPolygonF,
)

CANVAS = 1024

# アプリのダークテーマ / タイムラインと同じ配色
COLOR_BG_TOP = QColor("#3a3a40")
COLOR_BG_BOTTOM = QColor("#1a1a1e")
COLOR_FILM = QColor("#0e0e10")
COLOR_HOLE = QColor("#cfcfd4")
COLOR_SCENE_LEFT = QColor("#447553")
COLOR_SCENE_RIGHT = QColor("#6da37e")
COLOR_BOUNDARY = QColor("#ffcc00")

# iconset に必要なサイズ (ファイル名サフィックス, ピクセル数)
ICONSET_SIZES = [
    ("16x16", 16), ("16x16@2x", 32),
    ("32x32", 32), ("32x32@2x", 64),
    ("128x128", 128), ("128x128@2x", 256),
    ("256x256", 256), ("256x256@2x", 512),
    ("512x512", 512), ("512x512@2x", 1024),
]


def draw_icon() -> QImage:
    """1024x1024のアイコン画像を描画"""
    image = QImage(CANVAS, CANVAS, QImage.Format_ARGB32)
    image.fill(Qt.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)

    # スクワークル（macOS Big Sur以降のアイコン形状に合わせた角丸正方形）
    inset = 72
    squircle = QPainterPath()
    squircle.addRoundedRect(
        QRectF(inset, inset, CANVAS - 2 * inset, CANVAS - 2 * inset), 212, 212
    )

    gradient = QLinearGradient(0, inset, 0, CANVAS - inset)
    gradient.setColorAt(0.0, COLOR_BG_TOP)
    gradient.setColorAt(1.0, COLOR_BG_BOTTOM)
    painter.fillPath(squircle, gradient)

    # 以降はスクワークル内にクリップして描画
    painter.setClipPath(squircle)

    # フィルムストリップ（横帯）
    film_top, film_bottom = 332, 692
    painter.fillRect(QRectF(0, film_top, CANVAS, film_bottom - film_top), COLOR_FILM)

    # パーフォレーション（フィルムの送り穴）
    # 8個にすると中央に穴が来ず、分割線と重ならない
    hole_w, hole_h, hole_radius = 60, 46, 12
    hole_count = 8
    spacing = CANVAS / hole_count
    for i in range(hole_count):
        cx = spacing * (i + 0.5)
        for hy in (film_top + 22, film_bottom - 22 - hole_h):
            painter.setPen(Qt.NoPen)
            painter.setBrush(COLOR_HOLE)
            painter.drawRoundedRect(
                QRectF(cx - hole_w / 2, hy, hole_w, hole_h), hole_radius, hole_radius
            )

    # シーン領域（タイムラインの緑のセグメント、中央で分割）
    seg_top, seg_bottom = film_top + 88, film_bottom - 88
    gap = 16  # 境界線の左右に見せる隙間
    center = CANVAS / 2
    painter.fillRect(
        QRectF(0, seg_top, center - gap, seg_bottom - seg_top), COLOR_SCENE_LEFT
    )
    painter.fillRect(
        QRectF(center + gap, seg_top, CANVAS - center - gap, seg_bottom - seg_top),
        COLOR_SCENE_RIGHT,
    )

    # 分割境界線（タイムラインの黄色いマーカー）
    pen = QPen(COLOR_BOUNDARY, 20)
    painter.setPen(pen)
    painter.drawLine(QPointF(center, seg_top - 36), QPointF(center, seg_bottom + 36))

    # 境界線上部の三角ハンドル
    painter.setPen(Qt.NoPen)
    painter.setBrush(COLOR_BOUNDARY)
    handle_y = seg_top - 36
    painter.drawPolygon(QPolygonF([
        QPointF(center - 52, handle_y - 44),
        QPointF(center + 52, handle_y - 44),
        QPointF(center, handle_y + 28),
    ]))

    painter.end()
    return image


def build_icns(image: QImage, assets_dir: Path) -> Path:
    """iconsetを書き出してiconutilで.icnsを生成"""
    iconset_dir = assets_dir / "icon.iconset"
    iconset_dir.mkdir(parents=True, exist_ok=True)

    for suffix, px in ICONSET_SIZES:
        scaled = image.scaled(
            px, px, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        scaled.save(str(iconset_dir / f"icon_{suffix}.png"))

    icns_path = assets_dir / "icon.icns"
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_path)],
        check=True,
    )
    return icns_path


def main():
    project_root = Path(__file__).resolve().parent.parent
    assets_dir = project_root / "assets"

    # テキストを描画しないため QGuiApplication は不要
    # （プラットフォームプラグイン読み込みの環境問題も回避できる）
    image = draw_icon()

    preview_path = assets_dir / "icon_preview.png"
    assets_dir.mkdir(parents=True, exist_ok=True)
    image.save(str(preview_path))

    icns_path = build_icns(image, assets_dir)
    print(f"生成完了: {icns_path}")
    print(f"プレビュー: {preview_path}")


if __name__ == "__main__":
    main()
