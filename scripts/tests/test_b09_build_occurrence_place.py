"""scripts/b09_build_occurrence_place.py の統合テスト。

本物の `data/db/*.sqlite`・GeoJSON を要さず、`scripts/tests/occurrence_fixtures.py`
の小さなフィクスチャだけで完結する。
"""
import sqlite3

import pytest

import b09_build_occurrence_place as b09
from migrate import common

from .occurrence_fixtures import (
    DEFAULT_PLACE,
    DEFAULT_PLACE_SOURCE_REF,
    make_occurrence_place_declarations_yaml,
    make_occurrence_registry_db,
    make_ryuiki_sites_db,
    make_v2_db_with_occurrence,
    occurrence_row,
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
    places = [(pid, None, "watershed") for pid in dict.fromkeys(pid for pid, _ext, _sid in place_refs)]
    # occurrence_row の既定 place_id（grid01）も registry で引けること（b09 の検査）。
    make_occurrence_registry_db(
        registry_db, taxa=list(taxa), places=list(DEFAULT_PLACE) + places,
        place_refs=list(DEFAULT_PLACE_SOURCE_REF) + list(place_refs),
    )

    ryuiki_db = tmp_path / "ryuiki.sqlite"
    make_ryuiki_sites_db(ryuiki_db, list(sites_rows))

    return v2_db, ryuiki_db, registry_db, geojson_path


def _declarations(tmp_path, **kwargs):
    path = tmp_path / "occurrence_place_declarations.yaml"
    make_occurrence_place_declarations_yaml(path, **kwargs)
    return path


def test_resolved_and_null_rows(tmp_path):
    rows = [
        occurrence_row("r1", None, None, None, None, source_row_id=1, lat=35.05, lon=139.05),  # W1 の中
        occurrence_row("r2", None, None, None, None, source_row_id=2, lat=50.0, lon=200.0),  # どの面にも入らない
    ]
    v2_db, ryuiki_db, registry_db, geojson = _setup(
        tmp_path,
        occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS)],
        place_refs=[(_W1_PLACE_ID, "W1", "watershed_id")],
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
    # 系譜（Issue #45）: occurrence（検証済み）と registry・原本 sites が自動で入る。
    lineage_keys = set(common.read_recorded_inputs(conn, "occurrence_place"))
    # 出力を左右する registry の place_source_ref・原本の sites も系譜に載る
    # （staged_table の前の読み取りも含め、段の先頭以降の読み取りは全部載る）。
    assert {"occurrence", "ext:registry.place_source_ref", "ext:ryuiki.sites"} <= lineage_keys


def test_records_without_coordinates_get_no_row(tmp_path):
    """座標の無い記録（lat/lon NULL）は occurrence_place に行を持たない
    （母集団は「座標のある全記録」）。
    """
    rows = [
        occurrence_row("r1", None, None, None, None, source_row_id=1, lat=35.05, lon=139.05),
        occurrence_row("r2", None, None, None, None, source_row_id=2, lat=None, lon=None),
    ]
    v2_db, ryuiki_db, registry_db, geojson = _setup(
        tmp_path,
        occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS)],
        place_refs=[(_W1_PLACE_ID, "W1", "watershed_id")],
    )
    decl = _declarations(tmp_path, n_watershed_polygons=1, place_id_null_count=0, resolved_count=1)

    stats = b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, geojson, decl)
    assert stats["n_total"] == 1

    conn = sqlite3.connect(f"file:{v2_db}?mode=ro", uri=True)
    ids = {r[0] for r in conn.execute("SELECT record_id FROM occurrence_place")}
    assert ids == {"r1"}


def test_two_overlapping_polygons_halts(tmp_path):
    rows = [occurrence_row("r1", None, None, None, None, source_row_id=1, lat=35.075, lon=139.075)]  # W1 と W2 の両方に入る
    v2_db, ryuiki_db, registry_db, geojson = _setup(
        tmp_path,
        occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS), ("W2", _W2_RINGS)],
        place_refs=[
            (_W1_PLACE_ID, "W1", "watershed_id"),
            (_W2_PLACE_ID, "W2", "watershed_id"),
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
    rows = [occurrence_row("r1", None, None, None, None, source_row_id=1, lat=35.05, lon=139.1)]  # W1/W3 共有辺のちょうど上
    v2_db, ryuiki_db, registry_db, geojson = _setup(
        tmp_path,
        occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS), ("W3", _W3_RINGS)],
        place_refs=[
            (_W1_PLACE_ID, "W1", "watershed_id"),
            (_W3_PLACE_ID, "W3", "watershed_id"),
        ],
    )
    decl = _declarations(tmp_path, n_watershed_polygons=2, place_id_null_count=0, resolved_count=1)

    with pytest.raises(common.MigrationError, match="境界"):
        b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, geojson, decl)


def test_watershed_external_key_duplicate_halts(tmp_path):
    """registry の `place_source_ref(source_id='watershed_id')`
    に同じ `external_key`（watershed_id）を持つ行が2つあると、
    `watershed_id -> place_id` の辞書が後勝ちで黙って潰れる——事前に
    一意性を検証して止める（コードレビュー指摘5）。
    """
    rows = [occurrence_row("r1", None, None, None, None, source_row_id=1, lat=35.05, lon=139.05)]
    other_place_id = "common:place:watershed.w1-dup"
    v2_db, ryuiki_db, registry_db, geojson = _setup(
        tmp_path,
        occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS)],
        # 同じ external_key "W1" に2つの異なる place_id が対応している。
        place_refs=[
            (_W1_PLACE_ID, "W1", "watershed_id"),
            (other_place_id, "W1", "watershed_id"),
        ],
    )
    decl = _declarations(tmp_path, n_watershed_polygons=1, place_id_null_count=0, resolved_count=1)

    with pytest.raises(common.MigrationError, match="一意でない"):
        b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, geojson, decl)


def test_geojson_registry_set_mismatch_halts(tmp_path):
    rows = [occurrence_row("r1", None, None, None, None, source_row_id=1, lat=35.05, lon=139.05)]
    v2_db, ryuiki_db, registry_db, geojson = _setup(
        tmp_path,
        occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS)],
        # registry 側は別の watershed_id（"W_OTHER"）しか知らない。
        place_refs=[(_W1_PLACE_ID, "W_OTHER", "watershed_id")],
    )
    decl = _declarations(tmp_path, n_watershed_polygons=1, place_id_null_count=0, resolved_count=1)

    with pytest.raises(common.MigrationError, match="watershed_id"):
        b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, geojson, decl)


def test_declaration_count_mismatch_halts(tmp_path):
    rows = [occurrence_row("r1", None, None, None, None, source_row_id=1, lat=35.05, lon=139.05)]
    v2_db, ryuiki_db, registry_db, geojson = _setup(
        tmp_path,
        occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS)],
        place_refs=[(_W1_PLACE_ID, "W1", "watershed_id")],
    )
    # resolved_count を実際の値(1)と食い違わせる。
    decl = _declarations(tmp_path, n_watershed_polygons=1, place_id_null_count=0, resolved_count=999)

    with pytest.raises(common.MigrationError, match="宣言"):
        b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, geojson, decl)


def test_site_watershed_edge_mismatch_halts(tmp_path):
    rows = [occurrence_row("r1", None, None, None, None, source_row_id=1, lat=35.05, lon=139.05)]
    v2_db, ryuiki_db, registry_db, geojson = _setup(
        tmp_path,
        occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS)],
        place_refs=[(_W1_PLACE_ID, "W1", "watershed_id")],
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
    rows = [occurrence_row("r1", None, None, None, None, source_row_id=1, lat=None, lon=None)]  # 座標なし=母集団から除外
    v2_db, ryuiki_db, registry_db, geojson = _setup(
        tmp_path,
        occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS)],
        place_refs=[(_W1_PLACE_ID, "W1", "watershed_id")],
    )
    decl = _declarations(tmp_path, n_watershed_polygons=1, place_id_null_count=0, resolved_count=0)

    stats = b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, geojson, decl)
    assert stats["n_total"] == 0
    assert stats["n_null"] == 0
    assert stats["n_resolved"] == 0


def test_site_watershed_edge_matches_passes(tmp_path):
    rows = [occurrence_row("r1", None, None, None, None, source_row_id=1, lat=35.05, lon=139.05)]
    v2_db, ryuiki_db, registry_db, geojson = _setup(
        tmp_path,
        occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS)],
        place_refs=[(_W1_PLACE_ID, "W1", "watershed_id")],
        sites_rows=[("site_a", 35.05, 139.05, "W1"), ("site_b", 50.0, 200.0, None)],
    )
    decl = _declarations(tmp_path, n_watershed_polygons=1, place_id_null_count=0, resolved_count=1)

    stats = b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, geojson, decl)
    assert stats["n_checked_sites"] == 2


# ---------------------------------------------------------------------------
# place_id と place_source_ref の関係（Issue #48 PR-5。b08 の逆引き検査から移設）
# ---------------------------------------------------------------------------

def _run_b09(tmp_path, *, occurrence_rows, place_refs, features=None, extra_registry_refs=(), extra_places=()):
    v2_db, ryuiki_db, registry_db, geojson = _setup(
        tmp_path, occurrence_rows=occurrence_rows,
        geojson_features=features or [("W1", _W1_RINGS)], place_refs=place_refs,
    )
    if extra_registry_refs:
        conn = sqlite3.connect(str(registry_db))
        conn.executemany("INSERT INTO place_source_ref VALUES (?,?,?)", list(extra_registry_refs))
        conn.executemany("INSERT INTO place VALUES (?,?,?)", list(extra_places))
        conn.commit()
        conn.close()
    decl = _declarations(
        tmp_path, n_watershed_polygons=len(features or [1]), place_id_null_count=0, resolved_count=1,
    )
    return b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, geojson, decl)


_ONE_RESOLVED = [occurrence_row("r1", None, None, None, None, source_row_id=1, lat=35.05, lon=139.05)]


def test_watershed_place_id_with_two_external_keys_halts(tmp_path):
    """同じ place_id に2つの watershed の external_key が対応していると止まる
    （external_key は一意でも、place_id → external_key が一意でない）。
    """
    with pytest.raises(common.MigrationError, match="place_id について単射でない"):
        _run_b09(
            tmp_path, occurrence_rows=_ONE_RESOLVED,
            features=[("W1", _W1_RINGS), ("W3", _W3_RINGS)],
            # 2つの流域（external_key は別々）が同じ place_id を指している。
            place_refs=[
                (_W1_PLACE_ID, "W1", "watershed_id"),
                (_W1_PLACE_ID, "W3", "watershed_id"),
            ],
        )


def test_mesh_place_id_with_two_external_keys_halts(tmp_path):
    with pytest.raises(common.MigrationError, match="place_id について単射でない"):
        _run_b09(
            tmp_path, occurrence_rows=_ONE_RESOLVED,
            place_refs=[(_W1_PLACE_ID, "W1", "watershed_id")],
            extra_registry_refs=[(DEFAULT_PLACE_SOURCE_REF[0][0], "grid01:9999,9999", "grid01_latlon")],
        )


def test_occurrence_place_id_missing_from_place_source_ref_halts(tmp_path):
    """b06 が書いた occurrence.place_id（grid01）が registry の place_source_ref で
    引けなければ止まる（registry と occurrence の版のずれ）。
    """
    rows = [occurrence_row(
        "r1", None, None, None, None, source_row_id=1, lat=35.05, lon=139.05,
        place_id="common:place:grid01.0000_00000",
    )]
    with pytest.raises(common.MigrationError, match="引けない place_id"):
        _run_b09(tmp_path, occurrence_rows=rows, place_refs=[(_W1_PLACE_ID, "W1", "watershed_id")])


# ---------------------------------------------------------------------------
# 座標なしの日付あり記録（Issue #40 Phase D・J1）
# ---------------------------------------------------------------------------

def _nocoord_row(record_id, *, dated=True, source_id="kuma_like_source"):
    day = "2020-02-10" if dated else None
    return occurrence_row(
        record_id, None, day, day, day, source_row_id=9, lat=None, lon=None,
        place_id=None, place_kind=None, source_id=source_id,
    )


def _sums(**cube_overrides):
    from ingest import manifest as manifest_lib

    cube = {k: 0 for k in manifest_lib.EXPECTED_CUBE_KEYS}
    cube.update(cube_overrides)
    return manifest_lib.ExpectedSums(cube=cube, sources=("kuma_like_source",))


def _nocoord_setup(tmp_path, rows):
    return _setup(
        tmp_path,
        occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS)],
        place_refs=[(_W1_PLACE_ID, "W1", "watershed_id")],
    )


def test_dated_record_without_coordinates_gets_place_id_null_row(tmp_path):
    rows = [
        occurrence_row("r1", None, None, None, None, source_row_id=1, lat=35.05, lon=139.05),
        _nocoord_row("r2"),
    ]
    v2_db, ryuiki_db, registry_db, geojson = _nocoord_setup(tmp_path, rows)
    decl = _declarations(tmp_path, n_watershed_polygons=1, place_id_null_count=0, resolved_count=1)

    stats = b09.build_and_write_occurrence_place(
        v2_db, ryuiki_db, registry_db, geojson, decl, expected_sums=_sums(dated_no_coordinate_rows=1),
    )
    assert stats["n_total"] == 2 and stats["n_dated_no_coord"] == 1
    assert stats["n_null"] == 0 and stats["n_resolved"] == 1  # 座標あり記録の内訳は従来どおり
    conn = sqlite3.connect(f"file:{v2_db}?mode=ro", uri=True)
    out = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT record_id, place_kind, place_id FROM occurrence_place")}
    assert out["r2"] == ("watershed", None)
    assert out["r1"] == ("watershed", _W1_PLACE_ID)


def test_undated_record_without_coordinates_gets_no_row(tmp_path):
    rows = [_nocoord_row("r2", dated=False)]
    v2_db, ryuiki_db, registry_db, geojson = _nocoord_setup(tmp_path, rows)
    decl = _declarations(tmp_path, n_watershed_polygons=1, place_id_null_count=0, resolved_count=0)
    stats = b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, geojson, decl)
    assert stats["n_total"] == 0


def test_dated_record_without_coordinates_must_be_declared_by_manifest(tmp_path):
    """座標なしの日付あり記録が宣言（マニフェストの expected.cube.dated_no_coordinate_rows）に無ければ止まる。"""
    rows = [_nocoord_row("r2")]
    v2_db, ryuiki_db, registry_db, geojson = _nocoord_setup(tmp_path, rows)
    decl = _declarations(tmp_path, n_watershed_polygons=1, place_id_null_count=0, resolved_count=0)
    with pytest.raises(common.MigrationError, match="dated_no_coordinate_rows"):
        b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, geojson, decl)


def test_b09_output_passes_b07_population_check_for_coordinate_less_record(tmp_path):
    """b09 の出力（座標なし日付あり記録の place_id NULL 行）を、b07 の母集団検査がそのまま受け入れる（鎖が通る）。"""
    import b07_build_occurrence_cube as b07
    from .occurrence_fixtures import make_occurrence_cube_declarations_yaml

    rows = [
        occurrence_row("r1", None, "2020-01-05", "2020-01-05", "2020-01-05", source_row_id=1, lat=35.05, lon=139.05),
        _nocoord_row("r2"),
    ]
    v2_db, ryuiki_db, registry_db, geojson = _nocoord_setup(tmp_path, rows)
    decl = _declarations(tmp_path, n_watershed_polygons=1, place_id_null_count=0, resolved_count=1)
    sums = _sums(dated_rows=1, dated_no_coordinate_rows=1, watershed_dated_unresolved_rows=1)
    b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, geojson, decl, expected_sums=sums)

    cube_decl = tmp_path / "cube.yaml"
    make_occurrence_cube_declarations_yaml(cube_decl, {
        "leaf_cell_source_rows": 0, "month_cell_source_rows": 1,
        "watershed_dated_resolved_rows": 1, "watershed_dated_unresolved_rows": 0,
    })
    conn = sqlite3.connect(f"file:{v2_db}", uri=True)
    try:
        stats = b07.build_cube(conn, cube_decl, place_declarations_yaml=None, expected_sums=sums)
        assert stats["n_dated_by_place_kind"] == {"grid01": 1, "watershed": 2}
    finally:
        conn.close()


# ---- 地域ごとの W12（複数の GeoJSON。奄美 Step 1 PR-B）-------------------------------------------

_A1_RINGS = [[[129.5, 28.3], [129.6, 28.3], [129.6, 28.4], [129.5, 28.4], [129.5, 28.3]]]
_A1_PLACE_ID = "common:place:watershed.a1"


def _setup_two_regions(tmp_path):
    rows = [
        occurrence_row("r1", None, None, None, None, source_row_id=1, lat=35.05, lon=139.05),   # 神奈川側 W1
        occurrence_row("r2", None, None, None, None, source_row_id=2, lat=28.35, lon=129.55),   # 奄美側 A1
        occurrence_row("r3", None, None, None, None, source_row_id=3, lat=50.0, lon=200.0),     # どちらにも入らない
    ]
    v2_db, ryuiki_db, registry_db, geojson_k = _setup(
        tmp_path, occurrence_rows=rows,
        geojson_features=[("W1", _W1_RINGS)],
        place_refs=[(_W1_PLACE_ID, "W1", "watershed_id"), (_A1_PLACE_ID, "A1", "watershed_id")],
    )
    geojson_a = tmp_path / "watersheds_amami.geojson"
    write_watershed_geojson(geojson_a, [("A1", _A1_RINGS)])
    return v2_db, ryuiki_db, registry_db, geojson_k, geojson_a


def test_several_geojsons_are_unioned_and_matched_against_registry(tmp_path):
    v2_db, ryuiki_db, registry_db, geojson_k, geojson_a = _setup_two_regions(tmp_path)
    decl = _declarations(tmp_path, n_watershed_polygons=2, place_id_null_count=1, resolved_count=2)

    stats = b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, [geojson_k, geojson_a], decl)
    assert (stats["n_polygons"], stats["n_resolved"], stats["n_null"]) == (2, 2, 1)
    conn = sqlite3.connect(f"file:{v2_db}?mode=ro", uri=True)
    assert dict(conn.execute("SELECT record_id, place_id FROM occurrence_place")) == {
        "r1": _W1_PLACE_ID, "r2": _A1_PLACE_ID, "r3": None,
    }


def test_registry_comparison_is_against_the_union_of_all_geojsons(tmp_path):
    """registry の流域（W1+A1）に対し、片方の地域の GeoJSON しか渡さなければ集合が食い違って止まる。"""
    v2_db, ryuiki_db, registry_db, geojson_k, _geojson_a = _setup_two_regions(tmp_path)
    decl = _declarations(tmp_path, n_watershed_polygons=1, place_id_null_count=1, resolved_count=1)
    with pytest.raises(common.MigrationError, match="食い違う"):
        b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, [geojson_k], decl)


def test_same_watershed_id_in_two_geojsons_halts(tmp_path):
    v2_db, ryuiki_db, registry_db, geojson_k, _geojson_a = _setup_two_regions(tmp_path)
    decl = _declarations(tmp_path, n_watershed_polygons=2, place_id_null_count=1, resolved_count=2)
    with pytest.raises(ValueError, match="W1"):
        b09.build_and_write_occurrence_place(v2_db, ryuiki_db, registry_db, [geojson_k, geojson_k], decl)


def test_built_from_of_single_path_is_unchanged_by_list_support(tmp_path):
    """1ファイルなら指紋は従来と同じ（パスでもリストでも同じ値）。"""
    g = tmp_path / "g.geojson"
    write_watershed_geojson(g, [("W1", _W1_RINGS)])
    assert b09._built_from(g) == b09._built_from([g])
    import hashlib
    assert b09._built_from(g) == f"occurrence+nlni_w12_watersheds.geojson@sha256:{hashlib.sha256(g.read_bytes()).hexdigest()[:16]}"


def test_built_from_of_many_paths_has_no_concatenation_ambiguity(tmp_path):
    """複数ファイルは名前と長さを区切りに含める。同じ連結バイト列でも分割が違えば指紋が変わる。"""
    a, b, c = (tmp_path / n for n in ("a.geojson", "b.geojson", "c.geojson"))
    a.write_bytes(b"AB")
    b.write_bytes(b"C")
    c.write_bytes(b"ABC")
    assert b09._built_from([a, b]) != b09._built_from(c)
    a.write_bytes(b"A")
    b.write_bytes(b"BC")   # 連結は同じ "ABC"
    assert b09._built_from([a, b]) != b09._built_from([tmp_path / "a.geojson", tmp_path / "b.geojson"][::-1])
    first = b09._built_from([a, b])
    a.write_bytes(b"AB")
    b.write_bytes(b"C")
    assert b09._built_from([a, b]) != first
