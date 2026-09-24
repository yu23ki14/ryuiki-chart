"""scripts/b04_build_cube.py の統合テスト（小さな自作 observation フィクスチャ）。

`observation` の列は `scripts/b03_build_observation.py` の
`_CREATE_OBSERVATION_SQL` をそのまま使う（スキーマの正を1箇所に保つ）。
"""
import sqlite3

import pytest

import b03_build_observation as b03
import b04_build_cube as b04
from migrate import common
from reconcile import common as reconcile_common
from reconcile import datasource

from .migrate_fixtures import make_registry_db, make_v2_db_with_observation

# b04 は AVG()/SUM() を使うため `common.require_sqlite_version()` で古い
# SQLite を拒む（`scripts/migrate/common.py` 参照）。この版のガード自体の
# 単体テストは `scripts/tests/test_migrate_common.py`。ここでは環境の SQLite
# が実際に古いとき、意味の無い失敗の山を作らずスキップする。
pytestmark = pytest.mark.skipif(
    sqlite3.sqlite_version_info < common.MIN_SQLITE_VERSION,
    reason=f"SQLite {common.MIN_SQLITE_VERSION} 未満（実際: {sqlite3.sqlite_version}）",
)


def _row(
    source_table, source_row_id, period_start, period_end, value_num, value_raw, censoring,
    variable_id="common:variable:water.bod", obs_stat=None, unit_id="common:unit:mg_per_l",
    censoring_limit=None, value_grain="day", period_grain="day", period_raw=None,
):
    return (
        source_table, source_row_id, "jp-14", "place_s1", "site", variable_id, obs_stat,
        unit_id, "mg/L", value_grain, period_grain, period_start, period_end,
        period_raw if period_raw is not None else period_start, value_num, value_raw, censoring, censoring_limit,
        "公開済", 0, "ref", "ev1",
    )


def _registry_db(tmp_path):
    """`variable.default_stat` を持つ最小のレジストリ DB を作る（b04 が
    ATTACH する）。既定フィクスチャ（`weather.precipitation` が `default_stat=
    'sum'`）をそのまま使う。
    """
    registry_db = tmp_path / "registry.sqlite"
    make_registry_db(registry_db)
    return registry_db


def test_zero_and_lod_series_per_censoring_branch(tmp_path):
    """ADR-0009 決定4: `value_zero`/`value_lod` を4つの検閲区分（none/below_lod/
    not_detected/above_lod）それぞれについて格ごとに確認する（設計ブリーフ
    検証7の実測）。

    - `none`（2.0）: 両系列とも 2.0（代入の余地が無い）。
    - `below_lod`（<0.5）: value_zero=0.0（v1再現）・value_lod=0.5（censoring_limit）。
    - `not_detected`（ND）: value_zero=0.0（v1再現）・value_lod=NULL（限界値が
      無いため代入せず、平均から除外する一般形）。
    - `above_lod`（>9.0）: value_num が NULL（D2）のまま、どちらの系列でも
      代入されないので `v_zero IS NOT NULL` の絞り込みで日次セル自体ができない
      （非メンバーのまま。ADR-0009 決定4-C）。
    """
    rows = [
        _row("measurements", "m1", "2020-01-01", "2020-01-01", 2.0, "2.0", "none"),
        _row("measurements", "m2", "2020-01-02", "2020-01-02", None, "<0.5", "below_lod", censoring_limit=0.5),
        _row("measurements", "m3", "2020-01-03", "2020-01-03", None, "ND", "not_detected"),
        _row("measurements", "m4", "2020-01-04", "2020-01-04", None, ">9.0", "above_lod", censoring_limit=9.0),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        stats = b04.build_cube(conn, _registry_db(tmp_path))
        day_rows = conn.execute(
            "SELECT period_start, value_zero, value_lod, n, n_censored, n_not_detected FROM observation_agg "
            "WHERE grain='day' AND stat='mean' ORDER BY period_start"
        ).fetchall()
        assert stats["n_day"] == 9  # mean/min/max の3行 × 3日（above_lodの日は無い）
        assert ("2020-01-01", 2.0, 2.0, 1, 0, 0) in day_rows
        assert ("2020-01-02", 0.0, 0.5, 1, 1, 0) in day_rows
        assert ("2020-01-03", 0.0, None, 1, 0, 1) in day_rows
        assert all(r[0] != "2020-01-04" for r in day_rows)
        # 検証1: value_lod が NULL になるのは 2020-01-03（n_not_detected=n=1）
        # の日次セルだけ（`day_rows` は stat='mean' に絞っているので1行）。
        null_rows = [r for r in day_rows if r[2] is None]
        assert {r[0] for r in null_rows} == {"2020-01-03"}
        assert len(null_rows) == 1
    finally:
        conn.close()


def test_value_lod_report_counts(tmp_path):
    """`build_cube()` が返すレポート件数（`n_value_lod_differs`/
    `n_value_lod_null`。設計ブリーフ 検証4）を、月・年のロールアップに
    巻き込まれない出典配布セル（`period_grain='fiscal_year'`）だけの小さな
    フィクスチャで検証する（day セルは月・年へロールアップされるため、
    件数の手計算が煩雑になる。ここでは意図的にそれを避け、系列（variable_id）
    を分けて互いにロールアップで混ざらないようにする）。
    """
    rows = [
        _row(
            "measurements", "m1", "2020-04-01", "2021-03-31", 2.0, "2.0", "none",
            variable_id="common:variable:water.bod", value_grain="fiscal_year", period_grain="fiscal_year",
        ),
        _row(
            "measurements", "m2", "2020-04-01", "2021-03-31", None, "<0.5", "below_lod", censoring_limit=0.5,
            variable_id="common:variable:water.cod", value_grain="fiscal_year", period_grain="fiscal_year",
        ),
        _row(
            "measurements", "m3", "2020-04-01", "2021-03-31", None, "ND", "not_detected",
            variable_id="common:variable:water.ph", value_grain="fiscal_year", period_grain="fiscal_year",
        ),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        stats = b04.build_cube(conn, _registry_db(tmp_path))
        # 各系列は独立（variable_id が違う）なので互いにロールアップで混ざらない。
        # stat ∈ {mean, min, max} の3行 × 3系列 = 9行。
        assert stats["n_year_source"] == 9
        # none（m1）は3行とも差なし。below_lod（m2）は3行（mean/min/max）とも
        # 差あり。not_detected（m3）は3行とも value_lod が NULL——`!=` は
        # NULL を含む比較を「異なる」として数えない（SQL の3値論理）ので
        # n_value_lod_differs には入らず、n_value_lod_null 側だけに数えられる
        # （設計ブリーフ 検証4「重なり0」）。
        assert stats["n_value_lod_differs"] == 3  # below_lod の3行のみ
        assert stats["n_value_lod_null"] == 3  # not_detected の3行
    finally:
        conn.close()


def test_day_cell_has_mean_min_max_for_every_variable(tmp_path):
    """T4-2: 日次セルは全変数で stat ∈ {mean, min, max} を必ず持つ。"""
    rows = [
        _row("measurements", "m1", "2020-01-01", "2020-01-01", 1.0, "1.0", "none"),
        _row("measurements", "m2", "2020-01-01", "2020-01-01", 3.0, "3.0", "none"),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        b04.build_cube(conn, _registry_db(tmp_path))
        got = dict(
            conn.execute(
                "SELECT stat, value_zero FROM observation_agg WHERE grain='day' ORDER BY stat"
            ).fetchall()
        )
        assert got == {"max": 3.0, "mean": 2.0, "min": 1.0}
    finally:
        conn.close()


def test_day_cell_sum_only_for_default_stat_sum_variables_matching_obs_stat(tmp_path):
    """T4-2: `variable.default_stat='sum'` かつ (`obs_stat IS NULL` または
    `obs_stat='sum'`) の系列だけ `stat='sum'` の日次セルが足される。
    `weather.precipitation`（フィクスチャで default_stat='sum'）で確認する。
    `obs_stat='max_10min'` を宣言する別系列には sum をかけない
    （jma_daily の「最大値」相当。回帰テスト）。
    """
    rows = [
        _row(
            "sensor_timeseries", "s1", "2020-01-01", "2020-01-01", 1.0, None, "none",
            variable_id="common:variable:weather.precipitation", obs_stat=None, unit_id=None,
        ),
        _row(
            "sensor_timeseries", "s2", "2020-01-01", "2020-01-01", 2.0, None, "none",
            variable_id="common:variable:weather.precipitation", obs_stat=None, unit_id=None,
        ),
        # 同じ variable_id でも obs_stat='max_10min' は sum の対象外。
        _row(
            "sensor_timeseries", "s3", "2020-01-01", "2020-01-01", 5.0, None, "none",
            variable_id="common:variable:weather.precipitation", obs_stat="max_10min", unit_id=None,
        ),
        # default_stat が無い変数（water.bod）は obs_stat=NULL でも sum を作らない。
        _row("measurements", "m1", "2020-01-01", "2020-01-01", 9.0, "9.0", "none"),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        b04.build_cube(conn, _registry_db(tmp_path))
        sum_rows = conn.execute(
            "SELECT variable_id, obs_stat, value_zero, n FROM observation_agg WHERE grain='day' AND stat='sum'"
        ).fetchall()
        assert sum_rows == [("common:variable:weather.precipitation", None, 3.0, 2)]
    finally:
        conn.close()


def test_hour_and_instant_grain_roll_up_into_day_cell_with_correct_input_grain(tmp_path):
    """T4-1: period_grain IN ('hour','instant') も日次セルに積み上げる。
    日付は substr(period_start,1,10)（区間の始まりの日付）。input_grain は
    その period_grain になる。
    """
    rows = [
        _row(
            "sensor_timeseries", "s1", "2020-01-01T23:00:00", "2020-01-02T00:00:00", 4.0, None, "none",
            variable_id="common:variable:weather.precipitation", unit_id=None,
            value_grain="hour", period_grain="hour", period_raw="2020-01-02T00:00:00+09:00",
        ),
        _row(
            "sensor_timeseries", "s2", "2020-01-03T12:00:00", "2020-01-03T12:00:00", 6.0, None, "none",
            variable_id="common:variable:water.water_temp", unit_id=None,
            value_grain="instant", period_grain="instant", period_raw="2020-01-03T12:00:00+09:00",
        ),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        b04.build_cube(conn, _registry_db(tmp_path))
        hour_day = conn.execute(
            "SELECT period_start, period_end, input_grain, value_zero, n FROM observation_agg "
            "WHERE grain='day' AND stat='mean' AND variable_id='common:variable:weather.precipitation'"
        ).fetchall()
        # 区間の始まり（23:00 の日付＝2020-01-01）が日次セルの日になる（正しい日割り）。
        assert hour_day == [("2020-01-01", "2020-01-01", "hour", 4.0, 1)]

        instant_day = conn.execute(
            "SELECT period_start, input_grain, value_zero FROM observation_agg "
            "WHERE grain='day' AND stat='mean' AND variable_id='common:variable:water.water_temp'"
        ).fetchall()
        assert instant_day == [("2020-01-03", "instant", 6.0)]
    finally:
        conn.close()


def test_month_source_cell_is_symmetric_with_year_source_cell(tmp_path):
    """T4-1: period_grain='month'（jma_monthly 相当）は日次セルを経由せず、
    出典配布の月次セルになる（grain=input_grain='month'。年次の出典配布
    セルと対称——mean/min/max の3行になる）。
    """
    rows = [
        _row(
            "sensor_timeseries", "s1", "2019-01-01", "2019-01-31", 10.0, None, "none",
            variable_id="common:variable:weather.pressure_station", unit_id="common:unit:hpa",
            value_grain="month", period_grain="month", period_raw="2019-01",
        ),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        stats = b04.build_cube(conn, _registry_db(tmp_path))
        assert stats["n_month_source"] == 3
        assert stats["n_day"] == 0
        month_rows = conn.execute(
            "SELECT grain, input_grain, stat, value_zero, n FROM observation_agg WHERE grain='month' ORDER BY stat"
        ).fetchall()
        assert month_rows == [
            ("month", "month", "max", 10.0, 1),
            ("month", "month", "mean", 10.0, 1),
            ("month", "month", "min", 10.0, 1),
        ]
    finally:
        conn.close()


def test_year_source_cell_closed_to_year_and_fiscal_year_only(tmp_path):
    """T4-1: 出典配布の年次セルは period_grain IN ('year','fiscal_year') に
    閉じる（毎時・月次の観測を誤って年次として吸い込まない回帰テスト）。
    """
    rows = [
        _row(
            "sensor_timeseries", "s1", "2019-01-01", "2019-01-31", 10.0, None, "none",
            variable_id="common:variable:weather.pressure_station", unit_id="common:unit:hpa",
            value_grain="month", period_grain="month", period_raw="2019-01",
        ),
        _row(
            "measurements", "m1", "2020-04-01", "2021-03-31", 4.0, "4.0", "none",
            value_grain="fiscal_year", period_grain="fiscal_year",
        ),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        stats = b04.build_cube(conn, _registry_db(tmp_path))
        assert stats["n_month_source"] == 3
        assert stats["n_year_source"] == 3
        year_grains = conn.execute(
            "SELECT DISTINCT grain FROM observation_agg WHERE grain IN ('year','fiscal_year')"
        ).fetchall()
        assert year_grains == [("fiscal_year",)]  # 月次データが年次に混ざっていない
    finally:
        conn.close()


def test_month_and_year_from_day_inherit_input_grain_and_filter_mean(tmp_path):
    """T4-1/T4-3: 月次・年次（日次セルから積み上げる側）は input_grain を
    cube_day から引き継ぎ、かつ stat='mean' の日次セルだけを積み上げる
    （min/max/sum が混ざらない）。
    """
    rows = [
        _row("measurements", "m1", "2020-01-01", "2020-01-01", 1.0, "1.0", "none"),
        _row("measurements", "m2", "2020-01-02", "2020-01-02", 3.0, "3.0", "none"),
        _row("measurements", "m3", "2020-01-03", "2020-01-03", 5.0, "5.0", "none"),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        b04.build_cube(conn, _registry_db(tmp_path))
        month = conn.execute(
            "SELECT n, value_zero, input_grain FROM observation_agg WHERE grain='month'"
        ).fetchall()
        assert month == [(3, 3.0, "day")]  # n=3（日次セル3個）, avg=(1+3+5)/3=3.0, min/maxは混ざらない

        year_mean = conn.execute(
            "SELECT n, value_zero, input_grain FROM observation_agg WHERE grain='year' AND stat='mean'"
        ).fetchall()
        assert year_mean == [(3, 3.0, "day")]
        year_min = conn.execute(
            "SELECT value_zero FROM observation_agg WHERE grain='year' AND stat='min'"
        ).fetchall()
        year_max = conn.execute(
            "SELECT value_zero FROM observation_agg WHERE grain='year' AND stat='max'"
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
            "measurements", "m1", "2020-04-01", "2021-03-31", 4.0, "4.0", "none",
            value_grain="fiscal_year", period_grain="fiscal_year",
        ),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        stats = b04.build_cube(conn, _registry_db(tmp_path))
        assert stats["n_day"] == 0
        assert stats["n_month_from_day"] == 0
        annual = conn.execute(
            "SELECT grain, input_grain, stat, value_zero, n FROM observation_agg ORDER BY stat"
        ).fetchall()
        assert annual == [
            ("fiscal_year", "fiscal_year", "max", 4.0, 1),
            ("fiscal_year", "fiscal_year", "mean", 4.0, 1),
            ("fiscal_year", "fiscal_year", "min", 4.0, 1),
        ]
    finally:
        conn.close()


def test_built_from_containing_apostrophe_does_not_break_sql(tmp_path):
    """`built_from`/`spec_version` はバインドパラメータで渡す。以前は
    `f\"'{built_from}'\"` で SQL に直接埋め込んでいたため、アポストロフィを含む値
    で構文エラーになった。
    """
    rows = [_row("measurements", "m1", "2020-01-01", "2020-01-01", 1.0, "1.0", "none")]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        b04.build_cube(conn, _registry_db(tmp_path), built_from="o'brien's build", spec_version="v'1")
        got = conn.execute("SELECT DISTINCT built_from, spec_version FROM observation_agg").fetchall()
        assert got == [("o'brien's build", "v'1")]
    finally:
        conn.close()


def test_dimension_key_uniqueness_is_verified(tmp_path):
    """day/month(day側/出典側)/year(day側/出典側) の5経路が互いに排他である
    ことを一意性チェックが確認する（既存の回帰テストを維持）。1系列だけの
    小さなフィクスチャでは自然に一意になるので、ここでは例外が出ないことだけ
    を確認する。
    """
    rows = [_row("measurements", "m1", "2020-01-01", "2020-01-01", 1.0, "1.0", "none")]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        b04.build_cube(conn, _registry_db(tmp_path))  # 例外を投げなければ良い
    finally:
        conn.close()


def test_assert_dimension_key_unique_raises_with_examples(tmp_path):
    """C-3: `_assert_dimension_key_unique`（`CREATE UNIQUE INDEX` を使った
    一意性検証）自体を、重複キーを直接仕込んだ作業用テーブルに対して呼び、
    `sqlite3.IntegrityError` ではなく実例つきの `MigrationError` になる
    ことを確認する（GROUP BY へのフォールバックが機能している証拠）。
    """
    db_path = tmp_path / "t.sqlite"
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    conn.execute(b04._CREATE_OBSERVATION_AGG_SQL.format(table='"staging"'))
    cols = ", ".join(
        b04.DIM_COLUMNS
        + ["value_zero", "value_lod", "n", "n_censored", "n_not_detected", "n_places", "built_from", "spec_version"]
    )
    row = (
        "jp-14", "place_s1", "site", "common:variable:water.bod", None, "common:unit:mg_per_l",
        "day", "2020-01-01", "2020-01-01", "day", "day", "mean",
        1.0, 1.0, 1, 0, 0, 1, "bf", "sv",
    )
    placeholders = ", ".join("?" for _ in row)
    conn.executemany(f'INSERT INTO "staging" ({cols}) VALUES ({placeholders})', [row, row])
    conn.commit()
    try:
        with pytest.raises(common.MigrationError, match="次元キーが一意でない"):
            b04._assert_dimension_key_unique(conn, "staging")
    finally:
        conn.close()


def test_a1_uniqueness_failure_preserves_previous_observation_agg(tmp_path, monkeypatch):
    """A-1: 1回目を成功させたあと、2回目を一意性検証の失敗で止める
    （`_assert_dimension_key_unique` をモンキーパッチして強制的に失敗させる
    ——実データで5経路を衝突させるのは難しいため、`staged_table` の
    「検証が全部通ってから差し替える」契約そのものを検証する）。前回の
    observation_agg がそのまま残り、作業用テーブルも残らない。
    """
    rows = [_row("measurements", "m1", "2020-01-01", "2020-01-01", 1.0, "1.0", "none")]
    db_path = tmp_path / "v2.sqlite"
    registry_db = _registry_db(tmp_path)
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    b04.build_cube(conn, registry_db)
    before = conn.execute("SELECT * FROM observation_agg ORDER BY stat").fetchall()
    conn.close()

    def boom(conn, staging):
        raise common.MigrationError("テスト用に強制した一意性違反")

    monkeypatch.setattr(b04, "_assert_dimension_key_unique", boom)

    conn2 = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="テスト用に強制した一意性違反"):
            b04.build_cube(conn2, registry_db)

        tables = sorted(r[0] for r in conn2.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        after = conn2.execute("SELECT * FROM observation_agg ORDER BY stat").fetchall()
    finally:
        conn2.close()
    assert tables == ["observation", "observation_agg"], "作業用テーブルが残っている"
    assert after == before, "前回の observation_agg が変わってしまった"


def test_a1_running_twice_successfully_does_not_collide_on_index_name(tmp_path):
    """C-3 の検証用一意インデックスは使い捨て（張った直後に DROP する）。
    固定名の索引を本番テーブルまで残すと2回目の実行が名前衝突で壊れるはず
    ——2回連続で成功することを確認して、そうなっていないことを示す
    （実測で踏んだ回帰）。
    """
    rows = [_row("measurements", "m1", "2020-01-01", "2020-01-01", 1.0, "1.0", "none")]
    db_path = tmp_path / "v2.sqlite"
    registry_db = _registry_db(tmp_path)
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    b04.build_cube(conn, registry_db)
    conn.close()

    conn2 = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        stats = b04.build_cube(conn2, registry_db)
    finally:
        conn2.close()
    assert stats["n_total"] > 0


def test_build_cube_calls_the_shared_sqlite_version_guard(tmp_path, monkeypatch):
    """`build_cube()` の先頭で `common.require_sqlite_version()`（b04・b05・b10
    が共有するガード）を呼ぶことを確認する（コードレビュー指摘: 以前はこの
    ガードをモジュール読み込み時点で呼んでいたため、古い SQLite の環境では
    `import b04_build_cube` した瞬間に `SystemExit` が飛び、`pytest` の収集
    自体が止まっていた——守りたい状況でこそ壊れる形だった。関数の先頭に
    移したことで `import` は安全になり、実行時にだけ止まる。
    `-O` での assert 無効化への対処自体は `require_sqlite_version` 側のテスト
    ——`scripts/tests/test_migrate_common.py`
    ::test_require_sqlite_version_raises_systemexit_even_under_dash_o
    ——で確認する）。
    """
    monkeypatch.setattr(common.sqlite3, "sqlite_version_info", (3, 42, 0))
    rows = [_row("measurements", "m1", "2020-01-01", "2020-01-01", 1.0, "1.0", "none")]
    db_path = tmp_path / "v2.sqlite"
    registry_db = _registry_db(tmp_path)
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        with pytest.raises(SystemExit, match="古すぎる"):
            b04.build_cube(conn, registry_db)
    finally:
        conn.close()


def test_running_twice_yields_identical_observation_agg_content_hash(tmp_path):
    """決定論: 同じ `observation` に対して `build_cube()` を2回実行すると
    `observation_agg` の content_hash がバイト一致する（設計ブリーフ 検証8。
    `scripts/tests/test_b03_build_observation.py::test_running_twice_yields_identical_content_hash`
    と同じ流儀）。値の異なる4区分（none/below_lod/not_detected/above_lod）を
    混ぜたフィクスチャで確認する——`value_zero`/`value_lod` のどちらも
    決定論が崩れていないことの回帰。
    """
    rows = [
        _row("measurements", "m1", "2020-01-01", "2020-01-01", 2.0, "2.0", "none"),
        _row("measurements", "m2", "2020-01-02", "2020-01-02", None, "<0.5", "below_lod", censoring_limit=0.5),
        _row("measurements", "m3", "2020-01-03", "2020-01-03", None, "ND", "not_detected"),
        _row("measurements", "m4", "2020-01-04", "2020-01-04", None, ">9.0", "above_lod", censoring_limit=9.0),
    ]
    registry_db = _registry_db(tmp_path)

    def build(db_name):
        db_path = tmp_path / db_name
        conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
        try:
            b04.build_cube(conn, registry_db)
        finally:
            conn.close()
        return db_path

    def fingerprint(path):
        conn = reconcile_common.open_readonly(path)
        src = datasource.SqliteSource(conn)
        columns = src.columns("observation_agg")
        numeric = reconcile_common.numeric_columns_of(conn, "observation_agg", columns)
        fp = reconcile_common.compute_fingerprint(src, "observation_agg", columns, b04.DIM_COLUMNS, numeric)
        conn.close()
        return fp["content_hash"]

    out1 = build("v2_1.sqlite")
    out2 = build("v2_2.sqlite")
    assert fingerprint(out1) == fingerprint(out2)
