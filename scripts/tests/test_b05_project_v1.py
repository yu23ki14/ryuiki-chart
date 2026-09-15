"""scripts/b05_project_v1.py の統合テスト。"""
import sqlite3

import pytest

import b03_build_observation as b03
import b04_build_cube as b04
import b05_project_v1 as b05
from migrate import common

from .migrate_fixtures import (
    DEFAULT_SENSOR_ROWS,
    make_measurements_db,
    make_registry_db,
    make_time_label_conventions_yaml,
)


def _run_b03_b04(measurements_db, registry_db, tmp_path, sensor_rows=None):
    """b03（`observation` 生成）→ b04（キューブ）を通しで実行し、b05 の入力に
    なる v2_db のパスと `b04.build_cube()` の戻り値（stats）を返す（b05 の
    統合テストで共通の配線）。`sensor_rows` は呼び出し側が
    `make_measurements_db` に既に渡し済みの前提（ここでは b03/b04 を走らせる
    だけ）——引数として受けるのは time_label_conventions.yaml を作るかどうかの
    判定用。
    """
    v2_db = tmp_path / "v2.sqlite"
    conventions_path = tmp_path / "conventions.yaml" if sensor_rows else tmp_path / "no_conventions.yaml"
    if sensor_rows:
        make_time_label_conventions_yaml(conventions_path)
    b03.build_and_write_observation(
        measurements_db, registry_db, tmp_path / "no_exceptions.yaml", conventions_path, v2_db
    )
    conn = sqlite3.connect(f"file:{v2_db}", uri=True)
    try:
        stats = b04.build_cube(conn, registry_db)
    finally:
        conn.close()
    return v2_db, stats


def test_assert_alias_is_function_raises_on_collision(tmp_path):
    registry_db = tmp_path / "registry.sqlite"
    make_registry_db(
        registry_db,
        aliases=[
            ("measurements", "BOD", "src_a", "common:variable:water.bod", "common:unit:mg_per_l", None, "day"),
            # 同じ (variable_id, grain, stat, unit_id) にもう1つ別名がある＝関数でない。
            ("measurements", "BOD_alt", "src_a", "common:variable:water.bod", "common:unit:mg_per_l", None, "day"),
        ],
    )
    work = sqlite3.connect("file::memory:?cache=shared", uri=True)
    common.attach_readonly(work, registry_db, "reg")
    try:
        with pytest.raises(common.MigrationError, match="関数になっていない"):
            b05.assert_alias_is_function(work)
    finally:
        work.close()


def test_assert_alias_is_function_passes_when_unique(tmp_path):
    registry_db = tmp_path / "registry.sqlite"
    make_registry_db(registry_db)  # 既定のフィクスチャは衝突が無い
    work = sqlite3.connect("file::memory:?cache=shared", uri=True)
    common.attach_readonly(work, registry_db, "reg")
    try:
        b05.assert_alias_is_function(work)  # 例外を投げなければ良い
        b05.assert_alias_is_function(work, "sensor_timeseries", grains=("day", "hour", "instant"))
    finally:
        work.close()


def test_assert_alias_tuple_maps_to_single_dataset_raises_on_cross_dataset_collision(tmp_path):
    """T5: 同じ (variable_id, grain, stat, unit_id) が measurements と
    sensor_timeseries の両方の alias に対応していると止まる。
    """
    registry_db = tmp_path / "registry.sqlite"
    make_registry_db(
        registry_db,
        aliases=[
            ("measurements", "水温", "src_a", "common:variable:water.water_temp", None, None, "instant"),
            ("sensor_timeseries", "WTEMP", "src_b", "common:variable:water.water_temp", None, None, "instant"),
        ],
    )
    work = sqlite3.connect("file::memory:?cache=shared", uri=True)
    common.attach_readonly(work, registry_db, "reg")
    try:
        with pytest.raises(common.MigrationError, match="複数の dataset にまたがっている"):
            b05.assert_alias_tuple_maps_to_single_dataset(work)
    finally:
        work.close()


def test_assert_alias_tuple_maps_to_single_dataset_passes_on_default_fixture(tmp_path):
    registry_db = tmp_path / "registry.sqlite"
    make_registry_db(registry_db)
    work = sqlite3.connect("file::memory:?cache=shared", uri=True)
    common.attach_readonly(work, registry_db, "reg")
    try:
        b05.assert_alias_tuple_maps_to_single_dataset(work)  # 例外を投げなければ良い
    finally:
        work.close()


def test_end_to_end_pivot_and_labels(tmp_path):
    """b03 → b04 → b05 を通しで動かし、`meas_year` のピボット（mean/min/max を
    1行に）とラベルの引き戻し（site_id/variable/unit）を確認する。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(
        measurements_db,
        rows=[
            ("m1", "S1", "2020-01-01", "BOD", "src_a", 1.0, "1.0", "mg/L", "公開済", 0, "ref1", "ev1"),
            ("m2", "S1", "2020-06-01", "BOD", "src_a", 5.0, "5.0", "mg/L", "公開済", 0, "ref1", "ev1"),
        ],
    )
    make_registry_db(registry_db)

    v2_db, _ = _run_b03_b04(measurements_db, registry_db, tmp_path)

    projections = b05.build_projections(v2_db, registry_db)
    year_columns, year_rows = projections["meas_year"]
    assert year_rows  # 空でないこと
    idx = {c: i for i, c in enumerate(year_columns)}
    row = year_rows[0]
    assert row[idx["site_id"]] == "S1"
    assert row[idx["variable"]] == "BOD"
    assert row[idx["kind"]] == "daily"
    assert row[idx["min"]] == 1.0
    assert row[idx["max"]] == 5.0
    assert row[idx["avg"]] == 3.0
    assert row[idx["unit"]] == "mg/L"


def test_assert_v1_keys_are_unique_end_to_end_detects_alias_shared_across_sources(tmp_path):
    """`assert_alias_is_function` が検証するのは
    `(variable_id, grain, stat, unit_id) → alias` の関数性で、これが崩れていなくても、
    **逆向き**（`alias → tuple`）が関数でないと v1 の `GROUP BY variable` を復元
    できない（アドバイザー指摘）。同じ alias 'pH' を、異なる variable_id/unit_id を
    持つ2つの出典（src_a/src_b）に割り当て、同じ site×day に両方の観測があると、
    b04 は（tuple が違うので）2セル作り、射影は同じ (site_id, variable, d) の行を
    2つ出してしまう——これを b03→b04→b05 の通しで検出できることを確認する。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(
        measurements_db,
        rows=[
            ("m1", "S1", "2020-01-01", "pH", "src_a", 7.0, "7.0", "-", "公開済", 0, "ref1", "ev1"),
            ("m2", "S1", "2020-01-01", "pH", "src_b", 7.5, "7.5", "-", "公開済", 0, "ref1", "ev1"),
        ],
    )
    make_registry_db(
        registry_db,
        aliases=[
            ("measurements", "pH", "src_a", "common:variable:water.ph", "common:unit:none", None, "day"),
            ("measurements", "pH", "src_b", "common:variable:water.ph_alt", "common:unit:ph_scale", None, "day"),
        ],
    )

    v2_db, stats = _run_b03_b04(measurements_db, registry_db, tmp_path)
    assert stats["n_day"] == 6  # b04 自体は2セル×mean/min/max=6行として正常に作る（キーが違うため）

    with pytest.raises(common.MigrationError, match="v1 のキー"):
        b05.build_projections(v2_db, registry_db)


def test_meas_clim_mixes_series_sharing_alias_across_sites(tmp_path):
    """`meas_clim` は `site_id` を GROUP BY に持たない（v1 の
    `web/scripts/build-derived.mjs` の `meas_clim` も同様。`FROM meas_daily
    GROUP BY variable, month`）。異なる出典・異なる site（＝異なる
    `(variable_id, grain, stat, unit_id)` の系列）が同じ alias 文字列
    （ここでは 'pH'）を名乗っていれば、月別平年値では区別されずに1本の平均へ
    混ざる（オーナー決定1。docs/plans/PHASE_B_FACT_SLICE.md §6）。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(
        measurements_db,
        rows=[
            ("m1", "S1", "2020-01-10", "pH", "src_a", 7.0, "7.0", "-", "公開済", 0, "ref1", "ev1"),
            ("m2", "S2", "2020-01-20", "pH", "src_b", 9.0, "9.0", "-", "公開済", 0, "ref1", "ev1"),
        ],
    )
    make_registry_db(
        registry_db,
        aliases=[
            ("measurements", "pH", "src_a", "common:variable:water.ph", "common:unit:none", None, "day"),
            ("measurements", "pH", "src_b", "common:variable:water.ph_alt", "common:unit:ph_scale", None, "day"),
        ],
    )

    v2_db, _ = _run_b03_b04(measurements_db, registry_db, tmp_path)

    projections = b05.build_projections(v2_db, registry_db)

    daily_columns, daily_rows = projections["meas_daily"]
    assert len(daily_rows) == 2  # site_id が違うので meas_daily では別行のまま

    clim_columns, clim_rows = projections["meas_clim"]
    idx = {c: i for i, c in enumerate(clim_columns)}
    assert len(clim_rows) == 1  # meas_clim には site_id が無く、1本に混ざる
    row = clim_rows[0]
    assert row[idx["variable"]] == "pH"
    assert row[idx["month"]] == 1
    assert row[idx["n"]] == 2
    assert row[idx["avg"]] == 8.0  # (7.0 + 9.0) / 2
    assert row[idx["min"]] == 7.0
    assert row[idx["max"]] == 9.0


def test_site_var_and_var_catalog_split_daily_and_annual_kind(tmp_path):
    """`site_var`/`var_catalog` は `meas_year`（`kind` は b04 の `input_grain` から
    決まる。`input_grain='day'` なら `'daily'`、そうでなければ `'annual'`）を
    ソースにする。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(
        measurements_db,
        rows=[
            ("m1", "S1", "2020-01-01", "BOD", "src_a", 1.0, "1.0", "mg/L", "公開済", 0, "ref1", "ev1"),
            ("m2", "S1", "2020-06-01", "BOD", "src_a", 5.0, "5.0", "mg/L", "公開済", 0, "ref1", "ev1"),
            ("m3", "S1", "2019", "BOD", "src_b", 4.5, "4.5", "mg/L", "公開済", 0, "ref2", "ev2"),
        ],
    )
    make_registry_db(
        registry_db,
        aliases=[
            ("measurements", "BOD", "src_a", "common:variable:water.bod", "common:unit:mg_per_l", None, "day"),
            (
                "measurements", "BOD", "src_b", "common:variable:water.bod_annual",
                "common:unit:mg_per_l", None, "year",
            ),
        ],
    )

    v2_db, _ = _run_b03_b04(measurements_db, registry_db, tmp_path)

    projections = b05.build_projections(v2_db, registry_db)

    sv_columns, sv_rows = projections["site_var"]
    idx = {c: i for i, c in enumerate(sv_columns)}
    by_kind = {row[idx["kind"]]: row for row in sv_rows}
    assert set(by_kind) == {"daily", "annual"}
    daily = by_kind["daily"]
    assert daily[idx["n"]] == 2
    assert daily[idx["avg"]] == 3.0
    annual = by_kind["annual"]
    assert annual[idx["n"]] == 1
    assert annual[idx["avg"]] == 4.5

    vc_columns, vc_rows = projections["var_catalog"]
    vidx = {c: i for i, c in enumerate(vc_columns)}
    assert len(vc_rows) == 1
    row = vc_rows[0]
    assert row[vidx["n"]] == 3
    assert row[vidx["n_daily"]] == 2
    assert row[vidx["n_annual"]] == 1


def test_load_v1_keys_covers_all_nine_tables():
    """`_load_v1_keys` が `reports/derived_baseline.json`（コミット済みの小さな
    指紋ファイル。本物の `data/db/*.sqlite` は不要）から、6テーブル＋センサー
    3テーブルぶんのキーをちゃんと読めることを確認する（受け入れ条件1）。
    """
    keys = b05._load_v1_keys(b05.DEFAULT_BASELINE_JSON)
    assert keys["meas_clim"] == ["variable", "month"]
    assert keys["site_var"] == ["site_id", "variable", "kind"]
    assert keys["var_catalog"] == ["variable"]
    assert keys["sensor_daily"] == ["site_id", "datastream", "d"]
    assert keys["rain_daily"] == ["d"]
    assert keys["sensor_hour_month"] == ["datastream", "month", "hour"]


def test_assert_v1_keys_are_unique_detects_duplicate_in_new_tables():
    projections = {
        "var_catalog": (
            ["variable", "unit", "n"],
            [("BOD", "mg/L", 3), ("BOD", "mg/L", 5)],  # variable='BOD' が重複
        ),
    }
    keys_by_table = {"var_catalog": ["variable"]}
    with pytest.raises(common.MigrationError, match="v1 のキー"):
        b05.assert_v1_keys_are_unique(projections, keys_by_table)

    projections2 = {
        "sensor_daily": (
            ["site_id", "datastream", "d", "n"],
            [("S1", "RAIN", "2020-01-01", 2), ("S1", "RAIN", "2020-01-01", 9)],
        ),
    }
    keys_by_table2 = {"sensor_daily": ["site_id", "datastream", "d"]}
    with pytest.raises(common.MigrationError, match="v1 のキー"):
        b05.assert_v1_keys_are_unique(projections2, keys_by_table2)


def test_place_lookup_non_injective_place_id_raises_migration_error(tmp_path):
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db)
    make_registry_db(
        registry_db,
        place_refs=[
            ("place_s1", "S1", "sites.site_id"),
            ("place_s1", "S1_dup", "sites.site_id"),  # 同じ place_id に2つの site_id
            ("place_s2", "S2", "sites.site_id"),
        ],
    )

    v2_db, _ = _run_b03_b04(measurements_db, registry_db, tmp_path)

    with pytest.raises(common.MigrationError, match="単射でない"):
        b05.build_projections(v2_db, registry_db)


# ---------------------------------------------------------------------------
# センサーの縦線 設計 v2 T5・T6
# ---------------------------------------------------------------------------

def test_sensor_daily_unions_cube_day_grain_and_l2_hour_grain(tmp_path):
    """`sensor_daily` は value_grain ∈ {day, instant} をキューブの日次セルから
    （mean/min/max ピボット）、value_grain='hour' を L2 のラベル日割りから
    UNION する（T5）。既定フィクスチャ（TEMP_DAILY=day, RAIN=hour（24時ラベル
    含む）, WTEMP=instant）で両方の経路が同時に出ることを確認する。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db, sensor_rows=DEFAULT_SENSOR_ROWS)
    make_registry_db(registry_db)

    v2_db, _ = _run_b03_b04(measurements_db, registry_db, tmp_path, sensor_rows=DEFAULT_SENSOR_ROWS)
    projections = b05.build_projections(v2_db, registry_db)

    columns, rows = projections["sensor_daily"]
    idx = {c: i for i, c in enumerate(columns)}
    by_key = {(r[idx["datastream"]], r[idx["d"]]): r for r in rows}

    # day 由来（TEMP_DAILY）: 2020-01-01/01-02 それぞれ1点ずつ。
    assert by_key[("TEMP_DAILY", "2020-01-01")][idx["avg"]] == 5.0
    assert by_key[("TEMP_DAILY", "2020-01-02")][idx["avg"]] == 7.0

    # instant 由来（WTEMP）: 2020-01-01 に2点（00:00, 12:00）→ avg=10.5, min=10, max=11。
    wtemp = by_key[("WTEMP", "2020-01-01")]
    assert wtemp[idx["n"]] == 2
    assert wtemp[idx["avg"]] == 10.5
    assert wtemp[idx["min"]] == 10.0
    assert wtemp[idx["max"]] == 11.0

    # hour 由来（RAIN）: v1 のラベル日割り（substr(period_raw,1,10)）。
    # 01:00・02:00 は 2020-01-01、24時ラベル（2020-01-02T00:00）は
    # v1 のラベル日割りでは 2020-01-02 に入る（キューブの日割りとはここで
    # 1日ずれる。T5(b) がこの v1 の癖を再現する対象）。
    rain_0101 = by_key[("RAIN", "2020-01-01")]
    assert rain_0101[idx["n"]] == 2
    assert rain_0101[idx["avg"]] == 1.5  # (1.0+2.0)/2
    rain_0102 = by_key[("RAIN", "2020-01-02")]
    assert rain_0102[idx["n"]] == 1
    assert rain_0102[idx["avg"]] == 3.0


def test_rain_daily_matches_v1_label_day_bucketing_and_tenths_conversion(tmp_path):
    """`rain_daily`: L2 のラベル日割りで RAIN を合計し /10 する（v1 の
    0.1mm単位の推測換算をそのまま再現。T5）。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db, sensor_rows=DEFAULT_SENSOR_ROWS)
    make_registry_db(registry_db)

    v2_db, _ = _run_b03_b04(measurements_db, registry_db, tmp_path, sensor_rows=DEFAULT_SENSOR_ROWS)
    projections = b05.build_projections(v2_db, registry_db)

    columns, rows = projections["rain_daily"]
    idx = {c: i for i, c in enumerate(columns)}
    by_day = {r[idx["d"]]: r for r in rows}
    # 2020-01-01: RAIN 01:00(1.0)+02:00(2.0)=3.0 → /10 = 0.3mm, n_hours=2
    assert by_day["2020-01-01"][idx["mm"]] == 0.3
    assert by_day["2020-01-01"][idx["n_hours"]] == 2
    # 2020-01-02: 24時ラベル(3.0) → /10 = 0.3mm, n_hours=1
    assert by_day["2020-01-02"][idx["mm"]] == 0.3
    assert by_day["2020-01-02"][idx["n_hours"]] == 1


def test_sensor_hour_month_uses_period_raw_not_period_start(tmp_path):
    """`sensor_hour_month`: 月・時刻は period_raw から取る（period_start だと
    hour_ending で1時間ずれる。T5）。24時ラベル（period_raw の時刻=00）は
    period_raw 側では hour=0 のまま（period_start なら前日23時になる）。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db, sensor_rows=DEFAULT_SENSOR_ROWS)
    make_registry_db(registry_db)

    v2_db, _ = _run_b03_b04(measurements_db, registry_db, tmp_path, sensor_rows=DEFAULT_SENSOR_ROWS)
    projections = b05.build_projections(v2_db, registry_db)

    columns, rows = projections["sensor_hour_month"]
    idx = {c: i for i, c in enumerate(columns)}
    by_key = {(r[idx["datastream"]], r[idx["month"]], r[idx["hour"]]): r for r in rows}
    # 24時ラベル（period_raw='2020-01-02T00:00:00+09:00'）は period_raw から
    # hour=0 を取る（period_start=前日23時からなら hour=23 になってしまう）。
    assert ("RAIN", 1, 0) in by_key
    assert by_key[("RAIN", 1, 0)][idx["n"]] == 1
    assert ("RAIN", 1, 1) in by_key
    assert ("RAIN", 1, 2) in by_key
    # sensor_hour_month は value_grain IN ('hour','instant') を両方含む
    # （v1 の LENGTH(phenomenon_time)>=13 と同じ範囲）。WTEMP（instant）も出る。
    assert ("WTEMP", 1, 0) in by_key
    assert ("WTEMP", 1, 12) in by_key
    # TEMP_DAILY（day、10桁）は v1 と同じく対象外。
    assert not any(k[0] == "TEMP_DAILY" for k in by_key)


def test_verify_hourly_daily_rollup_passes_on_consistent_fixture(tmp_path):
    """T6: 整合したフィクスチャでは `build_projections` が例外を投げない
    （＝内部で呼ばれる `verify_hourly_daily_rollup` が通る）ことを end-to-end
    で確認する。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db, sensor_rows=DEFAULT_SENSOR_ROWS)
    make_registry_db(registry_db)

    v2_db, _ = _run_b03_b04(measurements_db, registry_db, tmp_path, sensor_rows=DEFAULT_SENSOR_ROWS)
    b05.build_projections(v2_db, registry_db)  # 例外を投げなければ良い


def test_verify_hourly_daily_rollup_detects_broken_day_bucketing(tmp_path):
    """T6: キューブの日次セルの n が期待式からずれていれば
    `MigrationError`（T6 の検証）で止まる。わざと `observation_agg` の
    `n` を書き換えて壊れた日割りを再現する。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db, sensor_rows=DEFAULT_SENSOR_ROWS)
    make_registry_db(registry_db)

    v2_db, _ = _run_b03_b04(measurements_db, registry_db, tmp_path, sensor_rows=DEFAULT_SENSOR_ROWS)

    conn = sqlite3.connect(str(v2_db))
    conn.execute(
        "UPDATE observation_agg SET n = n + 100 "
        "WHERE grain='day' AND input_grain='hour' AND stat='mean'"
    )
    conn.commit()
    conn.close()

    with pytest.raises(common.MigrationError, match="T6"):
        b05.build_projections(v2_db, registry_db)


def test_verify_hourly_daily_rollup_function_directly():
    """`verify_hourly_daily_rollup` 自体を直接呼び、期待式
    （キューブの日次セルのn = v1形の日Dのn − 日Dの00時の件数 + 日D+1の00時の件数）
    を小さな手作りの一時テーブルで確認する。
    """
    work = sqlite3.connect(":memory:")
    work.execute(
        "CREATE TABLE label25_obs_keyed (region_id, place_id, place_kind, variable_id, obs_stat, "
        "unit_id, value_grain, period_raw, value_num, akey)"
    )
    work.execute(
        "CREATE TABLE cube_observation_agg (region_id, place_id, place_kind, variable_id, obs_stat, "
        "unit_id, value_grain, period_start, period_end, grain, input_grain, stat, value, n)"
    )
    # cube.observation_agg として参照できるよう ATTACH のかわりに VIEW を張る
    # （このテストでは cube スキーマを別ファイルにする必要が無いので、
    # ATTACH の代わりに同一接続内でエイリアスする）。
    work.execute("ATTACH DATABASE ':memory:' AS cube")
    work.execute(
        "CREATE TABLE cube.observation_agg (region_id, place_id, place_kind, variable_id, obs_stat, "
        "unit_id, value_grain, period_start, period_end, grain, input_grain, stat, value, n)"
    )
    dim = ("jp-14", "place_s1", "site", "v1", None, "u1", "hour")
    # 2020-01-01 に3件、2020-01-02T00:00（24時ラベル）に1件。
    work.executemany(
        "INSERT INTO label25_obs_keyed VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (*dim, "2020-01-01T01:00:00+09:00", 1.0, "k"),
            (*dim, "2020-01-01T02:00:00+09:00", 2.0, "k"),
            (*dim, "2020-01-01T03:00:00+09:00", 3.0, "k"),
            (*dim, "2020-01-02T00:00:00+09:00", 4.0, "k"),
        ],
    )
    # 正しいキューブの日次セル: 2020-01-01 は3件（00:00ラベルの1件は前日側に
    # 移動するので）、v1形のラベル日割りでは2020-01-01が3件・2020-01-02が1件。
    # 期待式: n(2020-01-01) = 3 - 0(00時の件数@01-01) + 1(00時の件数@01-02) = 4
    # 2020-01-02T00:00 ラベル（値4.0）はキューブでは前日23:00に移動するため、
    # 唯一のキューブ日次セル（2020-01-01）が4件全部を持つ（n=4, min=1.0, max=4.0）。
    work.executemany(
        "INSERT INTO cube.observation_agg VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (*dim, "2020-01-01", "2020-01-01", "day", "hour", "mean", 2.5, 4),
            (*dim, "2020-01-01", "2020-01-01", "day", "hour", "min", 1.0, 4),
            (*dim, "2020-01-01", "2020-01-01", "day", "hour", "max", 4.0, 4),
        ],
    )
    import b05_project_v1 as b05_mod

    stats = b05_mod.verify_hourly_daily_rollup(work)
    assert stats["n_series_days_checked"] >= 1
