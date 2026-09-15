"""scripts/b04_build_cube.py の統合テスト（小さな自作 observation フィクスチャ）。

`observation` の列は `scripts/b03_build_observation.py` の
`_CREATE_OBSERVATION_SQL` をそのまま使う（スキーマの正を1箇所に保つ）。
"""
import subprocess
import sys

import b03_build_observation as b03
import b04_build_cube as b04

from .migrate_fixtures import make_v2_db_with_observation


def _row(
    source_measurement_id, period_start, period_end, value_num, value_raw, censoring,
    censoring_limit=None, value_grain="day", period_grain="day",
):
    return (
        source_measurement_id, "jp-14", "place_s1", "site", "common:variable:water.bod", None,
        "common:unit:mg_per_l", "mg/L", value_grain, period_grain, period_start, period_end,
        period_start, value_num, value_raw, censoring, censoring_limit,
        "公開済", 0, "ref", "ev1",
    )


def test_zero_imputation_includes_below_lod_and_excludes_above_lod(tmp_path):
    """imputation='zero' が below_lod/not_detected を 0.0 として平均に含め、
    above_lod/unknown を除外することを、実際の集計結果（AVG/n）で確認する。
    """
    rows = [
        _row("m1", "2020-01-01", "2020-01-01", 2.0, "2.0", "none"),
        _row("m2", "2020-01-02", "2020-01-02", None, "<0.5", "below_lod", 0.5),
        _row("m3", "2020-01-03", "2020-01-03", None, ">9.0", "above_lod", 9.0),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        stats = b04.build_cube(conn)
        # above_lod（m3）は value_num が NULL（D2）のまま imputation='zero' でも
        # 代入されないので、`v IS NOT NULL` の絞り込みで日次セル自体ができない。
        assert stats["n_day"] == 2
        day_rows = conn.execute(
            "SELECT period_start, value, n, n_censored FROM observation_agg WHERE grain='day' ORDER BY period_start"
        ).fetchall()
        # m1: value=2.0 のまま。m2: below_lod→0.0 が代入される。m3: above_lod→NULL のまま
        # （集計対象から外れる＝v='NULL' の行は WHERE v IS NOT NULL で cube から除外される
        # ので、above_lod の日は cube に現れない）。
        assert ("2020-01-01", 2.0, 1, 0) in day_rows
        assert ("2020-01-02", 0.0, 1, 1) in day_rows
        assert all(r[0] != "2020-01-03" for r in day_rows)
    finally:
        conn.close()


def test_month_and_year_n_counts_contributing_subcells_not_sum(tmp_path):
    """月次/年次セルの n は「寄与した下位セルの数」であって、下位セルの n の
    合計ではない（実データで踏んだバグの回帰テスト。b04 は当初 SUM(n) を
    使っていて meas_month/meas_year の n が v1 と食い違っていた）。
    """
    rows = [
        _row("m1", "2020-01-01", "2020-01-01", 1.0, "1.0", "none"),
        _row("m2", "2020-01-02", "2020-01-02", 3.0, "3.0", "none"),
        _row("m3", "2020-01-03", "2020-01-03", 5.0, "5.0", "none"),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        b04.build_cube(conn)
        month = conn.execute("SELECT n, value FROM observation_agg WHERE grain='month'").fetchall()
        assert month == [(3, 3.0)]  # n=3（日次セル3個）, avg=(1+3+5)/3=3.0

        year_mean = conn.execute(
            "SELECT n, value FROM observation_agg WHERE grain='year' AND stat='mean'"
        ).fetchall()
        assert year_mean == [(3, 3.0)]
        year_min = conn.execute(
            "SELECT value FROM observation_agg WHERE grain='year' AND stat='min'"
        ).fetchall()
        year_max = conn.execute(
            "SELECT value FROM observation_agg WHERE grain='year' AND stat='max'"
        ).fetchall()
        assert year_min == [(1.0,)]
        assert year_max == [(5.0,)]
    finally:
        conn.close()


def test_annual_direct_row_bypasses_day_month_cells(tmp_path):
    """出典が直接配った年次値（period_grain <> 'day'）は day/month セルを経由せず
    直接キューブに入り、input_grain がその period_grain になる。
    """
    rows = [
        _row(
            "m1", "2020-04-01", "2021-03-31", 4.0, "4.0", "none",
            value_grain="fiscal_year", period_grain="fiscal_year",
        ),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        stats = b04.build_cube(conn)
        assert stats["n_day"] == 0
        assert stats["n_month"] == 0
        annual = conn.execute(
            "SELECT grain, input_grain, stat, value, n FROM observation_agg ORDER BY stat"
        ).fetchall()
        assert annual == [
            ("fiscal_year", "fiscal_year", "max", 4.0, 1),
            ("fiscal_year", "fiscal_year", "mean", 4.0, 1),
            ("fiscal_year", "fiscal_year", "min", 4.0, 1),
        ]
    finally:
        conn.close()


def test_built_from_containing_apostrophe_does_not_break_sql(tmp_path):
    """`built_from`/`spec_version` はバインドパラメータで渡す（変更7）。以前は
    `f\"'{built_from}'\"` で SQL に直接埋め込んでいたため、アポストロフィを含む値
    （実際に起こりうる。`sqlite3.sqlite_version` 自体は数字だけだが、
    `DEFAULT_BUILT_FROM` 以外の値を渡すことは呼び出し側の自由）で
    構文エラーになった。
    """
    rows = [_row("m1", "2020-01-01", "2020-01-01", 1.0, "1.0", "none")]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        b04.build_cube(conn, built_from="o'brien's build", spec_version="v'1")
        got = conn.execute("SELECT DISTINCT built_from, spec_version FROM observation_agg").fetchall()
        assert got == [("o'brien's build", "v'1")]
    finally:
        conn.close()


def test_min_sqlite_version_guard_is_systemexit_not_assert(tmp_path):
    """SQLite バージョンガード（変更2）が `assert` ではなく明示的な `SystemExit`
    であることを、`python -O`（`assert` を丸ごと消すモード）下でも実際に
    止まることで確認する。`assert` のままなら `-O` で消え、古い SQLite
    （`meas_year(kind='daily')` の約20%が黙って変わる版）を検出できなくなる。
    """
    script = (
        "import sys\n"
        "sys.path.insert(0, 'scripts')\n"
        "import sqlite3\n"
        "sqlite3.sqlite_version_info = (3, 42, 0)\n"
        "sqlite3.sqlite_version = '3.42.0'\n"
        "import b04_build_cube\n"
        "print('UNREACHABLE')\n"
    )
    result = subprocess.run(
        [sys.executable, "-O", "-c", script],
        capture_output=True, text=True, cwd=str(b04.ROOT),
    )
    assert result.returncode != 0
    assert "UNREACHABLE" not in result.stdout
    assert "古すぎる" in result.stderr
