"""scripts/migrate/occurrence_period.py の単体テスト（O-1 設計 v2 D1）。"""
import pytest

from migrate import occurrence_period as op


def _shape(name, length, grain, expected_row_count=None, note="テスト用"):
    return op.PeriodShape(
        name=name, length=length, period_grain=grain,
        expected_row_count=expected_row_count, note=note,
    )


_PERIOD_GRAIN_BY_NAME = {
    "year": "year", "month": "month", "year_interval": "survey_period", "day": "day",
    "month_interval": "survey_period", "instant_minute": "instant", "instant_minute_z": "instant",
    "instant_second": "instant", "instant_second_z": "instant", "day_interval": "survey_period",
    "instant_millisecond_z": "instant", "instant_minute_z_interval": "survey_period",
}


@pytest.fixture()
def shapes() -> dict:
    return {name: _shape(name, length, _PERIOD_GRAIN_BY_NAME[name]) for name, (length, _pat) in op._SHAPE_DEFS.items()}


# ---------------------------------------------------------------------------
# classify_shape
# ---------------------------------------------------------------------------

def test_classify_shape_all_twelve_forms(shapes):
    cases = {
        "2020": "year",
        "2020-01": "month",
        "1990/1991": "year_interval",
        "2020-01-05": "day",
        "2012-08/2013-06": "month_interval",
        "2020-01-05T12:30": "instant_minute",
        "2020-01-05T12:30Z": "instant_minute_z",
        "2020-01-05T12:30:00": "instant_second",
        "2020-01-05T12:30:00Z": "instant_second_z",
        "2020-01-05/2020-01-06": "day_interval",
        "2020-01-05T12:30:00.123Z": "instant_millisecond_z",
        "2020-01-05T12:30Z/2020-01-06T12:30Z": "instant_minute_z_interval",
    }
    for value, expected_shape in cases.items():
        assert op.classify_shape(value, shapes) == expected_shape


def test_classify_shape_unknown_length_raises(shapes):
    with pytest.raises(op.UnknownPeriodShapeError):
        op.classify_shape("abc", shapes)


def test_classify_shape_matching_length_but_bad_pattern_raises(shapes):
    """長さは10桁で 'day' と一致するが、区切りがスラッシュで形が崩れている
    （宣言外の想定外パターン）。"""
    with pytest.raises(op.UnknownPeriodShapeError):
        op.classify_shape("2020/01/05", shapes)


def test_classify_shape_code_knows_shape_but_not_declared_raises():
    """コード側（_SHAPE_DEFS）には形があるが、宣言表（呼び出し側が渡す
    `shapes`）に無い場合は `UndeclaredPeriodShapeError`。"""
    with pytest.raises(op.UndeclaredPeriodShapeError):
        op.classify_shape("2020-01-05", {})


# ---------------------------------------------------------------------------
# expand_period: 非区間・非Z
# ---------------------------------------------------------------------------

def test_expand_year(shapes):
    result = op.expand_period("2020", shapes, "+09:00")
    assert (result.shape, result.period_grain, result.period_start, result.period_end) == (
        "year", "year", "2020-01-01", "2020-12-31",
    )
    assert not result.day_changed and not result.month_changed


def test_expand_month(shapes):
    result = op.expand_period("2020-02", shapes, "+09:00")
    assert (result.period_start, result.period_end) == ("2020-02-01", "2020-02-29")  # うるう年


def test_expand_day(shapes):
    result = op.expand_period("2020-01-05", shapes, "+09:00")
    assert (result.period_grain, result.period_start, result.period_end) == ("day", "2020-01-05", "2020-01-05")


def test_expand_instant_minute_appends_seconds_no_conversion(shapes):
    result = op.expand_period("2020-01-05T12:30", shapes, "+09:00")
    assert (result.period_grain, result.period_start, result.period_end) == (
        "instant", "2020-01-05T12:30:00", "2020-01-05T12:30:00",
    )


def test_expand_instant_second_passthrough_no_conversion(shapes):
    result = op.expand_period("2020-01-05T12:30:45", shapes, "+09:00")
    assert (result.period_start, result.period_end) == ("2020-01-05T12:30:45", "2020-01-05T12:30:45")


# ---------------------------------------------------------------------------
# expand_period: 区間（非Z）
# ---------------------------------------------------------------------------

def test_expand_year_interval(shapes):
    result = op.expand_period("1990/1992", shapes, "+09:00")
    assert (result.period_grain, result.period_start, result.period_end) == (
        "survey_period", "1990-01-01", "1992-12-31",
    )


def test_expand_month_interval(shapes):
    result = op.expand_period("2012-08/2013-06", shapes, "+09:00")
    assert (result.period_start, result.period_end) == ("2012-08-01", "2013-06-30")


def test_expand_day_interval(shapes):
    result = op.expand_period("2019-08-01/2019-08-31", shapes, "+09:00")
    assert (result.period_grain, result.period_start, result.period_end) == (
        "survey_period", "2019-08-01", "2019-08-31",
    )


# ---------------------------------------------------------------------------
# expand_period: 'Z' 変換（ADR-0024）
# ---------------------------------------------------------------------------

def test_expand_instant_minute_z_converts_with_utc_offset(shapes):
    """+09:00 を加えるので 05:10Z -> 14:10（ローカル）。"""
    result = op.expand_period("2021-01-31T05:10Z", shapes, "+09:00")
    assert (result.period_grain, result.period_start, result.period_end) == (
        "instant", "2021-01-31T14:10:00", "2021-01-31T14:10:00",
    )
    assert not result.day_changed


def test_expand_instant_minute_z_day_changes(shapes):
    """23:00Z + 9h -> 翌日08:00（ローカル）。day_changed=True, month_changed=False。"""
    result = op.expand_period("2021-01-30T23:00Z", shapes, "+09:00")
    assert result.period_start == "2021-01-31T08:00:00"
    assert result.day_changed is True
    assert result.month_changed is False


def test_expand_instant_minute_z_month_changes(shapes):
    """月末の23:00Z + 9h -> 翌月扱いになるケース。"""
    result = op.expand_period("2021-01-31T23:00Z", shapes, "+09:00")
    assert result.period_start == "2021-02-01T08:00:00"
    assert result.day_changed is True
    assert result.month_changed is True


def test_expand_instant_second_z(shapes):
    result = op.expand_period("2021-02-23T05:18:04Z", shapes, "+09:00")
    assert result.period_start == "2021-02-23T14:18:04"


def test_expand_instant_millisecond_z_truncates_ms(shapes):
    """ミリ秒は切り捨ててから変換する（design v2 D1）。"""
    result = op.expand_period("2022-01-04T03:28:34.188Z", shapes, "+09:00")
    assert result.period_start == "2022-01-04T12:28:34"


def test_expand_instant_minute_z_interval_converts_both_ends(shapes):
    result = op.expand_period("1910-03-01T00:00Z/1910-03-31T00:00Z", shapes, "+09:00")
    assert (result.period_grain, result.period_start, result.period_end) == (
        "survey_period", "1910-03-01T09:00:00", "1910-03-31T09:00:00",
    )


def test_expand_instant_minute_z_negative_offset(shapes):
    """region の utc_offset が負のときも減算できる（将来別地域を足したとき用の
    防御。実データでは +09:00 しか出ないが、utc_offset をハードコードしない
    設計の確認）。"""
    result = op.expand_period("2021-01-31T05:10Z", shapes, "-05:00")
    assert result.period_start == "2021-01-31T00:10:00"


# ---------------------------------------------------------------------------
# 年不変の機械検証（D3の前提）
# ---------------------------------------------------------------------------

def test_year_boundary_crossed_raises(shapes):
    """UTC 12/31 深夜の観測に +09:00 すると年が変わる。D3の前提が破れるので
    即座に止まる。"""
    with pytest.raises(op.YearBoundaryCrossedError):
        op.expand_period("2020-12-31T16:30Z", shapes, "+09:00")


def test_year_boundary_not_crossed_for_normal_case(shapes):
    """年内に収まる変換は例外を投げない。"""
    result = op.expand_period("2020-12-31T10:00Z", shapes, "+09:00")
    assert result.period_start.startswith("2020-12-31")


# ---------------------------------------------------------------------------
# 宣言表（occurrence_period_shapes.yaml）の読み込み・構造検証
# ---------------------------------------------------------------------------

def test_load_period_shapes_from_yaml(tmp_path):
    yaml_path = tmp_path / "shapes.yaml"
    yaml_path.write_text(
        "day:\n"
        "  length: 10\n"
        "  period_grain: day\n"
        "  expected_row_count: 5\n"
        "  note: テスト\n",
        encoding="utf-8",
    )
    shapes = op.load_period_shapes(yaml_path)
    assert set(shapes) == {"day"}
    assert shapes["day"].length == 10
    assert shapes["day"].expected_row_count == 5


def test_load_period_shapes_missing_file_returns_empty(tmp_path):
    assert op.load_period_shapes(tmp_path / "does_not_exist.yaml") == {}


def test_validate_occurrence_period_shapes_shape_accepts_complete_entry(tmp_path):
    yaml_path = tmp_path / "shapes.yaml"
    yaml_path.write_text(
        "day:\n  length: 10\n  period_grain: day\n  expected_row_count: 1\n  note: テスト\n",
        encoding="utf-8",
    )
    op.validate_occurrence_period_shapes_shape(yaml_path)  # 例外を投げなければ良い


def test_validate_occurrence_period_shapes_shape_rejects_missing_required_key(tmp_path):
    yaml_path = tmp_path / "shapes.yaml"
    yaml_path.write_text("day:\n  length: 10\n  period_grain: day\n", encoding="utf-8")
    with pytest.raises(op.MigrationError, match="day"):
        op.validate_occurrence_period_shapes_shape(yaml_path)


# ---------------------------------------------------------------------------
# PeriodShapeUsage（未使用宣言・件数不一致の検出）
# ---------------------------------------------------------------------------

def test_period_shape_usage_reports_unused_and_mismatched(shapes):
    day_shape = _shape("day", 10, "day", expected_row_count=3)
    usage = op.PeriodShapeUsage({"day": day_shape})
    assert usage.unused_entries() == ["day"]
    usage.mark_used("day")
    assert usage.unused_entries() == []
    assert usage.mismatched_expected_counts() == {"day": (3, 1)}
