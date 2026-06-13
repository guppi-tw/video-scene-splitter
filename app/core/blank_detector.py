"""
単色（青一色・黒一色）のつなぎ目シーンの検出

昔のテープでは映像と映像の間に、無信号の青画面や黒画面・白画面が入ることが多い。
シーンごとにフレームを縮小してばらつき（標準偏差）を測り、ほぼ一色なら
つなぎ目と判定する。色の平均から「青」「黒」「白」「単色」をラベル付けする。
"""
import logging
from pathlib import Path
from typing import Callable, Optional

from app.core.ffmpeg_runner import FFmpegRunner

logger = logging.getLogger(__name__)

# 縮小サイズ（ノイズを平均化しつつ構造は残す）。area縮小で平滑化する。
_DOWNSCALE_FILTER = "scale=32:32:flags=area"
# 縮小後のチャンネル標準偏差がこれ未満なら「一色」とみなす（0-255）
_DEFAULT_STD_THRESHOLD = 22.0


def classify_blank(
    channel_std_max: float,
    mean_b: float,
    mean_g: float,
    mean_r: float,
    std_threshold: float = _DEFAULT_STD_THRESHOLD,
) -> Optional[str]:
    """縮小フレームの統計から単色ラベルを返す（一色でなければNone）。

    引数は BGR（OpenCVの順）の平均値。
    """
    if channel_std_max > std_threshold:
        return None

    # 純粋な青は輝度が低い（約29）ため、黒より先に青を判定する
    if mean_b > mean_g + 20 and mean_b > mean_r + 20:
        return "青"

    mean_luma = 0.114 * mean_b + 0.587 * mean_g + 0.299 * mean_r
    if mean_luma < 40:
        return "黒"
    if mean_luma > 210:
        return "白"
    return "単色"


def _frame_stats(frame_path: Path) -> Optional[tuple[float, float, float, float]]:
    """縮小フレームを読み、(最大チャンネル標準偏差, B平均, G平均, R平均) を返す"""
    try:
        import cv2
    except ImportError:
        logger.warning("OpenCV(cv2)が無いため単色判定をスキップします")
        return None

    img = cv2.imread(str(frame_path))
    if img is None:
        return None

    pixels = img.reshape(-1, img.shape[-1]).astype("float32")
    std_max = float(pixels.std(axis=0).max())
    means = pixels.mean(axis=0)  # B, G, R
    return std_max, float(means[0]), float(means[1]), float(means[2])


def _sample_times(start: float, end: float) -> list[float]:
    """シーン内のサンプリング時刻（遷移フレームを避け中央・25%・75%）"""
    duration = max(0.0, end - start)
    if duration <= 1.5:
        return [start + duration / 2]
    return [start + duration * r for r in (0.5, 0.25, 0.75)]


def detect_blank_scenes(
    video_path: Path,
    scene_times: list[tuple[int, float, float]],
    cancel_callback: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    std_threshold: float = _DEFAULT_STD_THRESHOLD,
) -> dict[int, str]:
    """単色のつなぎ目シーンを検出する。

    各シーンの複数フレームを調べ、サンプルした全フレームが一色のときだけ
    つなぎ目と判定する（実映像の単調なカットを誤検出しないため）。

    Returns:
        {シーン番号: ラベル（"青"/"黒"/"単色"）}（つなぎ目のみ）
    """
    from collections import Counter

    runner = FFmpegRunner()
    results: dict[int, str] = {}

    import tempfile

    with tempfile.TemporaryDirectory(prefix="vss-blankcheck-") as tmp:
        work_dir = Path(tmp)

        for done, (index, start, end) in enumerate(scene_times):
            if cancel_callback is not None and cancel_callback():
                break

            labels: list[Optional[str]] = []
            for frame_id, time_sec in enumerate(_sample_times(start, end)):
                if cancel_callback is not None and cancel_callback():
                    break
                frame_path = work_dir / f"blank_{index}_{frame_id}.png"
                if not runner.extract_frame(
                    video_path, time_sec, frame_path, _DOWNSCALE_FILTER
                ):
                    continue
                try:
                    stats = _frame_stats(frame_path)
                finally:
                    try:
                        frame_path.unlink()
                    except OSError:
                        pass
                if stats is None:
                    continue
                labels.append(classify_blank(*stats, std_threshold=std_threshold))

            # サンプルした全フレームが一色のときのみ「つなぎ目」とする
            if labels and all(label is not None for label in labels):
                results[index] = Counter(labels).most_common(1)[0][0]

            if progress_callback is not None:
                progress_callback(done + 1, len(scene_times))

    return results
