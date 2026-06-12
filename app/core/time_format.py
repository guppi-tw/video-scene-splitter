"""
時間表示のフォーマット
"""


def format_seconds(seconds: float) -> str:
    """秒を M:SS（1時間以上は H:MM:SS）形式に変換"""
    total_sec = int(seconds)
    m, s = divmod(total_sec, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_ms_tenths(ms: int) -> str:
    """ミリ秒を MM:SS.f（1時間以上は HH:MM:SS.f）形式に変換"""
    tenths = (ms % 1000) // 100
    total_sec = ms // 1000
    m, s = divmod(total_sec, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}.{tenths}"
    return f"{m:02d}:{s:02d}.{tenths}"
