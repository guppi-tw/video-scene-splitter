"""
一括処理進捗ダイアログのユニットテスト
"""
from PySide6.QtWidgets import QApplication

from app.ui.batch_progress_dialog import BatchProgressDialog


def _app():
    return QApplication.instance() or QApplication([])


def test_batch_progress_dialog_updates_status_and_progress():
    _app()
    dialog = BatchProgressDialog(3)

    dialog.set_current_message("(1/3) 検出中: sample.mp4")
    dialog.set_progress(42)
    dialog.add_result("検出完了: sample.mp4 -> 5本")

    assert dialog.summary_label.text() == "3 本の動画を順番にシーン検出しています。"
    assert dialog.current_label.text() == "(1/3) 検出中: sample.mp4"
    assert dialog.progress_bar.value() == 42
    assert "sample.mp4" in dialog.result_log.toPlainText()

    dialog.close()


def test_batch_progress_dialog_cancel_and_finish_states():
    _app()
    dialog = BatchProgressDialog(1)
    requested = []
    dialog.cancel_requested.connect(lambda: requested.append(True))

    dialog._on_cancel_clicked()

    assert requested == [True]
    assert dialog.current_label.text() == "キャンセルしています..."
    assert dialog.btn_cancel.isEnabled() is False

    dialog.set_finished("一括検出完了")

    assert dialog.current_label.text() == "一括検出完了"
    assert dialog.progress_bar.value() == 100
    assert dialog.btn_close.isEnabled() is True

    dialog.close()
