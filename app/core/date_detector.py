"""
焼き込み日付の検出

昔のビデオカメラが映像に焼き込んだ日付スタンプ（例: 2001. 8.15）を
OCR（macOS Visionフレームワーク）で読み取り、撮影日として利用する。
"""
import logging
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from app.core.ffmpeg_runner import FFmpegRunner

logger = logging.getLogger(__name__)


class DateDetectionUnavailableError(RuntimeError):
    """OCRバックエンド（macOS Vision）が利用できない場合に送出"""


# 日付スタンプが映りやすい領域。クロップ + 拡大でOCR精度を上げる
_REGION_FILTERS = [
    # 下1/3（右下・左下のスタンプをカバー）
    "crop=iw:ih/3:0:2*ih/3,scale=iw*3:-2",
    # 上1/3
    "crop=iw:ih/3:0:0,scale=iw*3:-2",
    # フレーム全体（フォールバック）
    None,
]

_MIN_YEAR = 1950
_MAX_YEAR = 2099

# 4桁年が先頭: 2001.8.15 / 2001/08/15 / 2001-8-15 / 2001年8月15日
_YMD4_RE = re.compile(
    r"(19[5-9]\d|20\d{2})\s*[.,/\-年]\s*(\d{1,2})\s*[.,/\-月]\s*(\d{1,2})"
)
# 4桁年が末尾: 8.15.2001 / 15/8/2001
_XXY4_RE = re.compile(
    r"\b(\d{1,2})\s*[.,/\-]\s*(\d{1,2})\s*[.,/\-]\s*(19[5-9]\d|20\d{2})\b"
)
# 2桁年が先頭: 95.8.15 / 01-8-15
_YMD2_RE = re.compile(
    r"\b(\d{2})\s*[.,/\-]\s*(\d{1,2})\s*[.,/\-]\s*(\d{1,2})\b"
)


def _make_date(year: int, month: int, day: int) -> Optional[date]:
    if not (_MIN_YEAR <= year <= _MAX_YEAR):
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_date_from_text(text: str) -> Optional[date]:
    """OCRで読み取ったテキストから日付を抽出する。

    対応形式（優先順）:
    1. 4桁年が先頭: 2001.8.15 / 2001/08/15 / 2001年8月15日
    2. 4桁年が末尾: 8.15.2001（月日年）/ 15.8.2001（日月年）
       — どちらか一方だけ有効な解釈ならそれを採用、両方有効なら月日年を優先
    3. 2桁年が先頭: 95.8.15（50以上は19xx、未満は20xx）
    """
    m = _YMD4_RE.search(text)
    if m:
        result = _make_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if result:
            return result

    m = _XXY4_RE.search(text)
    if m:
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        mdy = _make_date(year, a, b)
        dmy = _make_date(year, b, a)
        if mdy and not dmy:
            return mdy
        if dmy and not mdy:
            return dmy
        if mdy:
            return mdy

    m = _YMD2_RE.search(text)
    if m:
        yy = int(m.group(1))
        year = 1900 + yy if yy >= 50 else 2000 + yy
        result = _make_date(year, int(m.group(2)), int(m.group(3)))
        if result:
            return result

    return None


def _ocr_image_lines(image_path: Path) -> list[str]:
    """画像内のテキスト行をOCRで読み取る（macOS Vision使用）"""
    try:
        import Vision
        from Foundation import NSURL
    except ImportError as exc:
        raise DateDetectionUnavailableError(
            "日付検出にはmacOSのVisionフレームワークが必要です。\n"
            "requirements.txt を再インストールしてください。\n"
            f"詳細: {exc}"
        ) from exc

    url = NSURL.fileURLWithPath_(str(image_path))
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    # 日付スタンプは自然言語ではないため言語補正は無効化
    request.setUsesLanguageCorrection_(False)

    ok, _error = handler.performRequests_error_([request], None)
    if not ok:
        return []

    lines = []
    for observation in request.results() or []:
        candidates = observation.topCandidates_(1)
        if candidates:
            lines.append(str(candidates[0].string()))
    return lines


def detect_date_at_time(
    runner: FFmpegRunner,
    video_path: Path,
    time_sec: float,
    work_dir: Path,
) -> Optional[date]:
    """指定時刻のフレームから焼き込み日付を検出する"""
    for region_index, video_filter in enumerate(_REGION_FILTERS):
        frame_path = work_dir / f"datecheck_{int(time_sec * 1000)}_{region_index}.jpg"
        if not runner.extract_frame(video_path, time_sec, frame_path, video_filter):
            continue
        try:
            for line in _ocr_image_lines(frame_path):
                detected = parse_date_from_text(line)
                if detected:
                    return detected
        finally:
            try:
                frame_path.unlink()
            except OSError:
                pass
    return None


def detect_scene_dates(
    video_path: Path,
    scene_times: list[tuple[int, float, float]],
    cancel_callback: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> dict[int, date]:
    """各シーンの焼き込み日付を検出する。

    Args:
        scene_times: (シーン番号, 開始秒, 終了秒) のリスト
        progress_callback: (処理済みシーン数, 全シーン数) を受け取る

    Returns:
        {シーン番号: 検出した日付}（検出できたシーンのみ）
    """
    runner = FFmpegRunner()
    results: dict[int, date] = {}

    with tempfile.TemporaryDirectory(prefix="vss-datecheck-") as tmp:
        work_dir = Path(tmp)

        for done, (index, start, end) in enumerate(scene_times):
            if cancel_callback is not None and cancel_callback():
                break

            duration = max(0.0, end - start)
            # スタンプはシーン中ほぼ一定なので、序盤と中間の2点を試す
            sample_times = [start + min(0.5, duration / 2)]
            if duration > 2.0:
                sample_times.append(start + duration / 2)

            for time_sec in sample_times:
                if cancel_callback is not None and cancel_callback():
                    break
                detected = detect_date_at_time(runner, video_path, time_sec, work_dir)
                if detected:
                    results[index] = detected
                    break

            if progress_callback is not None:
                progress_callback(done + 1, len(scene_times))

    return results
