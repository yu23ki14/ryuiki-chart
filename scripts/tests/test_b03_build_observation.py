"""scripts/b03_build_observation.py の統合テスト。

本物の `data/db/ryuiki.sqlite`/`registry.sqlite`（14GB・828MB）を要さず、
`scripts/tests/migrate_fixtures.py` の小さな自作 sqlite だけで完結する。
"""
import pytest

import b03_build_observation as b03
from migrate import common
from reconcile import common as reconcile_common
from reconcile import datasource

from .migrate_fixtures import make_measurements_db, make_registry_db


def test_normal_case_resolves_all_rows_and_maps_censoring(tmp_path):
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db)
    make_registry_db(registry_db)

    rows, stats = b03.build_observation(measurements_db, registry_db, tmp_path / "no_exceptions.yaml")

    assert stats["n_observation"] == 3
    assert stats["total_measurements"] == 3
    # censoring: m1='none'（1.2）, m2='below_lod'（<0.5）, m3='none'（12.3）
    assert stats["censoring_counts"] == {"none": 2, "below_lod": 1}
    assert stats["zero_imputed_count"] == 1
    assert stats["grain_mismatch_count"] == 0

    by_id = {r[0]: r for r in rows}
    # value_num は censoring='none' のときだけ運ぶ（D2）。below_lod は NULL。
    assert by_id["m1"][13] == 1.2  # value_num
    assert by_id["m2"][13] is None  # value_num (below_lod)
    assert by_id["m2"][15] == "below_lod"  # censoring
    assert by_id["m2"][16] == 0.5  # censoring_limit
    # region_id/place_id/place_kind はハードコードせず place 経由で解決している。
    assert by_id["m1"][1] == "jp-14"  # region_id
    assert by_id["m1"][3] == "site"  # place_kind


def test_unresolved_alias_raises_with_count_and_example(tmp_path):
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    # "kion" だけを alias として残し、"BOD" を解決不能にする。
    make_measurements_db(measurements_db)
    make_registry_db(
        registry_db,
        aliases=[("measurements", "kion", "src_a", "common:variable:weather.air_temp", "common:unit:degc", None, "day")],
    )

    with pytest.raises(common.MigrationError, match="variable_alias で解決できない"):
        b03.build_observation(measurements_db, registry_db, tmp_path / "no_exceptions.yaml")


def test_unresolved_place_raises(tmp_path):
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db)
    make_registry_db(
        registry_db,
        place_refs=[("place_s1", "S1", "sites.site_id")],  # S2 の解決先が無い
    )

    with pytest.raises(common.MigrationError, match="place_source_ref で解決できない"):
        b03.build_observation(measurements_db, registry_db, tmp_path / "no_exceptions.yaml")


def test_period_mismatch_without_declared_exception_raises(tmp_path):
    """value_grain='day' の alias なのに measured_on が4桁（年度番号）しか無い行は、
    period_exceptions.yaml に宣言が無ければ止まる（design.md D4）。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(
        measurements_db,
        rows=[("m1", "S1", "2020", "BOD", "src_a", 1.2, "1.2", "mg/L", "公開済", 0, "ref1", "ev1")],
    )
    make_registry_db(registry_db)

    with pytest.raises(common.MigrationError, match="value_grain と period_grain が食い違い"):
        b03.build_observation(measurements_db, registry_db, tmp_path / "no_exceptions.yaml")


def test_period_mismatch_covered_by_exception_succeeds(tmp_path):
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(
        measurements_db,
        rows=[("m1", "S1", "2020", "BOD", "src_a", 1.2, "1.2", "mg/L", "公開済", 0, "ref1", "ev1")],
    )
    make_registry_db(registry_db)
    exceptions_yaml = tmp_path / "exceptions.yaml"
    exceptions_yaml.write_text(
        "src_a:\n"
        "  period_grain_override: fiscal_year\n"
        "  expected_row_count: 1\n"
        "  reason: テスト\n"
        "  restoration_plan: テスト\n",
        encoding="utf-8",
    )

    rows, stats = b03.build_observation(measurements_db, registry_db, exceptions_yaml)
    assert stats["n_observation"] == 1
    assert stats["grain_mismatch_count"] == 1
    assert stats["exception_usage"] == {"src_a": 1}


def test_exception_entry_never_matched_raises(tmp_path):
    """例外表のエントリが1件も当たらなかったら止まる（腐った例外を放置しない）。"""
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db)  # value_grain==period_grain の行しかない
    make_registry_db(registry_db)
    exceptions_yaml = tmp_path / "exceptions.yaml"
    exceptions_yaml.write_text(
        "never_appears:\n"
        "  period_grain_override: fiscal_year\n"
        "  reason: テスト\n"
        "  restoration_plan: テスト\n",
        encoding="utf-8",
    )

    with pytest.raises(common.MigrationError, match="1件も該当しなかった"):
        b03.build_observation(measurements_db, registry_db, exceptions_yaml)


def test_expected_row_count_mismatch_raises(tmp_path):
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(
        measurements_db,
        rows=[("m1", "S1", "2020", "BOD", "src_a", 1.2, "1.2", "mg/L", "公開済", 0, "ref1", "ev1")],
    )
    make_registry_db(registry_db)
    exceptions_yaml = tmp_path / "exceptions.yaml"
    exceptions_yaml.write_text(
        "src_a:\n"
        "  period_grain_override: fiscal_year\n"
        "  expected_row_count: 999\n"
        "  reason: テスト\n"
        "  restoration_plan: テスト\n",
        encoding="utf-8",
    )

    with pytest.raises(common.MigrationError, match="expected_row_count と実測件数が食い違う"):
        b03.build_observation(measurements_db, registry_db, exceptions_yaml)


def test_running_twice_yields_identical_content_hash(tmp_path):
    """決定論: 同じ入力に対して b03 を2回実行すると observation の content_hash が
    バイト一致する（受け入れ条件2の単体テスト版）。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db)
    make_registry_db(registry_db)

    out1 = tmp_path / "v2_1.sqlite"
    out2 = tmp_path / "v2_2.sqlite"
    rows1, _ = b03.build_observation(measurements_db, registry_db, tmp_path / "no_exceptions.yaml")
    b03.write_observation(rows1, out1)
    rows2, _ = b03.build_observation(measurements_db, registry_db, tmp_path / "no_exceptions.yaml")
    b03.write_observation(rows2, out2)

    def fingerprint(path):
        conn = reconcile_common.open_readonly(path)
        src = datasource.SqliteSource(conn)
        columns = src.columns("observation")
        numeric = reconcile_common.numeric_columns_of(conn, "observation", columns)
        fp = reconcile_common.compute_fingerprint(src, "observation", columns, ["source_measurement_id"], numeric)
        conn.close()
        return fp["content_hash"]

    assert fingerprint(out1) == fingerprint(out2)
