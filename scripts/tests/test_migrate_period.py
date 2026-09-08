"""scripts/migrate/period.py の単体テスト（ADR-0008・design.md D4）。"""
import pytest

from migrate import period


def _exceptions(**overrides):
    exc = period.PeriodException(
        source_id="atsugi_like",
        period_grain_override="fiscal_year",
        expected_row_count=2,
        reason="テスト用",
        restoration_plan="テスト用",
    )
    for k, v in overrides.items():
        exc = period.PeriodException(**{**exc.__dict__, k: v})
    return {"atsugi_like": exc}


def test_day_grain_matches():
    usage = period.PeriodExceptionUsage({})
    grain, start, end = period.compute_period("2020-01-05", "day", "src_a", {}, usage)
    assert (grain, start, end) == ("day", "2020-01-05", "2020-01-05")


def test_calendar_year_grain_matches():
    usage = period.PeriodExceptionUsage({})
    grain, start, end = period.compute_period("2020", "year", "src_a", {}, usage)
    assert (grain, start, end) == ("year", "2020-01-01", "2020-12-31")


def test_fiscal_year_grain_matches():
    usage = period.PeriodExceptionUsage({})
    grain, start, end = period.compute_period("2020", "fiscal_year", "src_a", {}, usage)
    assert (grain, start, end) == ("fiscal_year", "2020-04-01", "2021-03-31")


def test_day_length_but_non_day_value_grain_raises():
    """10桁の日付なのに alias が 'day' 以外を宣言している想定外の組み合わせは、
    例外表を経由せず即座に止まる（このケースの宣言的な例外は存在しない）。
    """
    usage = period.PeriodExceptionUsage({})
    with pytest.raises(period.PeriodMismatchError):
        period.compute_period("2020-01-05", "year", "src_a", {}, usage)


def test_four_digit_mismatch_without_declared_exception_raises():
    """value_grain が 'year'/'fiscal_year' のどちらでもなく、例外表にも
    その source_id が無い場合は例外を投げて止まる（design.md D4）。
    """
    usage = period.PeriodExceptionUsage({})
    with pytest.raises(period.PeriodMismatchError):
        period.compute_period("2020", "day", "unknown_source", {}, usage)


def test_four_digit_mismatch_covered_by_exception_is_allowed():
    exceptions = _exceptions()
    usage = period.PeriodExceptionUsage(exceptions)
    grain, start, end = period.compute_period("2020", "day", "atsugi_like", exceptions, usage)
    assert (grain, start, end) == ("fiscal_year", "2020-04-01", "2021-03-31")
    assert usage.counts() == {"atsugi_like": 1}


def test_unused_exception_entry_is_reported():
    """例外表のエントリが1件も当たらなかったら、腐った宣言として検出できる
    （実際に例外を投げるかどうかは呼び出し側 b03 の責務。ここでは
    `unused_entries()` がそれを正しく報告することだけを確認する）。
    """
    exceptions = _exceptions()
    usage = period.PeriodExceptionUsage(exceptions)
    # 誰も compute_period を呼ばない＝1件もマッチしなかった状態のまま。
    assert usage.unused_entries() == ["atsugi_like"]


def test_expected_row_count_mismatch_is_reported():
    exceptions = _exceptions(expected_row_count=5)
    usage = period.PeriodExceptionUsage(exceptions)
    period.compute_period("2020", "day", "atsugi_like", exceptions, usage)
    mismatched = usage.mismatched_expected_counts()
    assert mismatched == {"atsugi_like": (5, 1)}


def test_unexpected_digit_count_raises_migration_error():
    usage = period.PeriodExceptionUsage({})
    with pytest.raises(period.MigrationError):
        period.compute_period("202-01", "day", "src_a", {}, usage)


def test_load_period_exceptions_from_yaml(tmp_path):
    yaml_path = tmp_path / "exceptions.yaml"
    yaml_path.write_text(
        "atsugi_like:\n"
        "  period_grain_override: fiscal_year\n"
        "  expected_row_count: 3\n"
        "  reason: テスト\n"
        "  restoration_plan: テスト\n",
        encoding="utf-8",
    )
    exceptions = period.load_period_exceptions(yaml_path)
    assert set(exceptions) == {"atsugi_like"}
    assert exceptions["atsugi_like"].period_grain_override == "fiscal_year"
    assert exceptions["atsugi_like"].expected_row_count == 3


def test_load_period_exceptions_missing_file_returns_empty(tmp_path):
    assert period.load_period_exceptions(tmp_path / "does_not_exist.yaml") == {}


# ---------------------------------------------------------------------------
# validate_period_exceptions_shape（CI の構造検証。原本DBを必要としない）
# ---------------------------------------------------------------------------

def test_validate_period_exceptions_shape_accepts_complete_entry(tmp_path):
    yaml_path = tmp_path / "exceptions.yaml"
    yaml_path.write_text(
        "atsugi_like:\n"
        "  period_grain_override: fiscal_year\n"
        "  expected_row_count: 3\n"
        "  reason: テスト\n"
        "  restoration_plan: テスト\n",
        encoding="utf-8",
    )
    period.validate_period_exceptions_shape(yaml_path)  # 例外を投げなければ良い


def test_validate_period_exceptions_shape_rejects_missing_required_key(tmp_path):
    """`reason`/`restoration_plan` を省略すると `load_period_exceptions` は
    空文字で埋めて黙って動いてしまう（実行時のガードだけでは「なぜ・いつ直すか」を
    書くことを強制できない）。CI 用の構造検証はここを見て止める。
    """
    yaml_path = tmp_path / "exceptions.yaml"
    yaml_path.write_text(
        "atsugi_like:\n"
        "  period_grain_override: fiscal_year\n"
        "  expected_row_count: 3\n",
        encoding="utf-8",
    )
    with pytest.raises(period.MigrationError, match="atsugi_like"):
        period.validate_period_exceptions_shape(yaml_path)


def test_validate_period_exceptions_shape_missing_file_is_allowed(tmp_path):
    period.validate_period_exceptions_shape(tmp_path / "does_not_exist.yaml")  # 空表は許す
