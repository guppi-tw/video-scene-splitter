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


# OCR前処理: 拡大 + ノイズ除去 + シャープ + コントラスト強調。
# VHSのブロックフォント＋ノイズに効く。
_OCR_POST = "hqdn3d=4:3:6:4,unsharp=5:5:0.8,eq=contrast=1.2"

# 日付スタンプが映りやすい領域。スタンプは機種により下端〜画面中央付近まで
# 位置がばらつくため、下60%を広めに取り、全体OCRも併用する。
_REGION_FILTERS = [
    # 下60%（下端〜中央付近のスタンプを広くカバー）
    f"crop=iw:ih*3/5:0:ih*2/5,scale=1280:-2,{_OCR_POST}",
    # フレーム全体を高解像度化（位置に依存せず全テキストを拾う）
    "scale=1280:-2",
    # フレーム全体（ノイズ除去＋強調）
    f"scale=1280:-2,{_OCR_POST}",
]

_MIN_YEAR = 1950
_MAX_YEAR = 2099

# 区切りは句読点（. , / -）か空白、和暦区切り（年月）を1つ以上許容する。
# 古いカメラのスタンプはOCRで細い句読点が落ちて空白だけになることが多い。
_SEP_YM = r"[.,/\s\-年]+"
_SEP_MD = r"[.,/\s\-月]+"
# 4桁年が先頭: 2001.8.15 / 2001/08/15 / 1997. 7.27 / 2001年8月15日
_YMD4_RE = re.compile(
    r"(19[5-9]\d|20\d{2})" + _SEP_YM + r"(\d{1,2})" + _SEP_MD + r"(\d{1,2})"
)
# 4桁年が末尾: 8.15.2001 / 15/8/2001（空白区切りは誤検出を招くため句読点のみ）
_XXY4_RE = re.compile(
    r"\b(\d{1,2})\s*[.,/\-]\s*(\d{1,2})\s*[.,/\-]\s*(19[5-9]\d|20\d{2})\b"
)
# 2桁年が先頭: 95.8.15 / 01-8-15（空白区切りは誤検出を招くため句読点のみ）
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
        # 上位2候補まで見る（VHSの読みづらい字は2番目が正しいことがある）
        for candidate in observation.topCandidates_(2) or []:
            lines.append(str(candidate.string()))
    return lines


def _candidate_dates_in_frame(
    runner: FFmpegRunner,
    video_path: Path,
    time_sec: float,
    work_dir: Path,
    frame_id: int,
) -> list[date]:
    """1フレームを複数領域でOCRし、見つかった日付候補をすべて返す"""
    candidates: list[date] = []
    for region_index, video_filter in enumerate(_REGION_FILTERS):
        frame_path = work_dir / f"datecheck_{frame_id}_{region_index}.png"
        if not runner.extract_frame(video_path, time_sec, frame_path, video_filter):
            continue
        try:
            for line in _ocr_image_lines(frame_path):
                detected = parse_date_from_text(line)
                if detected:
                    candidates.append(detected)
        finally:
            try:
                frame_path.unlink()
            except OSError:
                pass
    return candidates


def _sample_times(start: float, end: float) -> list[float]:
    """シーン内のサンプリング時刻（遷移フレームを避け25/50/75%地点）"""
    duration = max(0.0, end - start)
    if duration <= 1.5:
        return [start + duration / 2]
    return [start + duration * r for r in (0.5, 0.25, 0.75)]


def detect_scene_dates(
    video_path: Path,
    scene_times: list[tuple[int, float, float]],
    cancel_callback: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> dict[int, date]:
    """各シーンの焼き込み日付を検出する。

    スタンプはシーン中ほぼ一定なので、複数フレーム×複数領域で読み取り、
    同じ日付が2回出たら確定（OCR誤読への保険）。一致しない場合は最多得票を採用。

    Args:
        scene_times: (シーン番号, 開始秒, 終了秒) のリスト
        progress_callback: (処理済みシーン数, 全シーン数) を受け取る

    Returns:
        {シーン番号: 検出した日付}（検出できたシーンのみ）
    """
    from collections import Counter

    runner = FFmpegRunner()
    results: dict[int, date] = {}

    with tempfile.TemporaryDirectory(prefix="vss-datecheck-") as tmp:
        work_dir = Path(tmp)

        for done, (index, start, end) in enumerate(scene_times):
            if cancel_callback is not None and cancel_callback():
                break

            votes: Counter = Counter()
            confirmed: Optional[date] = None

            for frame_id, time_sec in enumerate(_sample_times(start, end)):
                if cancel_callback is not None and cancel_callback():
                    break
                for detected in _candidate_dates_in_frame(
                    runner, video_path, time_sec, work_dir, frame_id
                ):
                    votes[detected] += 1
                    if votes[detected] >= 2:
                        confirmed = detected
                        break
                if confirmed is not None:
                    break

            if confirmed is None and votes:
                confirmed = votes.most_common(1)[0][0]
            if confirmed is not None:
                results[index] = confirmed

            if progress_callback is not None:
                progress_callback(done + 1, len(scene_times))

    return results
