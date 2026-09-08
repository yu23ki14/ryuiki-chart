"""scripts/b05_project_v1.py の統合テスト。"""
import sqlite3

import pytest

import b03_build_observation as b03
import b04_build_cube as b04
import b05_project_v1 as b05
from migrate import common

from .migrate_fixtures import make_registry_db


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

    v2_db = tmp_path / "v2.sqlite"
    rows, _ = b03.build_observation(measurements_db, registry_db, tmp_path / "no_exceptions.yaml")
    b03.write_observation(rows, v2_db)

    conn = sqlite3.connect(str(v2_db))
    try:
        b04.build_cube(conn)
    finally:
        conn.close()

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

    v2_db = tmp_path / "v2.sqlite"
    rows, _ = b03.build_observation(measurements_db, registry_db, tmp_path / "no_exceptions.yaml")
    b03.write_observation(rows, v2_db)

    conn = sqlite3.connect(str(v2_db))
    try:
        stats = b04.build_cube(conn)
    finally:
        conn.close()
    assert stats["n_day"] == 2  # b04 自体は2つの別セルとして正常に作る（キーが違うため）

    with pytest.raises(common.MigrationError, match="v1 のキー"):
        b05.build_projections(v2_db, registry_db)


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

    v2_db = tmp_path / "v2.sqlite"
    rows, _ = b03.build_observation(measurements_db, registry_db, tmp_path / "no_exceptions.yaml")
    b03.write_observation(rows, v2_db)
    conn = sqlite3.connect(str(v2_db))
    try:
        b04.build_cube(conn)
    finally:
        conn.close()

    with pytest.raises(common.MigrationError, match="単射でない"):
        b05.build_projections(v2_db, registry_db)
