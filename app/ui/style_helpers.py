"""UIの視覚的な優先度を一貫して切り替える補助関数。"""

from PySide6.QtWidgets import QPushButton


def set_recommended_action(button: QPushButton, recommended: bool) -> None:
    """既存ボタンを「次におすすめの操作」として強調する。"""
    recommended = bool(recommended)
    if button.property("recommended") is recommended:
        return
    button.setProperty("recommended", recommended)
    button.setAccessibleDescription(
        "おすすめの次の操作" if recommended else ""
    )
    button.style().unpolish(button)
    button.style().polish(button)
    button.update()
