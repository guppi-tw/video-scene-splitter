from app.core.blank_detector import classify_blank


def test_classify_black_frame():
    # 低輝度・低分散 → 黒
    assert classify_blank(5.0, 8.0, 8.0, 8.0) == "黒"


def test_classify_blue_frame():
    # 青が突出・低分散 → 青
    assert classify_blank(6.0, 180.0, 60.0, 40.0) == "青"


def test_classify_white_frame():
    # 高輝度・低分散 → 白
    assert classify_blank(6.0, 245.0, 245.0, 245.0) == "白"


def test_classify_uniform_other_color():
    # 一色だが青でも黒でも白でもない（緑がかった灰）→ 単色
    assert classify_blank(7.0, 120.0, 150.0, 120.0) == "単色"


def test_high_variance_is_not_blank():
    # 分散が大きい（実映像）→ None
    assert classify_blank(60.0, 100.0, 100.0, 100.0) is None


def test_threshold_boundary():
    assert classify_blank(22.0, 10.0, 10.0, 10.0) is not None
    assert classify_blank(22.1, 10.0, 10.0, 10.0) is None
