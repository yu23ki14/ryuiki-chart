"""scripts/migrate/censoring.py の単体テスト（ADR-0009・オーナー方針変更後の5分岐）。"""
import pytest

from migrate import censoring


def test_below_lod_ascii():
    c, limit = censoring.classify_censoring("<0.5")
    assert c == "below_lod"
    assert limit == 0.5


def test_not_detected():
    c, limit = censoring.classify_censoring("ND")
    assert c == "not_detected"
    assert limit is None


def test_above_lod():
    c, limit = censoring.classify_censoring(">3.2")
    assert c == "above_lod"
    assert limit == 3.2


def test_below_lod_japanese_miman():
    """`◯未満` は日本語表記の「定量下限未満」であり、意味が読める
    （detection_flag のような出典コードではない）。ASCII の `<` と同じ
    `below_lod` にし、`censoring_limit` も『未満』の直前の数値を写す。
    """
    c, limit = censoring.classify_censoring("1未満")
    assert c == "below_lod"
    assert limit == 1.0


def test_below_lod_japanese_miman_unparseable_number_raises():
    """`◯未満` の数値部分が解析できない想定外の表記は、推測せず例外を投げる
    （`<abc` と同じ扱い）。"""
    with pytest.raises(ValueError):
        censoring.classify_censoring("たくさん未満")


def test_none_for_ordinary_numeric_string():
    c, limit = censoring.classify_censoring("1.2")
    assert c == "none"
    assert limit is None


def test_none_for_none_value_raw():
    """実データでは value_raw IS NULL は0件だが、フィクスチャ向けの防御的分岐
    として none 扱いにする。"""
    c, limit = censoring.classify_censoring(None)
    assert c == "none"
    assert limit is None


def test_parse_limit_failure_raises():
    """'<' の直後が数値でない想定外の表記は、推測せず例外を投げる。"""
    with pytest.raises(ValueError):
        censoring.classify_censoring("<abc")


def test_resolve_value_num_only_for_none_censoring():
    """D2: value_num は censoring='none' のときだけ measurements.value を運ぶ。
    それ以外は（v1 の格納値が 0.0 であっても）NULL にする——ADR-0009 決定1。
    """
    assert censoring.resolve_value_num("none", 1.2) == 1.2
    assert censoring.resolve_value_num("below_lod", 0.0) is None
    assert censoring.resolve_value_num("not_detected", 0.0) is None
    assert censoring.resolve_value_num("above_lod", None) is None
    assert censoring.resolve_value_num("unknown", None) is None
