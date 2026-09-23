"""scripts/b05_project_v1.py の統合テスト。"""
import sqlite3

import pytest

import b03_build_observation as b03
import b04_build_cube as b04
import b05_project_v1 as b05
from migrate import common

from .migrate_fixtures import (
    DEFAULT_ALIASES,
    DEFAULT_PLACE_REFS,
    DEFAULT_PLACES,
    DEFAULT_PLACE_RELATIONS,
    DEFAULT_SENSOR_ROWS,
    PLACE_REFS_WITH_ZONE,
    PLACES_WITH_ZONE,
    make_measurements_db,
    make_registry_db,
    make_time_label_conventions_yaml,
)

# b04/b05 は AVG()/SUM() を使うため `common.require_sqlite_version()` で
# 古い SQLite を拒む（`scripts/migrate/common.py` 参照）。この版のガード自体の
# 単体テストは `scripts/tests/test_migrate_common.py`。ここでは環境の SQLite が
# 実際に古いとき、意味の無い失敗の山を作らずスキップする。
pytestmark = pytest.mark.skipif(
    sqlite3.sqlite_version_info < common.MIN_SQLITE_VERSION,
    reason=f"SQLite {common.MIN_SQLITE_VERSION} 未満（実際: {sqlite3.sqlite_version}）",
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


def test_load_v1_keys_covers_all_table_sql_entries():
    """`_load_v1_keys` が `reports/derived_baseline.json`（コミット済みの小さな
    指紋ファイル。本物の `data/db/*.sqlite` は不要）から、`_TABLE_SQL` の
    全エントリ（11テーブル）ぶんのキーをちゃんと読めることを確認する
    （受け入れ条件1）。新しいテーブルを `_TABLE_SQL` に足し忘れたり、
    このテストの更新を忘れたりすると `set(keys) == set(b05._TABLE_SQL)` が
    落ちる。
    """
    keys = b05._load_v1_keys(b05.DEFAULT_BASELINE_JSON)
    assert set(keys) == set(b05._TABLE_SQL)
    assert keys["meas_clim"] == ["variable", "month"]
    assert keys["site_var"] == ["site_id", "variable", "kind"]
    assert keys["var_catalog"] == ["variable"]
    assert keys["sensor_daily"] == ["site_id", "datastream", "d"]
    assert keys["rain_daily"] == ["d"]
    assert keys["sensor_hour_month"] == ["datastream", "month", "hour"]
    assert keys["zone_year"] == ["zone", "variable", "year", "kind"]
    assert keys["zone_clim"] == ["zone", "variable", "month"]


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
# ゾーンの縦線（zone_year/zone_clim。`place_relation` の最初の消費者。
# phase-b/zone-slice。ADR-0022 決定2。D11参照）
#
# 「レジストリの不変条件」（地点→ゾーンの辺の単射性・ゾーン番号の数値形式・
# place_source_ref の一意性）は scripts/r01_build_registry.py 側で保証する
# （scripts/tests/test_r01_invariants.py）。ここでテストするのは「射影
# （b05）固有の前提」だけ: fraction=1.0（v1 を非加重で再現する b05 の設計
# 判断）・ゾーン番号の place をまたいだ衝突（b05 が place_id を番号に潰す
# ことから生じる）・site_zone_lookup の site_id 一意（結合の安全性）。
# いずれも `_materialize_lookup_tables` に組み込まれ、`build_projections`
# 以外の呼び出し口を持たない private 関数なので、検証が効くことを確認する
# テストは検証関数を直接呼ぶのではなく **`build_projections` を通して**
# 確認する（検証の呼び出しを消したらテストが落ちる形にする）。
# ---------------------------------------------------------------------------

_ZONE_BOD_ROWS = [
    ("m1", "S1", "2020-01-01", "BOD", "src_a", 1.0, "1.0", "mg/L", "公開済", 0, "ref1", "ev1"),
    ("m2", "S1", "2020-01-02", "BOD", "src_a", 5.0, "5.0", "mg/L", "公開済", 0, "ref1", "ev1"),
    ("m3", "S2", "2020-01-15", "BOD", "src_a", 10.0, "10.0", "mg/L", "公開済", 0, "ref1", "ev1"),
]


def test_zone_year_and_zone_clim_average_site_averages_unweighted(tmp_path):
    """v1（`web/scripts/build-derived.mjs`）の `zone_year`/`zone_clim` は
    `AVG(y.avg)`/`AVG(m.avg)`——ゾーン内の**地点別平均を非加重で平均**する
    （`n` で重み付けしない）。S1（2件, avg=3.0）と S2（1件, avg=10.0）を同じ
    ゾーンに属させると、非加重平均は (3.0+10.0)/2=6.5 になる（n加重なら
    (3.0*2+10.0*1)/3≈5.33 になり区別できる）。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db, rows=_ZONE_BOD_ROWS)
    make_registry_db(
        registry_db,
        places=PLACES_WITH_ZONE,
        place_refs=PLACE_REFS_WITH_ZONE,
        place_relations=[
            ("place_zone1", "place_s1", "within", 1.0, "test"),
            ("place_zone1", "place_s2", "within", 1.0, "test"),
        ],
    )

    v2_db, _ = _run_b03_b04(measurements_db, registry_db, tmp_path)
    projections = b05.build_projections(v2_db, registry_db)

    zy_columns, zy_rows = projections["zone_year"]
    idx = {c: i for i, c in enumerate(zy_columns)}
    assert len(zy_rows) == 1
    row = zy_rows[0]
    assert row[idx["zone"]] == 1
    assert row[idx["variable"]] == "BOD"
    assert row[idx["kind"]] == "daily"
    assert row[idx["year"]] == 2020
    assert row[idx["n_sites"]] == 2
    assert row[idx["n"]] == 3  # S1の2件 + S2の1件
    assert row[idx["avg"]] == 6.5  # (3.0 + 10.0) / 2、非加重
    assert row[idx["unit"]] == "mg/L"

    zc_columns, zc_rows = projections["zone_clim"]
    cidx = {c: i for i, c in enumerate(zc_columns)}
    assert len(zc_rows) == 1
    crow = zc_rows[0]
    assert crow[cidx["zone"]] == 1
    assert crow[cidx["variable"]] == "BOD"
    assert crow[cidx["month"]] == 1
    assert crow[cidx["n_sites"]] == 2
    assert crow[cidx["n"]] == 3
    assert crow[cidx["avg"]] == 6.5
    assert crow[cidx["unit"]] == "mg/L"


def test_zone_year_and_zone_clim_exclude_sites_without_a_zone_edge(tmp_path):
    """`place_relation` に辺を持たない地点（v1 の `sites.zone IS NULL` 相当）は
    zone_year・zone_clim のどちらからも除かれる。S2 にはゾーンの辺を張らない。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db, rows=_ZONE_BOD_ROWS)
    make_registry_db(
        registry_db,
        places=PLACES_WITH_ZONE,
        place_refs=PLACE_REFS_WITH_ZONE,
        place_relations=DEFAULT_PLACE_RELATIONS,  # S1 のみ
    )

    v2_db, _ = _run_b03_b04(measurements_db, registry_db, tmp_path)
    projections = b05.build_projections(v2_db, registry_db)

    zy_columns, zy_rows = projections["zone_year"]
    idx = {c: i for i, c in enumerate(zy_columns)}
    assert len(zy_rows) == 1
    row = zy_rows[0]
    assert row[idx["n_sites"]] == 1
    assert row[idx["n"]] == 2  # S1 の2件のみ（S2の1件は含まない）
    assert row[idx["avg"]] == 3.0

    zc_columns, zc_rows = projections["zone_clim"]
    cidx = {c: i for i, c in enumerate(zc_columns)}
    assert len(zc_rows) == 1
    crow = zc_rows[0]
    assert crow[cidx["n_sites"]] == 1
    assert crow[cidx["n"]] == 2
    assert crow[cidx["avg"]] == 3.0


def test_zone_year_and_zone_clim_are_empty_without_any_place_relation(tmp_path):
    """`place_relation` が空（既定フィクスチャ）でも例外にならず、
    zone_year/zone_clim は空のまま作られる——ゾーンを持たない大半の既存
    フィクスチャテストがそのまま動くことの根拠。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db)
    make_registry_db(registry_db)  # place_relations 省略 = 空

    v2_db, _ = _run_b03_b04(measurements_db, registry_db, tmp_path)
    projections = b05.build_projections(v2_db, registry_db)

    assert projections["zone_year"][1] == []
    assert projections["zone_clim"][1] == []


def test_non_zone_within_edges_do_not_block_or_affect_zone_projection(tmp_path):
    """`place_relation` に `'within'` 辺が増えても、`sites.zone` に解決できない
    もの（地点→流域、流域→地域で `fraction<1`）は `site_zone_lookup` の JOIN
    条件（`place_source_ref(source_id='sites.zone')`）に一致しないため、
    ゾーンの検証にも zone_year/zone_clim の値にも一切影響しない。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db, rows=_ZONE_BOD_ROWS)
    non_zone_places = [("place_ws1", "common", "watershed"), ("place_region1", "common", "region")]
    make_registry_db(
        registry_db,
        places=PLACES_WITH_ZONE + non_zone_places,
        place_refs=PLACE_REFS_WITH_ZONE,
        place_relations=[
            ("place_zone1", "place_s1", "within", 1.0, "test"),
            ("place_zone1", "place_s2", "within", 1.0, "test"),
            # 地点→流域（sites.zone に解決されないので site_zone_lookup には現れない）
            ("place_ws1", "place_s1", "within", 1.0, "site->watershed"),
            # 流域→地域、fraction<1（同上。fraction 検証の対象にもならない）
            ("place_region1", "place_ws1", "within", 0.3, "watershed->region"),
        ],
    )

    v2_db, _ = _run_b03_b04(measurements_db, registry_db, tmp_path)
    projections = b05.build_projections(v2_db, registry_db)  # 例外を投げなければ良い

    zy_columns, zy_rows = projections["zone_year"]
    idx = {c: i for i, c in enumerate(zy_columns)}
    assert len(zy_rows) == 1
    row = zy_rows[0]
    assert row[idx["n_sites"]] == 2
    assert row[idx["n"]] == 3
    assert row[idx["avg"]] == 6.5


def test_zone_clim_averages_meas_month_values_not_raw_daily_observations(tmp_path):
    """`zone_clim` は `meas_month`（(site, year-month) ごとに日次値を平均した
    もの）の `avg` を `AVG()` する——`meas_daily`（生の日次値）を月番号だけで
    直接平均するのではない。S1 に、同じ月（1月）だが年が異なる2つの
    meas_month 行を持たせる（2020-01: 2日分の平均=3.0、2021-01: 1日のみ=100.0）。

    - 正しい実装（meas_month.avg を平均）: AVG(3.0, 100.0) = 51.5
    - 誤った実装（全日次値を月番号だけで直接平均）: AVG(1.0, 5.0, 100.0)
      ≈ 35.33（日数の多い年に引っ張られる）

    この2つの値は明確に異なるため区別できる。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(
        measurements_db,
        rows=[
            ("m1", "S1", "2020-01-01", "BOD", "src_a", 1.0, "1.0", "mg/L", "公開済", 0, "ref1", "ev1"),
            ("m2", "S1", "2020-01-02", "BOD", "src_a", 5.0, "5.0", "mg/L", "公開済", 0, "ref1", "ev1"),
            ("m3", "S1", "2021-01-15", "BOD", "src_a", 100.0, "100.0", "mg/L", "公開済", 0, "ref1", "ev1"),
        ],
    )
    make_registry_db(
        registry_db,
        places=PLACES_WITH_ZONE,
        place_refs=PLACE_REFS_WITH_ZONE,
        place_relations=DEFAULT_PLACE_RELATIONS,
    )

    v2_db, _ = _run_b03_b04(measurements_db, registry_db, tmp_path)
    projections = b05.build_projections(v2_db, registry_db)

    zc_columns, zc_rows = projections["zone_clim"]
    idx = {c: i for i, c in enumerate(zc_columns)}
    assert len(zc_rows) == 1
    row = zc_rows[0]
    assert row[idx["month"]] == 1
    assert row[idx["n_sites"]] == 1
    assert row[idx["n"]] == 3  # meas_month.n の合計（2020-01の2 + 2021-01の1）
    assert row[idx["avg"]] == 51.5  # AVG(3.0, 100.0)。meas_month 経由でないと出ない値


def test_zone_year_keeps_daily_and_annual_kind_separate(tmp_path):
    """`zone_year` は `(zone, variable, kind, year)` でグループ化する——同じ
    ゾーン・変数・年でも `kind`（'daily'/'annual'）が違えば別行のまま混ざら
    ないことを確認する。S1 の日次由来の BOD（kind='daily'）と、別 alias
    （grain='year' 宣言）による年次直接値（kind='annual'）を同じ年（2020）に
    持たせる。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(
        measurements_db,
        rows=[
            ("m1", "S1", "2020-01-01", "BOD", "src_a", 1.0, "1.0", "mg/L", "公開済", 0, "ref1", "ev1"),
            ("m2", "S1", "2020-01-02", "BOD", "src_a", 5.0, "5.0", "mg/L", "公開済", 0, "ref1", "ev1"),
            ("m3", "S1", "2020", "BOD", "src_b", 50.0, "50.0", "mg/L", "公開済", 0, "ref2", "ev2"),
        ],
    )
    make_registry_db(
        registry_db,
        aliases=DEFAULT_ALIASES + [
            (
                "measurements", "BOD", "src_b", "common:variable:water.bod_annual",
                "common:unit:mg_per_l", None, "year",
            ),
        ],
        places=PLACES_WITH_ZONE,
        place_refs=PLACE_REFS_WITH_ZONE,
        place_relations=DEFAULT_PLACE_RELATIONS,
    )

    v2_db, _ = _run_b03_b04(measurements_db, registry_db, tmp_path)
    projections = b05.build_projections(v2_db, registry_db)

    zy_columns, zy_rows = projections["zone_year"]
    idx = {c: i for i, c in enumerate(zy_columns)}
    by_kind = {row[idx["kind"]]: row for row in zy_rows}
    assert set(by_kind) == {"daily", "annual"}
    assert by_kind["daily"][idx["year"]] == 2020
    assert by_kind["daily"][idx["avg"]] == 3.0
    assert by_kind["annual"][idx["year"]] == 2020
    assert by_kind["annual"][idx["avg"]] == 50.0


def test_meas_month_materialization_preserves_value_and_type(tmp_path):
    """`meas_month` を一時テーブルに実体化しても（このタスクで
    `_MEAS_MONTH_SQL` を直接 SELECT する形から変更した）、値・型が変わらない
    ことを確認する（`AVG()` の REAL の 3.0 が INTEGER の 3 にならない等）。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(
        measurements_db,
        rows=[
            ("m1", "S1", "2020-01-01", "BOD", "src_a", 2.0, "2.0", "mg/L", "公開済", 0, "ref1", "ev1"),
            ("m2", "S1", "2020-01-02", "BOD", "src_a", 4.0, "4.0", "mg/L", "公開済", 0, "ref1", "ev1"),
        ],
    )
    make_registry_db(registry_db)

    v2_db, _ = _run_b03_b04(measurements_db, registry_db, tmp_path)
    projections = b05.build_projections(v2_db, registry_db)

    columns, rows = projections["meas_month"]
    idx = {c: i for i, c in enumerate(columns)}
    assert len(rows) == 1
    row = rows[0]
    assert row[idx["avg"]] == 3.0
    assert isinstance(row[idx["avg"]], float)  # INTEGER の 3 にならない
    assert row[idx["n"]] == 2
    assert isinstance(row[idx["n"]], int)


def test_build_projections_raises_when_zone_edge_fraction_is_not_one(tmp_path):
    """検証 (a): `site_zone_lookup` 上で `fraction<>1.0` が1件でもあれば
    `build_projections` 経由で止まる。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db, rows=_ZONE_BOD_ROWS)
    make_registry_db(
        registry_db,
        places=PLACES_WITH_ZONE,
        place_refs=PLACE_REFS_WITH_ZONE,
        place_relations=[("place_zone1", "place_s1", "within", 0.5, "test")],
    )
    v2_db, _ = _run_b03_b04(measurements_db, registry_db, tmp_path)

    with pytest.raises(common.MigrationError, match="fraction が1.0でない"):
        b05.build_projections(v2_db, registry_db)


def test_build_projections_raises_when_site_belongs_to_multiple_zones(tmp_path):
    """検証 (b): 1つの地点が2つの異なるゾーン（番号も別）に属していれば
    `build_projections` 経由で止まる。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db, rows=_ZONE_BOD_ROWS)
    zone_places = [("place_zone1", "jp-14", "zone"), ("place_zone2", "jp-14", "zone")]
    zone_refs = [("place_zone1", "1", "sites.zone"), ("place_zone2", "2", "sites.zone")]
    make_registry_db(
        registry_db,
        places=DEFAULT_PLACES + zone_places,
        place_refs=DEFAULT_PLACE_REFS + zone_refs,
        place_relations=[
            ("place_zone1", "place_s1", "within", 1.0, "test"),
            ("place_zone2", "place_s1", "within", 1.0, "test"),  # S1 が2つ目のゾーンにも属す
        ],
    )
    v2_db, _ = _run_b03_b04(measurements_db, registry_db, tmp_path)

    with pytest.raises(common.MigrationError, match="複数のゾーンに属する"):
        b05.build_projections(v2_db, registry_db)


def test_build_projections_raises_when_zone_number_collides_across_zone_places(tmp_path):
    """検証 (c): 異なる place_id を持つ2つのゾーンが同じゾーン番号
    （`external_key`）に解決されていれば `build_projections` 経由で止まる
    （将来の2地域目を想定した検証）。S1/S2 はそれぞれ単一のゾーンにしか
    属さないため、検証 (b)（地点の単一ゾーン所属）には引っかからない。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db, rows=_ZONE_BOD_ROWS)
    zone_places = [("place_zoneA", "jp-14", "zone"), ("place_zoneB", "jp-13", "zone")]
    zone_refs = [("place_zoneA", "1", "sites.zone"), ("place_zoneB", "1", "sites.zone")]  # 両方 "1"
    make_registry_db(
        registry_db,
        places=DEFAULT_PLACES + zone_places,
        place_refs=DEFAULT_PLACE_REFS + zone_refs,
        place_relations=[
            ("place_zoneA", "place_s1", "within", 1.0, "test"),
            ("place_zoneB", "place_s2", "within", 1.0, "test"),
        ],
    )
    v2_db, _ = _run_b03_b04(measurements_db, registry_db, tmp_path)

    with pytest.raises(common.MigrationError, match="同じゾーン番号に解決されている"):
        b05.build_projections(v2_db, registry_db)


def test_build_projections_raises_with_helpful_error_when_registry_predates_place_relation(tmp_path):
    """`place_relation` テーブルを持たない古い registry.sqlite（ADR-0022 より
    前にビルドしたもの相当）を渡すと、素の `OperationalError`（"no such
    table"）ではなく、r01 の再実行を促す `MigrationError` になる。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db)
    make_registry_db(registry_db)

    conn = sqlite3.connect(str(registry_db))
    conn.execute("DROP TABLE place_relation")
    conn.commit()
    conn.close()

    v2_db, _ = _run_b03_b04(measurements_db, registry_db, tmp_path)

    with pytest.raises(common.MigrationError, match="r01_build_registry.py"):
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
    stats = b05.verify_hourly_daily_rollup(work)
    assert stats["n_series_days_checked"] >= 1


# ---------------------------------------------------------------------------
# B-6: 読む grain の宣言（定数）と、実際に読む SQL の WHERE が一致していること
# ---------------------------------------------------------------------------

def test_sensor_alias_grains_is_the_union_of_day_keyed_and_label25_grains():
    """`_SENSOR_ALIAS_GRAINS`（`assert_alias_is_function` に渡す grain 集合）が
    `_DAY_KEYED_INPUT_GRAINS` と `_LABEL25_VALUE_GRAINS` の和集合そのもので
    あることを確認する（3箇所が手書きのタプルとして食い違う事故を防ぐ）。
    `'month'`（jma_monthly の積雪 alias の表記ゆれ）がどちらにも含まれない
    ——射影が消費しない grain は検証対象に含めない——という意図も確認する。
    """
    assert set(b05._SENSOR_ALIAS_GRAINS) == set(b05._DAY_KEYED_INPUT_GRAINS) | set(b05._LABEL25_VALUE_GRAINS)
    assert "month" not in b05._SENSOR_ALIAS_GRAINS


def test_day_keyed_sql_where_matches_declared_grains():
    """`_day_keyed_sql()` の WHERE 句が `_DAY_KEYED_INPUT_GRAINS` から作った
    IN リストをそのまま含んでいる（SQL がこの定数から作られている——手書きの
    別タプルに乖離していない）ことを、生成された SQL テキストを見て確認する。
    """
    sql = b05._day_keyed_sql()
    assert f"c.input_grain IN ({b05._sql_in_clause(b05._DAY_KEYED_INPUT_GRAINS)})" in sql
    for grain in b05._DAY_KEYED_INPUT_GRAINS:
        assert f"'{grain}'" in sql


def test_label25_obs_keyed_sql_where_matches_declared_grains():
    """`_label25_obs_keyed_sql()` の WHERE 句が `_LABEL25_VALUE_GRAINS` から
    作った IN リストをそのまま含んでいることを確認する（同上）。
    """
    sql = b05._label25_obs_keyed_sql()
    assert f"value_grain IN ({b05._sql_in_clause(b05._LABEL25_VALUE_GRAINS)})" in sql
    for grain in b05._LABEL25_VALUE_GRAINS:
        assert f"'{grain}'" in sql
