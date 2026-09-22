"""scripts/migrate/occurrence_period.py の単体テスト（O-1 設計 v2 D1）。"""
import pytest

from migrate import occurrence_period as op
from migrate import period


# ---------------------------------------------------------------------------
# classify_shape
# ---------------------------------------------------------------------------

def test_classify_shape_all_twelve_forms():
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
        assert op.classify_shape(value) == expected_shape


def test_classify_shape_unknown_length_raises():
    with pytest.raises(op.UnknownPeriodShapeError):
        op.classify_shape("abc")


def test_classify_shape_matching_length_but_bad_pattern_raises():
    """長さは10桁で 'day' と一致するが、区切りがスラッシュで形が崩れている
    （宣言外の想定外パターン）。"""
    with pytest.raises(op.UnknownPeriodShapeError):
        op.classify_shape("2020/01/05")


def test_classify_shape_error_includes_record_id():
    with pytest.raises(op.UnknownPeriodShapeError, match="rec-123"):
        op.classify_shape("abc", record_id="rec-123")


def test_classify_shape_rejects_fullwidth_digits():
    """`\\d` ではなく `[0-9]` を使う（コードレビュー指摘2）: 全角数字は
    Python の `re` の `\\d`（既定は Unicode）だと誤ってマッチしうるが、
    `_SHAPE_DEFS` は `[0-9]` なので弾く。"""
    with pytest.raises(op.UnknownPeriodShapeError):
        op.classify_shape("２０２０")  # 全角の "2020"


# ---------------------------------------------------------------------------
# expand_period: 非区間・非Z
# ---------------------------------------------------------------------------

def test_expand_year():
    result = op.expand_period("2020", "+09:00")
    assert (result.shape, result.period_grain, result.period_start, result.period_end) == (
        "year", "year", "2020-01-01", "2020-12-31",
    )
    assert not result.day_changed and not result.month_changed


def test_expand_month():
    result = op.expand_period("2020-02", "+09:00")
    assert (result.period_start, result.period_end) == ("2020-02-01", "2020-02-29")  # うるう年


def test_expand_day():
    result = op.expand_period("2020-01-05", "+09:00")
    assert (result.period_grain, result.period_start, result.period_end) == ("day", "2020-01-05", "2020-01-05")


def test_expand_instant_minute_appends_seconds_no_conversion():
    result = op.expand_period("2020-01-05T12:30", "+09:00")
    assert (result.period_grain, result.period_start, result.period_end) == (
        "instant", "2020-01-05T12:30:00", "2020-01-05T12:30:00",
    )


def test_expand_instant_second_passthrough_no_conversion():
    result = op.expand_period("2020-01-05T12:30:45", "+09:00")
    assert (result.period_start, result.period_end) == ("2020-01-05T12:30:45", "2020-01-05T12:30:45")


# ---------------------------------------------------------------------------
# expand_period: 区間（非Z）
# ---------------------------------------------------------------------------

def test_expand_year_interval():
    result = op.expand_period("1990/1992", "+09:00")
    assert (result.period_grain, result.period_start, result.period_end) == (
        "survey_period", "1990-01-01", "1992-12-31",
    )


def test_expand_month_interval():
    result = op.expand_period("2012-08/2013-06", "+09:00")
    assert (result.period_start, result.period_end) == ("2012-08-01", "2013-06-30")


def test_expand_day_interval():
    result = op.expand_period("2019-08-01/2019-08-31", "+09:00")
    assert (result.period_grain, result.period_start, result.period_end) == (
        "survey_period", "2019-08-01", "2019-08-31",
    )


# ---------------------------------------------------------------------------
# expand_period: 'Z' 変換（ADR-0024）
# ---------------------------------------------------------------------------

def test_expand_instant_minute_z_converts_with_utc_offset():
    """+09:00 を加えるので 05:10Z -> 14:10（ローカル）。"""
    result = op.expand_period("2021-01-31T05:10Z", "+09:00")
    assert (result.period_grain, result.period_start, result.period_end) == (
        "instant", "2021-01-31T14:10:00", "2021-01-31T14:10:00",
    )
    assert not result.day_changed


def test_expand_instant_minute_z_day_changes():
    """23:00Z + 9h -> 翌日08:00（ローカル）。day_changed=True, month_changed=False。"""
    result = op.expand_period("2021-01-30T23:00Z", "+09:00")
    assert result.period_start == "2021-01-31T08:00:00"
    assert result.day_changed is True
    assert result.month_changed is False


def test_expand_instant_minute_z_month_changes():
    """月末の23:00Z + 9h -> 翌月扱いになるケース。"""
    result = op.expand_period("2021-01-31T23:00Z", "+09:00")
    assert result.period_start == "2021-02-01T08:00:00"
    assert result.day_changed is True
    assert result.month_changed is True


def test_expand_instant_second_z():
    result = op.expand_period("2021-02-23T05:18:04Z", "+09:00")
    assert result.period_start == "2021-02-23T14:18:04"


def test_expand_instant_millisecond_z_truncates_ms():
    """ミリ秒は切り捨ててから変換する（design v2 D1）。"""
    result = op.expand_period("2022-01-04T03:28:34.188Z", "+09:00")
    assert result.period_start == "2022-01-04T12:28:34"


def test_expand_instant_minute_z_interval_converts_both_ends():
    result = op.expand_period("1910-03-01T00:00Z/1910-03-31T00:00Z", "+09:00")
    assert (result.period_grain, result.period_start, result.period_end) == (
        "survey_period", "1910-03-01T09:00:00", "1910-03-31T09:00:00",
    )


def test_expand_instant_minute_z_negative_offset():
    """region の utc_offset が負のときも減算できる（将来別地域を足したとき用の
    防御。実データでは +09:00 しか出ないが、utc_offset をハードコードしない
    設計の確認）。"""
    result = op.expand_period("2021-01-31T05:10Z", "-05:00")
    assert result.period_start == "2021-01-31T00:10:00"


# ---------------------------------------------------------------------------
# 実在する日付・時刻としての検証（コードレビュー指摘3）
# ---------------------------------------------------------------------------

def test_expand_day_rejects_nonexistent_date():
    with pytest.raises(op.InvalidPeriodValueError, match="2020-02-30"):
        op.expand_period("2020-02-30", "+09:00")


def test_expand_month_rejects_month_13():
    with pytest.raises(op.InvalidPeriodValueError):
        op.expand_period("2020-13", "+09:00")


def test_expand_instant_rejects_hour_24():
    with pytest.raises(op.InvalidPeriodValueError):
        op.expand_period("2020-01-01T24:00", "+09:00")


def test_expand_day_interval_rejects_nonexistent_end_date():
    """区間の**両端**を検証する（開始日は実在するが終了日が実在しない）。"""
    with pytest.raises(op.InvalidPeriodValueError):
        op.expand_period("2020-01-05/2020-02-30", "+09:00")


def test_expand_instant_minute_z_rejects_hour_24():
    with pytest.raises(op.InvalidPeriodValueError):
        op.expand_period("2020-01-01T24:00Z", "+09:00")


def test_invalid_period_value_error_includes_record_id():
    with pytest.raises(op.InvalidPeriodValueError, match="rec-999"):
        op.expand_period("2020-02-30", "+09:00", record_id="rec-999")


# ---------------------------------------------------------------------------
# 年不変の機械検証（D3の前提）
# ---------------------------------------------------------------------------

def test_year_boundary_crossed_raises():
    """UTC 12/31 深夜の観測に +09:00 すると年が変わる。D3の前提が破れるので
    即座に止まる。"""
    with pytest.raises(op.YearBoundaryCrossedError):
        op.expand_period("2020-12-31T16:30Z", "+09:00")


def test_year_boundary_not_crossed_for_normal_case():
    """年内に収まる変換は例外を投げない。"""
    result = op.expand_period("2020-12-31T10:00Z", "+09:00")
    assert result.period_start.startswith("2020-12-31")


# ---------------------------------------------------------------------------
# 宣言表（occurrence_period_shapes.yaml）の読み込み・構造検証
# ---------------------------------------------------------------------------

def _all_shapes_yaml_text(**overrides) -> str:
    counts = {name: 1 for name in op._SHAPE_NAMES}
    counts.update(overrides)
    return "".join(
        f"{name}:\n  expected_row_count: {counts[name]}\n  note: テスト\n" for name in op._SHAPE_NAMES
    )


def test_load_period_shapes_from_yaml(tmp_path):
    yaml_path = tmp_path / "shapes.yaml"
    yaml_path.write_text(
        "day:\n"
        "  expected_row_count: 5\n"
        "  note: テスト\n",
        encoding="utf-8",
    )
    shapes = op.load_period_shapes(yaml_path)
    assert set(shapes) == {"day"}
    assert shapes["day"].expected_row_count == 5


def test_load_period_shapes_missing_file_returns_empty(tmp_path):
    assert op.load_period_shapes(tmp_path / "does_not_exist.yaml") == {}


def test_validate_occurrence_period_shapes_shape_accepts_all_twelve(tmp_path):
    yaml_path = tmp_path / "shapes.yaml"
    yaml_path.write_text(_all_shapes_yaml_text(), encoding="utf-8")
    op.validate_occurrence_period_shapes_shape(yaml_path)  # 例外を投げなければ良い


def test_validate_occurrence_period_shapes_shape_rejects_missing_required_key(tmp_path):
    yaml_path = tmp_path / "shapes.yaml"
    yaml_path.write_text("day:\n  expected_row_count: 10\n", encoding="utf-8")
    with pytest.raises(op.MigrationError, match="day"):
        op.validate_occurrence_period_shapes_shape(yaml_path)


def test_validate_occurrence_period_shapes_shape_rejects_non_integer_count(tmp_path):
    """コードレビュー指摘6: expected_row_count は整数必須（文字列・小数・
    真偽値は拒否する）。"""
    yaml_path = tmp_path / "shapes.yaml"
    yaml_path.write_text('day:\n  expected_row_count: "10"\n  note: テスト\n', encoding="utf-8")
    with pytest.raises(op.MigrationError, match="整数"):
        op.validate_occurrence_period_shapes_shape(yaml_path)


def test_validate_occurrence_period_shapes_shape_rejects_missing_shape_name(tmp_path):
    """コードレビュー指摘4: 宣言された形の名前がコードの12形と過不足なく
    一致しなければ止める（1つ欠けているだけでも検出する）。"""
    yaml_path = tmp_path / "shapes.yaml"
    text = _all_shapes_yaml_text()
    # 'year' の節を丸ごと消す（雑に文字列操作で1形だけ欠落させる）。
    lines = text.splitlines()
    idx = lines.index("year:")
    del lines[idx:idx + 3]
    yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(op.MigrationError, match="year"):
        op.validate_occurrence_period_shapes_shape(yaml_path)


def test_validate_occurrence_period_shapes_shape_rejects_extra_shape_name(tmp_path):
    yaml_path = tmp_path / "shapes.yaml"
    text = _all_shapes_yaml_text() + "not_a_real_shape:\n  expected_row_count: 1\n  note: テスト\n"
    yaml_path.write_text(text, encoding="utf-8")
    with pytest.raises(op.MigrationError, match="not_a_real_shape"):
        op.validate_occurrence_period_shapes_shape(yaml_path)


def test_validate_occurrence_period_shapes_shape_missing_file_raises_all_missing(tmp_path):
    """空表（宣言0件）はコードの12形と一致しないので止まる（宣言必須）。"""
    with pytest.raises(op.MigrationError):
        op.validate_occurrence_period_shapes_shape(tmp_path / "does_not_exist.yaml")


def test_assert_declared_shapes_match_code_accepts_full_set():
    loaded = {
        name: op.PeriodShape(name=name, expected_row_count=1, note="t") for name in op._SHAPE_NAMES
    }
    op.assert_declared_shapes_match_code(loaded)  # 例外を投げなければ良い


def test_assert_declared_shapes_match_code_rejects_partial_set():
    loaded = {"day": op.PeriodShape(name="day", expected_row_count=1, note="t")}
    with pytest.raises(op.MigrationError):
        op.assert_declared_shapes_match_code(loaded)


# ---------------------------------------------------------------------------
# period.EntryUsage（未使用宣言・件数不一致の検出。専用の別名は持たない
# ——/simplify 指摘10）
# ---------------------------------------------------------------------------

def test_period_shape_usage_reports_unused_and_mismatched():
    day_shape = op.PeriodShape(name="day", expected_row_count=3, note="t")
    usage = period.EntryUsage({"day": day_shape})
    assert usage.unused_entries() == ["day"]
    usage.mark_used("day")
    assert usage.unused_entries() == []
    assert usage.mismatched_expected_counts() == {"day": (3, 1)}
