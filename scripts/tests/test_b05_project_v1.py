"""scripts/b05_project_v1.py の統合テスト。"""
import sqlite3

import pytest

import b03_build_observation as b03
import b04_build_cube as b04
import b05_project_v1 as b05
from migrate import common

from .migrate_fixtures import make_registry_db


def _run_b03_b04(measurements_db, registry_db, tmp_path):
    """b03（`observation` 生成）→ b04（キューブ）を通しで実行し、b05 の入力に
    なる v2_db のパスと `b04.build_cube()` の戻り値（stats）を返す（b05 の
    統合テストで共通の配線。5箇所で使う）。
    """
    v2_db = tmp_path / "v2.sqlite"
    rows, _ = b03.build_observation(measurements_db, registry_db, tmp_path / "no_exceptions.yaml")
    b03.write_observation(rows, v2_db)
    conn = sqlite3.connect(str(v2_db))
    try:
        stats = b04.build_cube(conn)
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
    finally:
        work.close()


def test_end_to_end_pivot_and_labels(tmp_path):
    """b03 → b04 → b05 を通しで動かし、`meas_year` のピボット（mean/min/max を
    1行に）とラベルの引き戻し（site_id/variable/unit）を確認する。
    """
    from .migrate_fixtures import make_measurements_db

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
    """`assert_alias_is_function`（変更5）が検証するのは
    `(variable_id, grain, stat, unit_id) → alias` の関数性で、これが崩れていなくても、
    **逆向き**（`alias → tuple`）が関数でないと v1 の `GROUP BY variable` を復元
    できない（アドバイザー指摘）。同じ alias 'pH' を、異なる variable_id/unit_id を
    持つ2つの出典（src_a/src_b）に割り当て、同じ site×day に両方の観測があると、
    b04 は（tuple が違うので）2セル作り、射影は同じ (site_id, variable, d) の行を
    2つ出してしまう——これを b03→b04→b05 の通しで検出できることを確認する。
    """
    from .migrate_fixtures import make_measurements_db

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
    assert stats["n_day"] == 2  # b04 自体は2つの別セルとして正常に作る（キーが違うため）

    with pytest.raises(common.MigrationError, match="v1 のキー"):
        b05.build_projections(v2_db, registry_db)


def test_meas_clim_mixes_series_sharing_alias_across_sites(tmp_path):
    """`meas_clim` は `site_id` を GROUP BY に持たない（v1 の
    `web/scripts/build-derived.mjs` の `meas_clim` も同様。`FROM meas_daily
    GROUP BY variable, month`）。異なる出典・異なる site（＝異なる
    `(variable_id, grain, stat, unit_id)` の系列）が同じ alias 文字列
    （ここでは 'pH'）を名乗っていれば、月別平年値では区別されずに1本の平均へ
    混ざる——これが `docs/plans/PHASE_B_FACT_SLICE.md` §6 に記録した
    「v1 の癖」の実装側の確認（オーナー決定1）。`meas_daily`/`meas_month`/
    `meas_year` は `site_id` がキーに残るので、この2系列は別々の行のまま
    （`assert_v1_keys_are_unique` に引っかからない）。
    """
    from .migrate_fixtures import make_measurements_db

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
    ソースにする。同じ site・同じ alias 文字列 'BOD' に、日次積み上げ由来の年
    （2020）と出典が直接配った年次値（2019、別の出典・別の variable_id）の
    両方があるとき、`site_var` が `kind` ごとに別行になり、`var_catalog` の
    `n_daily`/`n_annual` がそれぞれの `n` を正しく振り分けることを確認する。
    """
    from .migrate_fixtures import make_measurements_db

    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(
        measurements_db,
        rows=[
            # 日次観測2件（2020年）→ meas_year(kind='daily', year=2020, n=2)
            ("m1", "S1", "2020-01-01", "BOD", "src_a", 1.0, "1.0", "mg/L", "公開済", 0, "ref1", "ev1"),
            ("m2", "S1", "2020-06-01", "BOD", "src_a", 5.0, "5.0", "mg/L", "公開済", 0, "ref1", "ev1"),
            # 出典が直接配った年次値1件（2019年度・別出典）
            # → meas_year(kind='annual', year=2019, n=1)
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
    assert daily[idx["site_id"]] == "S1"
    assert daily[idx["variable"]] == "BOD"
    assert daily[idx["n"]] == 2
    assert daily[idx["y_from"]] == 2020
    assert daily[idx["y_to"]] == 2020
    assert daily[idx["avg"]] == 3.0  # AVG(avg) over 年 = meas_year(2020).avg = (1+5)/2
    annual = by_kind["annual"]
    assert annual[idx["n"]] == 1
    assert annual[idx["y_from"]] == 2019
    assert annual[idx["y_to"]] == 2019
    assert annual[idx["avg"]] == 4.5

    vc_columns, vc_rows = projections["var_catalog"]
    vidx = {c: i for i, c in enumerate(vc_columns)}
    assert len(vc_rows) == 1
    row = vc_rows[0]
    assert row[vidx["variable"]] == "BOD"
    assert row[vidx["n"]] == 3  # 2（daily） + 1（annual）
    assert row[vidx["n_sites"]] == 1
    assert row[vidx["y_from"]] == 2019
    assert row[vidx["y_to"]] == 2020
    assert row[vidx["n_daily"]] == 2
    assert row[vidx["n_annual"]] == 1
    assert row[vidx["n_censored"]] == 0


def test_load_v1_keys_covers_all_six_tables():
    """`_load_v1_keys`（`assert_v1_keys_are_unique` に渡すキー列の出所）が、
    追加した3テーブル（`meas_clim`/`site_var`/`var_catalog`）ぶんも
    `reports/derived_baseline.json`（コミット済みの小さな指紋ファイル。本物の
    `data/db/*.sqlite` は不要）からちゃんと読めることを確認する（受け入れ条件6）。
    """
    keys = b05._load_v1_keys(b05.DEFAULT_BASELINE_JSON)
    assert keys["meas_clim"] == ["variable", "month"]
    assert keys["site_var"] == ["site_id", "variable", "kind"]
    assert keys["var_catalog"] == ["variable"]


def test_assert_v1_keys_are_unique_detects_duplicate_in_new_tables():
    """`assert_v1_keys_are_unique` 自体（受け入れ条件6）が、新しい3テーブルの
    キー形（1列だけの `var_catalog`、3列の `site_var`）でも重複を検出することを
    直接確認する。`meas_clim`/`site_var`/`var_catalog` は v1 のキー列そのもので
    `GROUP BY` するので実データで重複が起きることは構造的に無い
    （`build_projections` の統合テストでは再現できない）が、チェック関数自体が
    汎用（テーブル名で分岐しない）であることは、このように直接呼び出せば確認できる。
    """
    projections = {
        "var_catalog": (
            ["variable", "unit", "n"],
            [("BOD", "mg/L", 3), ("BOD", "mg/L", 5)],  # variable='BOD' が重複
        ),
    }
    keys_by_table = {"var_catalog": ["variable"]}
    with pytest.raises(common.MigrationError, match="v1 のキー"):
        b05.assert_v1_keys_are_unique(projections, keys_by_table)

    # site_var（3列キー）でも同様に働くことを確認する。
    projections2 = {
        "site_var": (
            ["site_id", "variable", "kind", "n"],
            [("S1", "BOD", "daily", 2), ("S1", "BOD", "daily", 9)],  # 3列とも重複
        ),
    }
    keys_by_table2 = {"site_var": ["site_id", "variable", "kind"]}
    with pytest.raises(common.MigrationError, match="v1 のキー"):
        b05.assert_v1_keys_are_unique(projections2, keys_by_table2)


def test_place_lookup_non_injective_place_id_raises_migration_error(tmp_path):
    """`place_source_ref`（`source_id='sites.site_id'`）が `place_id` について単射で
    ないと（同じ place_id に複数の site_id が対応している）、素の
    `sqlite3.IntegrityError`（`CREATE UNIQUE INDEX` が投げる）ではなく、実例つきの
    `MigrationError` で止まることを確認する（変更6）。
    """
    from .migrate_fixtures import make_measurements_db

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
