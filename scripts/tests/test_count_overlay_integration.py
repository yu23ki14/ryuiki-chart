"""件数の宣言の上書き（Issue #29 A-2）が、`scripts/migrate/period.py` 以外の
読み込み関数（`source_regions.load_source_regions`・
`occurrence_period.load_period_shapes`・b07/b08/b09 の
`load_and_validate_*_declarations`）にも正しく効くことの統合テスト。
tmp_path に自前の小さな宣言 YAML を書くだけで、原本DB・data/sample/ の実データは
一切使わない。
"""
from __future__ import annotations

import b07_build_occurrence_cube as b07
import b08_project_occurrence_v1 as b08
import b09_build_occurrence_place as b09
from migrate import occurrence_period, source_regions


def test_source_regions_count_overlay_applies_only_to_sources(tmp_path):
    path = tmp_path / "source_regions.yaml"
    path.write_text(
        "sources:\n"
        "  gbif_kanagawa_occurrences:\n"
        "    region_id: jp-14\n"
        "    consumer: occurrence\n"
        "    expected_row_count: 658360\n"
        "    evidence: e\n"
        "regions:\n"
        "  jp-14:\n"
        "    utc_offset: '+09:00'\n"
        "    evidence: e\n",
        encoding="utf-8",
    )
    sources, regions = source_regions.load_source_regions(
        path, consumer="occurrence", count_overlay={"gbif_kanagawa_occurrences": 10}
    )
    assert sources["gbif_kanagawa_occurrences"].expected_row_count == 10
    assert regions["jp-14"].utc_offset == "+09:00"


def test_occurrence_period_shapes_count_overlay(tmp_path):
    path = tmp_path / "occurrence_period_shapes.yaml"
    path.write_text("year:\n  expected_row_count: 1797\n  note: n\n", encoding="utf-8")
    shapes = occurrence_period.load_period_shapes(path, count_overlay={"year": 3})
    assert shapes["year"].expected_row_count == 3
    assert shapes["year"].note == "n"


def test_b07_cube_declarations_count_overlay(tmp_path):
    path = tmp_path / "occurrence_cube_declarations.yaml"
    path.write_text("leaf_cell_source_rows:\n  expected_row_count: 1191\n  note: n\n", encoding="utf-8")
    declarations = b07.load_and_validate_cube_declarations(path, count_overlay={"leaf_cell_source_rows": 4})
    assert declarations["leaf_cell_source_rows"]["expected_row_count"] == 4


def test_b09_place_declarations_count_overlay(tmp_path):
    path = tmp_path / "occurrence_place_declarations.yaml"
    path.write_text(
        "n_watershed_polygons:\n  expected_row_count: 377\n  note: n\n"
        "place_id_null_count:\n  expected_row_count: 86285\n  note: n\n"
        "resolved_count:\n  expected_row_count: 737407\n  note: n\n",
        encoding="utf-8",
    )
    declarations = b09.load_and_validate_place_declarations(
        path, count_overlay={"place_id_null_count": 31, "resolved_count": 186}
    )
    assert declarations["n_watershed_polygons"]["expected_row_count"] == 377
    assert declarations["place_id_null_count"]["expected_row_count"] == 31
    assert declarations["resolved_count"]["expected_row_count"] == 186


def test_b08_watershed_declarations_count_overlay_updates_breakdown_and_total(tmp_path):
    path = tmp_path / "occurrence_watershed_v1_declarations.yaml"
    path.write_text(
        "memo_moved_records:\n"
        "  expected_count: 11306\n"
        "  breakdown:\n"
        "    ws_to_ws: 9428\n"
        "    v1_assigned_exact_unassigned: 622\n"
        "    v1_unassigned_exact_assigned: 1256\n"
        "  note: n\n"
        "memo_mixed_buckets:\n"
        "  expected_count: 741\n"
        "  note: n\n"
        "org_watershed_year_keys_changed_vs_exact:\n"
        "  expected_count: 1091\n"
        "  note: n\n",
        encoding="utf-8",
    )
    overlay = {
        "memo_moved_records": 1,
        "memo_moved_records.ws_to_ws": 0,
        "memo_moved_records.v1_assigned_exact_unassigned": 1,
        "memo_moved_records.v1_unassigned_exact_assigned": 0,
        "memo_mixed_buckets": 1,
        "org_watershed_year_keys_changed_vs_exact": 1,
    }
    declarations = b08.load_and_validate_watershed_declarations(path, count_overlay=overlay)
    assert declarations["memo_moved_records"]["expected_count"] == 1
    assert declarations["memo_moved_records"]["breakdown"] == {
        "ws_to_ws": 0, "v1_assigned_exact_unassigned": 1, "v1_unassigned_exact_assigned": 0,
    }
    assert declarations["memo_mixed_buckets"]["expected_count"] == 1
    assert declarations["org_watershed_year_keys_changed_vs_exact"]["expected_count"] == 1


def test_b08_watershed_declarations_count_overlay_self_consistency_still_checked(tmp_path):
    """`apply_count_overlay` 適用後の値でも、breakdown の合計が expected_count と
    食い違えば自己矛盾として止まる（上書きが検証をすり抜けない）。
    """
    import pytest

    from migrate.common import MigrationError

    path = tmp_path / "occurrence_watershed_v1_declarations.yaml"
    path.write_text(
        "memo_moved_records:\n"
        "  expected_count: 3\n"
        "  breakdown:\n"
        "    ws_to_ws: 1\n"
        "    v1_assigned_exact_unassigned: 1\n"
        "    v1_unassigned_exact_assigned: 1\n"
        "  note: n\n"
        "memo_mixed_buckets:\n"
        "  expected_count: 1\n"
        "  note: n\n"
        "org_watershed_year_keys_changed_vs_exact:\n"
        "  expected_count: 1\n"
        "  note: n\n",
        encoding="utf-8",
    )
    # 上書きで合計(0+0+0=0)が expected_count(9) と食い違う状態にする。
    overlay = {
        "memo_moved_records": 9,
        "memo_moved_records.ws_to_ws": 0,
        "memo_moved_records.v1_assigned_exact_unassigned": 0,
        "memo_moved_records.v1_unassigned_exact_assigned": 0,
    }
    with pytest.raises(MigrationError):
        b08.load_and_validate_watershed_declarations(path, count_overlay=overlay)
