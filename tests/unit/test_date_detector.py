from datetime import date

from app.core.date_detector import infer_missing_dates, parse_date_from_text


def test_infer_fills_gap_between_equal_neighbours():
    detected = {1: date(1997, 1, 1), 3: date(1997, 1, 1)}
    # シーン2は前後が同じ → 1997-01-01 で補完
    assert infer_missing_dates([1, 2, 3], detected) == {2: date(1997, 1, 1)}


def test_infer_carries_previous_date_forward():
    detected = {1: date(1997, 2, 15), 3: date(1997, 2, 16)}
    # シーン2は直前の日付を引き継ぐ
    assert infer_missing_dates([1, 2, 3], detected) == {2: date(1997, 2, 15)}


def test_infer_backfills_leading_gap():
    detected = {3: date(1997, 5, 6)}
    # 先頭側の欠損は直後の検出済み日付で補う
    assert infer_missing_dates([1, 2, 3], detected) == {
        1: date(1997, 5, 6),
        2: date(1997, 5, 6),
    }


def test_infer_forward_fills_trailing_gap():
    detected = {1: date(1997, 5, 6)}
    # 末尾の欠損は直前の日付を引き継ぐ
    assert infer_missing_dates([1, 2, 3], detected) == {
        2: date(1997, 5, 6),
        3: date(1997, 5, 6),
    }


def test_infer_returns_empty_without_any_detection():
    assert infer_missing_dates([1, 2, 3], {}) == {}


def test_infer_does_not_override_detected():
    detected = {1: date(1997, 1, 1), 2: date(1997, 2, 2), 3: date(1997, 3, 3)}
    # 全て検出済み → 補完なし
    assert infer_missing_dates([1, 2, 3], detected) == {}


def test_parse_ymd_with_dots():
    assert parse_date_from_text("2001.8.15") == date(2001, 8, 15)


def test_parse_ymd_with_padded_spaces():
    # 昔のビデオカメラは桁をスペースで揃えることが多い
    assert parse_date_from_text("2001. 8.15") == date(2001, 8, 15)


def test_parse_vhs_stamp_with_space_before_month():
    # 実機VHSの例: "1997. 7.27"（月の前にスペース）
    assert parse_date_from_text("1997. 7.27") == date(1997, 7, 27)


def test_parse_single_digit_month_and_day():
    # 時計リセット時のデフォルト "1997. 1. 1"（行復元後の連結文字列）
    assert parse_date_from_text("1997. 1. 1") == date(1997, 1, 1)


def test_parse_date_line_with_trailing_time():
    # 行復元で日付行に時刻が続いても日付部分を取る
    assert parse_date_from_text("1997. 1. 1 AM 9:59") == date(1997, 1, 1)


def test_parse_ymd_with_space_only_separators():
    # OCRが細い句読点を落として空白だけになるケース
    assert parse_date_from_text("1997 7 27") == date(1997, 7, 27)


def test_time_line_is_not_parsed_as_date():
    # 日付の下に出る時刻 "PM 5:27" を日付と誤認しない
    assert parse_date_from_text("PM 5:27") is None


def test_parse_ymd_with_slashes():
    assert parse_date_from_text("1995/12/24") == date(1995, 12, 24)


def test_parse_japanese_format():
    assert parse_date_from_text("2001年8月15日") == date(2001, 8, 15)


def test_parse_mdy_with_4digit_year():
    assert parse_date_from_text("8.15.2001") == date(2001, 8, 15)


def test_parse_dmy_when_mdy_invalid():
    # 15は月として無効なので日月年と解釈される
    assert parse_date_from_text("15.8.2001") == date(2001, 8, 15)


def test_parse_2digit_year_1900s():
    assert parse_date_from_text("95.8.15") == date(1995, 8, 15)


def test_parse_2digit_year_2000s():
    assert parse_date_from_text("01.8.15") == date(2001, 8, 15)


def test_parse_embedded_in_other_text():
    assert parse_date_from_text("REC 2001.8.15 PM 3:00") == date(2001, 8, 15)


def test_parse_rejects_invalid_date():
    assert parse_date_from_text("2001.13.45") is None


def test_parse_rejects_out_of_range_year():
    assert parse_date_from_text("2150.1.1") is None


def test_parse_rejects_plain_text():
    assert parse_date_from_text("こんにちは") is None
    assert parse_date_from_text("") is None


def test_parse_rejects_timecode_like():
    # タイムコード 00:12:34 を日付と誤認しない
    assert parse_date_from_text("00:12:34") is None
