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


# ---------------------------------------------------------------------------
# センサーの縦線 設計 v2 T1・T2: month（7桁）・instant/hour（25桁）
# ---------------------------------------------------------------------------

def test_month_grain_matches():
    """jma_monthly 相当（7桁、value_grain='month'）。月の初日〜末日。"""
    usage = period.PeriodExceptionUsage({})
    grain, start, end = period.compute_period("2019-01", "month", "jma_monthly_kanagawa", {}, usage)
    assert (grain, start, end) == ("month", "2019-01-01", "2019-01-31")


def test_month_grain_handles_december_and_leap_february():
    usage = period.PeriodExceptionUsage({})
    assert period.compute_period("2019-12", "month", "src", {}, usage)[1:] == ("2019-12-01", "2019-12-31")
    assert period.compute_period("2020-02", "month", "src", {}, usage)[1:] == ("2020-02-01", "2020-02-29")
    assert period.compute_period("2021-02", "month", "src", {}, usage)[1:] == ("2021-02-01", "2021-02-28")


def test_month_length_but_non_month_value_grain_raises():
    usage = period.PeriodExceptionUsage({})
    with pytest.raises(period.PeriodMismatchError):
        period.compute_period("2019-01", "day", "src", {}, usage)


def test_instant_grain_strips_timezone_and_keeps_label():
    """`value_grain='instant'`（合成センサー相当）は時刻帯を落として
    `period_start=period_end=ラベル` にする。`time_conventions` は不要
    （T2: instant/day は宣言不要）。
    """
    usage = period.PeriodExceptionUsage({})
    grain, start, end = period.compute_period(
        "2024-01-01T00:00:00+09:00", "instant", "synthetic_sensor", {}, usage
    )
    assert (grain, start, end) == ("instant", "2024-01-01T00:00:00", "2024-01-01T00:00:00")


def test_hour_grain_without_time_conventions_raises_unknown_convention():
    """value_grain='hour' の出典で `time_conventions` が空（または該当なし）
    だと `UnknownTimeLabelConventionError`（`PeriodMismatchError` とは別系統。
    T2）で止まる。
    """
    usage = period.PeriodExceptionUsage({})
    with pytest.raises(period.UnknownTimeLabelConventionError):
        period.compute_period(
            "2015-04-01T01:00:00+09:00", "hour", "sagamihara_taiki_hourly", {}, usage, {}, None
        )


def _hour_ending_convention(source_id="sagamihara_taiki_hourly", expected_row_count=None):
    return {
        source_id: period.TimeLabelConvention(
            source_id=source_id,
            convention="hour_ending",
            expected_row_count=expected_row_count,
            evidence="テスト用",
        )
    }


def test_hour_ending_subtracts_one_hour():
    """hour_ending: period_start = ラベル-1時間、period_end = ラベル。"""
    conventions = _hour_ending_convention()
    time_usage = period.TimeLabelConventionUsage(conventions)
    grain, start, end = period.compute_period(
        "2015-04-01T01:00:00+09:00", "hour", "sagamihara_taiki_hourly", {}, period.PeriodExceptionUsage({}),
        conventions, time_usage,
    )
    assert (grain, start, end) == ("hour", "2015-04-01T00:00:00", "2015-04-01T01:00:00")
    assert time_usage.counts() == {"sagamihara_taiki_hourly": 1}


def test_hour_ending_00_00_label_crosses_to_previous_day():
    """「24時」ラベル（翌日00:00として保存済み）は hour_ending で前日23:00に
    なる——T1「時刻の計算は時刻帯を落としてから行う」の日またぎケース。
    """
    conventions = _hour_ending_convention()
    time_usage = period.TimeLabelConventionUsage(conventions)
    grain, start, end = period.compute_period(
        "2015-05-01T00:00:00+09:00", "hour", "sagamihara_taiki_hourly", {}, period.PeriodExceptionUsage({}),
        conventions, time_usage,
    )
    assert (grain, start, end) == ("hour", "2015-04-30T23:00:00", "2015-05-01T00:00:00")


def test_hour_grain_unknown_source_id_raises_even_with_other_conventions_declared():
    conventions = _hour_ending_convention(source_id="sagamihara_taiki_hourly")
    with pytest.raises(period.UnknownTimeLabelConventionError):
        period.compute_period(
            "2025-08-01T01:00:00+09:00", "hour", "soramame_hourly_kanagawa", {}, period.PeriodExceptionUsage({}),
            conventions, period.TimeLabelConventionUsage(conventions),
        )


def test_25_digit_label_with_unexpected_timezone_offset_raises():
    """`+09:00` 以外のオフセットは推測で読み替えず即座に止まる。"""
    conventions = _hour_ending_convention()
    with pytest.raises(period.MigrationError):
        period.compute_period(
            "2015-04-01T01:00:00+00:00", "hour", "sagamihara_taiki_hourly", {}, period.PeriodExceptionUsage({}),
            conventions, period.TimeLabelConventionUsage(conventions),
        )


def test_load_time_label_conventions_from_yaml(tmp_path):
    yaml_path = tmp_path / "conventions.yaml"
    yaml_path.write_text(
        "sagamihara_taiki_hourly:\n"
        "  convention: hour_ending\n"
        "  expected_row_count: 3\n"
        "  evidence: テスト\n",
        encoding="utf-8",
    )
    conventions = period.load_time_label_conventions(yaml_path)
    assert set(conventions) == {"sagamihara_taiki_hourly"}
    assert conventions["sagamihara_taiki_hourly"].convention == "hour_ending"
    assert conventions["sagamihara_taiki_hourly"].expected_row_count == 3


def test_load_time_label_conventions_missing_file_returns_empty(tmp_path):
    assert period.load_time_label_conventions(tmp_path / "does_not_exist.yaml") == {}


def test_load_time_label_conventions_rejects_unsupported_convention(tmp_path):
    yaml_path = tmp_path / "conventions.yaml"
    yaml_path.write_text(
        "src:\n  convention: hour_beginning\n  expected_row_count: 1\n  evidence: テスト\n",
        encoding="utf-8",
    )
    with pytest.raises(period.MigrationError, match="未対応"):
        period.load_time_label_conventions(yaml_path)


def test_time_label_convention_usage_reports_unused_and_mismatched():
    conventions = _hour_ending_convention(expected_row_count=5)
    usage = period.TimeLabelConventionUsage(conventions)
    assert usage.unused_entries() == ["sagamihara_taiki_hourly"]
    usage.mark_used("sagamihara_taiki_hourly")
    usage.mark_used("sagamihara_taiki_hourly")
    assert usage.unused_entries() == []
    assert usage.mismatched_expected_counts() == {"sagamihara_taiki_hourly": (5, 2)}


def test_validate_time_label_conventions_shape_rejects_missing_required_key(tmp_path):
    yaml_path = tmp_path / "conventions.yaml"
    yaml_path.write_text("src:\n  convention: hour_ending\n", encoding="utf-8")
    with pytest.raises(period.MigrationError, match="src"):
        period.validate_time_label_conventions_shape(yaml_path)


def test_validate_time_label_conventions_shape_accepts_complete_entry(tmp_path):
    yaml_path = tmp_path / "conventions.yaml"
    yaml_path.write_text(
        "src:\n  convention: hour_ending\n  expected_row_count: 1\n  evidence: テスト\n",
        encoding="utf-8",
    )
    period.validate_time_label_conventions_shape(yaml_path)  # 例外を投げなければ良い


def test_unexpected_digit_count_message_mentions_all_supported_lengths():
    usage = period.PeriodExceptionUsage({})
    with pytest.raises(period.MigrationError, match="4/7/10/25桁"):
        period.compute_period("abc", "day", "src_a", {}, usage)
