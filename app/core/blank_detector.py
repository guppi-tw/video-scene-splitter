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


def _scene_blank_segments(
    runner: FFmpegRunner,
    video_path: Path,
    start: float,
    end: float,
    work_dir: Path,
    std_threshold: float,
    step: float = 0.5,
    min_run: float = 1.0,
) -> list[tuple[float, float, str]]:
    """シーン [start, end] 内の単色区間（時間範囲）を返す。

    シーン全体が一色ならその全体を返す。そうでなければ、先頭と末尾に
    一色が min_run 秒以上続くリードイン／アウトを検出して返す。映像と
    映像の間の青／黒画面は、こうしてシーンの端に現れることが多い。
    """
    from collections import Counter

    duration = end - start
    if duration <= 0:
        return []

    counter = 0

    def label_at(t: float) -> Optional[str]:
        nonlocal counter
        counter += 1
        frame_path = work_dir / f"blank_{int(round(start * 1000))}_{counter}.png"
        if not runner.extract_frame(video_path, t, frame_path, _DOWNSCALE_FILTER):
            return None
        try:
            stats = _frame_stats(frame_path)
        finally:
            try:
                frame_path.unlink()
            except OSError:
                pass
        return classify_blank(*stats, std_threshold=std_threshold) if stats else None

    # シーン全体が一色か（25/50/75%地点で確認）
    whole = [label_at(t) for t in _sample_times(start, end)]
    if whole and all(label is not None for label in whole):
        label = Counter(whole).most_common(1)[0][0]
        return [(start, end, label)]

    segments: list[tuple[float, float, str]] = []

    # シーン端ちょうどのフレームはシーク直後で不安定なことがあるため、
    # わずかに内側から走査を始める（青が0.3秒目から始まる等を取りこぼさない）。
    offset = min(0.3, duration / 4)

    # 先頭の一色ラン（最初に映像が現れるまで前進）
    last_uniform = None
    lead_label = None
    t = start + offset
    while t < end:
        label = label_at(t)
        if label is None:
            break
        last_uniform, lead_label = t, label
        t += step
    if last_uniform is not None and (last_uniform - start) + step >= min_run:
        inner = min(end, last_uniform + step / 2)
        segments.append((start, inner, lead_label))

    # 末尾の一色ラン（末尾から後退）
    last_uniform = None
    trail_label = None
    t = end - offset
    while t > start:
        label = label_at(t)
        if label is None:
            break
        last_uniform, trail_label = t, label
        t -= step
    if last_uniform is not None and (end - last_uniform) + step >= min_run:
        inner = max(start, last_uniform - step / 2)
        # 先頭ランと重なる場合は追加しない
        if not segments or inner > segments[0][1]:
            segments.append((inner, end, trail_label))

    return segments


def detect_blank_segments(
    video_path: Path,
    scene_times: list[tuple[int, float, float]],
    cancel_callback: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    std_threshold: float = _DEFAULT_STD_THRESHOLD,
) -> list[tuple[float, float, str]]:
    """単色のつなぎ目区間（時間範囲）を検出する。

    シーン全体が一色の場合だけでなく、シーン先頭／末尾の一色リードイン・
    アウトも検出する。映像の冒頭に残る青画面などを切り出すために使う。

    Returns:
        [(開始秒, 終了秒, ラベル)] のリスト（時間順）
    """
    runner = FFmpegRunner()
    segments: list[tuple[float, float, str]] = []

    import tempfile

    with tempfile.TemporaryDirectory(prefix="vss-blankcheck-") as tmp:
        work_dir = Path(tmp)

        for done, (_index, start, end) in enumerate(scene_times):
            if cancel_callback is not None and cancel_callback():
                break

            segments.extend(
                _scene_blank_segments(
                    runner, video_path, start, end, work_dir, std_threshold
                )
            )

            if progress_callback is not None:
                progress_callback(done + 1, len(scene_times))

    return segments
