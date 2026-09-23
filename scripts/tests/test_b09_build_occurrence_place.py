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
# W3: W1 と辺を共有する（重ならない）隣の正方形（lon [139.1, 139.2] x lat [35.0, 35.1]。
# W1 の右辺 lon=139.1 と W3 の左辺 lon=139.1 が同じ——境界上の点のテスト用
# （コードレビュー指摘1）。
_W3_RINGS = [[[139.1, 35.0], [139.2, 35.0], [139.2, 35.1], [139.1, 35.1], [139.1, 35.0]]]

_W1_PLACE_ID = "common:place:watershed.w1"
_W2_PLACE_ID = "common:place:watershed.w2"
_W3_PLACE_ID = "common:place:watershed.w3"


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


def test_point_on_shared_edge_boundary_halts(tmp_path):
    """W1 と W3 が共有する辺（`lon=139.1`）ちょうど上にある座標は、even-odd の
    交差判定だけでは片方に静かに入ってしまう（コードレビュー指摘1。
    `scripts/tests/test_migrate_point_in_polygon.py` で単体テスト済みの
    `on_boundary()` を b09 の実データ経路で確認する）。境界上なので
    `_assert_no_multi_match`（一致が2つ以上）ではなく、専用の境界検証で
    無条件に止まる。
    """
    rows = [occurrence_row_at("r1", 35.05, 139.1, source_row_id=1)]  # W1/W3 共有辺のちょうど上
    v2_db, ryuiki_db, registry_db, geojson = _setup(
        tmp_path,
        occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS), ("W3", _W3_RINGS)],
        place_refs=[
            (_W1_PLACE_ID, "W1", "watershed_meta.watershed_id"),
            (_W3_PLACE_ID, "W3", "watershed_meta.watershed_id"),
        ],
    )
    decl = _declarations(tmp_path, n_watershed_polygons=2, place_id_null_count=0, resolved_count=1)

    with pytest.raises(common.MigrationError, match="境界"):
        b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, geojson, decl)


def test_watershed_external_key_duplicate_halts(tmp_path):
    """registry の `place_source_ref(source_id='watershed_meta.watershed_id')`
    に同じ `external_key`（watershed_id）を持つ行が2つあると、
    `watershed_id -> place_id` の辞書が後勝ちで黙って潰れる——事前に
    一意性を検証して止める（コードレビュー指摘5）。
    """
    rows = [occurrence_row_at("r1", 35.05, 139.05, source_row_id=1)]
    other_place_id = "common:place:watershed.w1-dup"
    v2_db, ryuiki_db, registry_db, geojson = _setup(
        tmp_path,
        occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS)],
        # 同じ external_key "W1" に2つの異なる place_id が対応している。
        place_refs=[
            (_W1_PLACE_ID, "W1", "watershed_meta.watershed_id"),
            (other_place_id, "W1", "watershed_meta.watershed_id"),
        ],
    )
    decl = _declarations(tmp_path, n_watershed_polygons=1, place_id_null_count=0, resolved_count=1)

    with pytest.raises(common.MigrationError, match="一意でない"):
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


def test_empty_population_does_not_crash_on_sum(tmp_path):
    """座標のある記録が1件も無いとき（`occurrence_place` が空のまま作られる）、
    `SUM(CASE ...)` が空集合に対して NULL を返し、宣言との突き合わせで
    `None:,` の書式化が `TypeError` になっていた（コードレビュー指摘11）。
    `COALESCE(..., 0)` で空でも 0 として扱われることを確認する。
    """
    rows = [occurrence_row_at("r1", None, None, source_row_id=1)]  # 座標なし=母集団から除外
    v2_db, ryuiki_db, registry_db, geojson = _setup(
        tmp_path,
        occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS)],
        place_refs=[(_W1_PLACE_ID, "W1", "watershed_meta.watershed_id")],
    )
    decl = _declarations(tmp_path, n_watershed_polygons=1, place_id_null_count=0, resolved_count=0)

    stats = b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, geojson, decl)
    assert stats["n_total"] == 0
    assert stats["n_null"] == 0
    assert stats["n_resolved"] == 0


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
