"""scripts/b09_build_occurrence_place.py の統合テスト。

本物の `data/db/*.sqlite`・GeoJSON を要さず、`scripts/tests/occurrence_fixtures.py`
の小さなフィクスチャだけで完結する。
"""
import sqlite3

import pytest

import b09_build_occurrence_place as b09
from migrate import common

from .occurrence_fixtures import (
    make_occurrence_place_declarations_yaml,
    make_occurrence_registry_db,
    make_ryuiki_sites_db,
    make_v2_db_with_occurrence,
    occurrence_row_at,
    write_watershed_geojson,
)

# W1: lon [139.0, 139.1] x lat [35.0, 35.1] の正方形。
_W1_RINGS = [[[139.0, 35.0], [139.1, 35.0], [139.1, 35.1], [139.0, 35.1], [139.0, 35.0]]]
# W2: W1 と重なる正方形（lon [139.05, 139.15] x lat [35.05, 35.15]）。
_W2_RINGS = [[[139.05, 35.05], [139.15, 35.05], [139.15, 35.15], [139.05, 35.15], [139.05, 35.05]]]

_W1_PLACE_ID = "common:place:watershed.w1"
_W2_PLACE_ID = "common:place:watershed.w2"


def _setup(tmp_path, *, occurrence_rows, geojson_features, place_refs, sites_rows=(), taxa=()):
    geojson_path = tmp_path / "watersheds.geojson"
    write_watershed_geojson(geojson_path, geojson_features)

    v2_db = tmp_path / "v2.sqlite"
    make_v2_db_with_occurrence(v2_db, occurrence_rows)

    registry_db = tmp_path / "registry.sqlite"
    places = [(pid, None, "watershed") for pid, _ext, _sid in place_refs]
    make_occurrence_registry_db(registry_db, taxa=list(taxa), places=places, place_refs=list(place_refs))

    ryuiki_db = tmp_path / "ryuiki.sqlite"
    make_ryuiki_sites_db(ryuiki_db, list(sites_rows))

    return v2_db, ryuiki_db, registry_db, geojson_path


def _declarations(tmp_path, **kwargs):
    path = tmp_path / "occurrence_place_declarations.yaml"
    make_occurrence_place_declarations_yaml(path, **kwargs)
    return path


def test_resolved_and_null_rows(tmp_path):
    rows = [
        occurrence_row_at("r1", 35.05, 139.05, source_row_id=1),  # W1 の中
        occurrence_row_at("r2", 50.0, 200.0, source_row_id=2),  # どの面にも入らない
    ]
    v2_db, ryuiki_db, registry_db, geojson = _setup(
        tmp_path,
        occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS)],
        place_refs=[(_W1_PLACE_ID, "W1", "watershed_meta.watershed_id")],
    )
    decl = _declarations(tmp_path, n_watershed_polygons=1, place_id_null_count=1, resolved_count=1)

    stats = b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, geojson, decl)
    assert stats["n_total"] == 2
    assert stats["n_resolved"] == 1
    assert stats["n_null"] == 1

    conn = sqlite3.connect(f"file:{v2_db}?mode=ro", uri=True)
    rows_out = dict(conn.execute("SELECT record_id, place_id FROM occurrence_place"))
    assert rows_out["r1"] == _W1_PLACE_ID
    assert rows_out["r2"] is None
    kinds = {r[0] for r in conn.execute("SELECT DISTINCT place_kind FROM occurrence_place")}
    assert kinds == {"watershed"}


def test_records_without_coordinates_get_no_row(tmp_path):
    """座標の無い記録（lat/lon NULL）は occurrence_place に行を持たない
    （母集団は「座標のある全記録」）。
    """
    rows = [
        occurrence_row_at("r1", 35.05, 139.05, source_row_id=1),
        occurrence_row_at("r2", None, None, source_row_id=2),
    ]
    v2_db, ryuiki_db, registry_db, geojson = _setup(
        tmp_path,
        occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS)],
        place_refs=[(_W1_PLACE_ID, "W1", "watershed_meta.watershed_id")],
    )
    decl = _declarations(tmp_path, n_watershed_polygons=1, place_id_null_count=0, resolved_count=1)

    stats = b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, geojson, decl)
    assert stats["n_total"] == 1

    conn = sqlite3.connect(f"file:{v2_db}?mode=ro", uri=True)
    ids = {r[0] for r in conn.execute("SELECT record_id FROM occurrence_place")}
    assert ids == {"r1"}


def test_two_overlapping_polygons_halts(tmp_path):
    rows = [occurrence_row_at("r1", 35.075, 139.075, source_row_id=1)]  # W1 と W2 の両方に入る
    v2_db, ryuiki_db, registry_db, geojson = _setup(
        tmp_path,
        occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS), ("W2", _W2_RINGS)],
        place_refs=[
            (_W1_PLACE_ID, "W1", "watershed_meta.watershed_id"),
            (_W2_PLACE_ID, "W2", "watershed_meta.watershed_id"),
        ],
    )
    decl = _declarations(tmp_path, n_watershed_polygons=2, place_id_null_count=0, resolved_count=1)

    with pytest.raises(common.MigrationError, match="2つ以上"):
        b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, geojson, decl)


def test_geojson_registry_set_mismatch_halts(tmp_path):
    rows = [occurrence_row_at("r1", 35.05, 139.05, source_row_id=1)]
    v2_db, ryuiki_db, registry_db, geojson = _setup(
        tmp_path,
        occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS)],
        # registry 側は別の watershed_id（"W_OTHER"）しか知らない。
        place_refs=[(_W1_PLACE_ID, "W_OTHER", "watershed_meta.watershed_id")],
    )
    decl = _declarations(tmp_path, n_watershed_polygons=1, place_id_null_count=0, resolved_count=1)

    with pytest.raises(common.MigrationError, match="watershed_id"):
        b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, geojson, decl)


def test_declaration_count_mismatch_halts(tmp_path):
    rows = [occurrence_row_at("r1", 35.05, 139.05, source_row_id=1)]
    v2_db, ryuiki_db, registry_db, geojson = _setup(
        tmp_path,
        occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS)],
        place_refs=[(_W1_PLACE_ID, "W1", "watershed_meta.watershed_id")],
    )
    # resolved_count を実際の値(1)と食い違わせる。
    decl = _declarations(tmp_path, n_watershed_polygons=1, place_id_null_count=0, resolved_count=999)

    with pytest.raises(common.MigrationError, match="宣言"):
        b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, geojson, decl)


def test_site_watershed_edge_mismatch_halts(tmp_path):
    rows = [occurrence_row_at("r1", 35.05, 139.05, source_row_id=1)]
    v2_db, ryuiki_db, registry_db, geojson = _setup(
        tmp_path,
        occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS)],
        place_refs=[(_W1_PLACE_ID, "W1", "watershed_meta.watershed_id")],
        # この地点は実際には W1 の中だが、sites.watershed は別の値を申告している。
        sites_rows=[("site_a", 35.05, 139.05, "W_WRONG")],
    )
    decl = _declarations(tmp_path, n_watershed_polygons=1, place_id_null_count=0, resolved_count=1)

    with pytest.raises(common.MigrationError, match="sites.watershed"):
        b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, geojson, decl)


def test_site_watershed_edge_matches_passes(tmp_path):
    rows = [occurrence_row_at("r1", 35.05, 139.05, source_row_id=1)]
    v2_db, ryuiki_db, registry_db, geojson = _setup(
        tmp_path,
        occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS)],
        place_refs=[(_W1_PLACE_ID, "W1", "watershed_meta.watershed_id")],
        sites_rows=[("site_a", 35.05, 139.05, "W1"), ("site_b", 50.0, 200.0, None)],
    )
    decl = _declarations(tmp_path, n_watershed_polygons=1, place_id_null_count=0, resolved_count=1)

    stats = b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, geojson, decl)
    assert stats["n_checked_sites"] == 2
