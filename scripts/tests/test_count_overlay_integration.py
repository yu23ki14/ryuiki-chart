"""件数の宣言の上書き（Issue #29 A-2）が、`scripts/migrate/period.py` 以外の
読み込み関数（`source_regions.load_source_regions`・
`occurrence_period.load_period_shapes`・b07/b09 の
`load_and_validate_*_declarations`）にも正しく効くことの統合テスト。
tmp_path に自前の小さな宣言 YAML を書くだけで、原本DB・data/sample/ の実データは
一切使わない。
"""
from __future__ import annotations

import b07_build_occurrence_cube as b07
import b09_build_occurrence_place as b09
from migrate import occurrence_period, source_regions

from .manifest_fixtures import write_manifests_from_sources_text


def test_source_regions_count_overlay_applies_only_to_sources(tmp_path):
    path = tmp_path / "manifests"
    write_manifests_from_sources_text(
        path,
        "sources:\n"
        "  gbif_kanagawa_occurrences:\n"
        "    region_id: jp-14\n"
        "    consumer: occurrence\n"
        "    expected_row_count: 658360\n"
        "    evidence: e\n",
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
    path.write_text(
        "leaf_cell_source_rows:\n  expected_row_count: 1191\n  note: n\n"
        "month_cell_source_rows:\n  expected_row_count: 812974\n  note: n\n"
        "watershed_dated_resolved_rows:\n  expected_row_count: 733341\n  note: n\n"
        "watershed_dated_unresolved_rows:\n  expected_row_count: 83515\n  note: n\n",
        encoding="utf-8",
    )
    declarations = b07.load_and_validate_cube_declarations(
        path,
        count_overlay={
            "leaf_cell_source_rows": 4, "month_cell_source_rows": 2,
            "watershed_dated_resolved_rows": 3, "watershed_dated_unresolved_rows": 1,
        },
    )
    assert declarations["leaf_cell_source_rows"]["expected_row_count"] == 4
    assert declarations["month_cell_source_rows"]["expected_row_count"] == 2
    assert declarations["watershed_dated_resolved_rows"]["expected_row_count"] == 3
    assert declarations["watershed_dated_unresolved_rows"]["expected_row_count"] == 1


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
