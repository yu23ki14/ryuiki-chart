"""scripts/b11_project_place_v1.py の統合テスト（Phase B `phase-b/place-attributes`、
P-1a）。

本物の `data/db/registry.sqlite` を要さない: `registry.common.create_registry_db()`
で空の registry.sqlite を作り、place / place_watershed / place_source_ref に
検証したい行だけを直接 INSERT する（scripts/tests/test_r01_invariants.py と同じ流儀）。
"""
import sqlite3

import pytest

import b11_project_place_v1 as b11
from migrate import common as migrate_common
from registry import common as registry_common

_WATERSHED_ROW = {
    "place_id": "common:place:watershed.nlni-83032-0024",
    "watershed_id": "83032-0024",
    "name_ja": "相模川",
    "lat": 35.1,
    "lon": 139.2,
    "area_km2": 1.2,
    "definition_ref": "https://example.invalid/w12",
    "water_system_code": "83032",
    "water_system_category": "一級河川を含む単一水系域",
    "main_rivers": "相模川|中津川",
    "data_year": 1977,
}


def _insert_watershed_place(conn, row) -> None:
    conn.execute(
        "INSERT INTO place (place_id, region_id, place_kind, name_ja, lat, lon, "
        "elevation_m, area_km2, definition_ref, status) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            row["place_id"], None, "watershed", row.get("name_ja"),
            row.get("lat"), row.get("lon"), None, row.get("area_km2"),
            row.get("definition_ref"), "ok",
        ),
    )
    conn.execute(
        "INSERT INTO place_source_ref (place_id, external_key, source_id) VALUES (?,?,?)",
        (row["place_id"], row["watershed_id"], "watershed_meta.watershed_id"),
    )
    conn.execute(
        "INSERT INTO place_watershed "
        "(place_id, water_system_code, water_system_category, main_rivers, data_year) "
        "VALUES (?,?,?,?,?)",
        (
            row["place_id"], row.get("water_system_code"), row.get("water_system_category"),
            row.get("main_rivers"), row.get("data_year"),
        ),
    )


def _make_registry_db(path, watershed_rows=()) -> None:
    conn = registry_common.create_registry_db(path)
    try:
        for row in watershed_rows:
            _insert_watershed_place(conn, row)
        conn.commit()
    finally:
        conn.close()


def test_projects_watershed_meta_with_v1_column_order_and_types(tmp_path):
    """列名・列順・値が v1（`reports/derived_baseline.json` の `watershed_meta`
    エントリ）と一致すること（受け入れ条件1の単体版）。
    """
    registry_db = tmp_path / "registry.sqlite"
    _make_registry_db(registry_db, [_WATERSHED_ROW])
    out_db = tmp_path / "v1_projection_place.sqlite"

    counts = b11.build_projections(registry_db, out_db)
    assert counts == {"watershed_meta": 1}

    conn = sqlite3.connect(out_db)
    conn.row_factory = sqlite3.Row
    try:
        cols = [d[1] for d in conn.execute("PRAGMA table_info(watershed_meta)")]
        assert cols == [
            "watershed_id", "water_system_code", "water_system_name",
            "water_system_category", "main_rivers", "area_km2",
            "centroid_lat", "centroid_lon", "data_year", "source_ref",
        ]
        row = conn.execute("SELECT * FROM watershed_meta").fetchone()
        assert row["watershed_id"] == "83032-0024"
        assert row["water_system_code"] == "83032"
        assert row["water_system_name"] == "相模川"
        assert row["water_system_category"] == "一級河川を含む単一水系域"
        assert row["main_rivers"] == "相模川|中津川"
        assert row["area_km2"] == pytest.approx(1.2)
        assert row["centroid_lat"] == pytest.approx(35.1)
        assert row["centroid_lon"] == pytest.approx(139.2)
        assert row["data_year"] == 1977
        assert row["source_ref"] == "https://example.invalid/w12"
    finally:
        conn.close()


def test_main_rivers_empty_string_is_preserved_not_coerced_to_null(tmp_path):
    """v1（`?? null`）に合わせ、main_rivers の空文字列を NULL に丸めない
    （docs/plans/PHASE_B_PLACE_ATTRIBUTES.md 実測: main_rivers 234/377 のみ非空）。
    """
    row = dict(_WATERSHED_ROW, place_id="common:place:watershed.nlni-x", watershed_id="x", main_rivers="")
    registry_db = tmp_path / "registry.sqlite"
    _make_registry_db(registry_db, [row])
    out_db = tmp_path / "v1_projection_place.sqlite"

    b11.build_projections(registry_db, out_db)

    conn = sqlite3.connect(out_db)
    try:
        value = conn.execute("SELECT main_rivers FROM watershed_meta").fetchone()[0]
    finally:
        conn.close()
    assert value == ""
    assert value is not None


def test_name_ja_null_becomes_water_system_name_null(tmp_path):
    row = dict(
        _WATERSHED_ROW, place_id="common:place:watershed.nlni-y", watershed_id="y", name_ja=None
    )
    registry_db = tmp_path / "registry.sqlite"
    _make_registry_db(registry_db, [row])
    out_db = tmp_path / "v1_projection_place.sqlite"

    b11.build_projections(registry_db, out_db)

    conn = sqlite3.connect(out_db)
    try:
        value = conn.execute("SELECT water_system_name FROM watershed_meta").fetchone()[0]
    finally:
        conn.close()
    assert value is None


def test_ignores_non_watershed_places(tmp_path):
    """place_kind が 'watershed' 以外の place（site 等）は射影対象に混ざらない。"""
    registry_db = tmp_path / "registry.sqlite"
    conn = registry_common.create_registry_db(registry_db)
    try:
        _insert_watershed_place(conn, _WATERSHED_ROW)
        conn.execute(
            "INSERT INTO place (place_id, region_id, place_kind, name_ja, status) "
            "VALUES (?,?,?,?,?)",
            ("jp-14:place:site.jma-s1", "jp-14", "site", "地点1", "ok"),
        )
        conn.commit()
    finally:
        conn.close()
    out_db = tmp_path / "v1_projection_place.sqlite"

    counts = b11.build_projections(registry_db, out_db)
    assert counts == {"watershed_meta": 1}


def test_missing_place_watershed_row_raises(tmp_path):
    """place_kind='watershed' なのに place_watershed に行が無ければ例外で止まる
    （欠落した行が INNER JOIN で黙って落ちる——一番気づきにくい壊れ方——のを防ぐ）。
    """
    registry_db = tmp_path / "registry.sqlite"
    conn = registry_common.create_registry_db(registry_db)
    try:
        conn.execute(
            "INSERT INTO place (place_id, region_id, place_kind, status) VALUES (?,?,?,?)",
            ("common:place:watershed.nlni-x", None, "watershed", "ok"),
        )
        conn.execute(
            "INSERT INTO place_source_ref (place_id, external_key, source_id) VALUES (?,?,?)",
            ("common:place:watershed.nlni-x", "x", "watershed_meta.watershed_id"),
        )
        conn.commit()
    finally:
        conn.close()

    out_db = tmp_path / "v1_projection_place.sqlite"
    with pytest.raises(migrate_common.MigrationError, match="place_watershed に行が無い"):
        b11.build_projections(registry_db, out_db)


def test_missing_place_source_ref_raises(tmp_path):
    """place_kind='watershed' なのに
    place_source_ref(source_id='watershed_meta.watershed_id') が無ければ例外で止まる。
    """
    registry_db = tmp_path / "registry.sqlite"
    conn = registry_common.create_registry_db(registry_db)
    try:
        conn.execute(
            "INSERT INTO place (place_id, region_id, place_kind, status) VALUES (?,?,?,?)",
            ("common:place:watershed.nlni-x", None, "watershed", "ok"),
        )
        conn.execute(
            "INSERT INTO place_watershed (place_id, data_year) VALUES (?,?)",
            ("common:place:watershed.nlni-x", 1977),
        )
        conn.commit()
    finally:
        conn.close()

    out_db = tmp_path / "v1_projection_place.sqlite"
    with pytest.raises(migrate_common.MigrationError, match="place_source_ref"):
        b11.build_projections(registry_db, out_db)


def test_duplicate_watershed_id_reference_raises(tmp_path):
    """watershed_meta.watershed_id が複数の place_id に対応していれば例外で止まる
    （v1 の watershed_id への逆引きが一意でなくなる）。
    """
    row_a = dict(_WATERSHED_ROW, place_id="common:place:watershed.nlni-a")
    row_b = dict(_WATERSHED_ROW, place_id="common:place:watershed.nlni-b")  # 同じ watershed_id
    registry_db = tmp_path / "registry.sqlite"
    _make_registry_db(registry_db, [row_a, row_b])
    out_db = tmp_path / "v1_projection_place.sqlite"

    with pytest.raises(migrate_common.MigrationError, match="複数の place_id"):
        b11.build_projections(registry_db, out_db)


def test_output_is_rebuilt_from_scratch_each_run(tmp_path):
    """`common.fresh_sqlite` により毎回ゼロから作り直す（前回実行の残骸で
    行が重複しない）。"""
    registry_db = tmp_path / "registry.sqlite"
    _make_registry_db(registry_db, [_WATERSHED_ROW])
    out_db = tmp_path / "v1_projection_place.sqlite"

    b11.build_projections(registry_db, out_db)
    b11.build_projections(registry_db, out_db)

    conn = sqlite3.connect(out_db)
    try:
        n = conn.execute("SELECT COUNT(*) FROM watershed_meta").fetchone()[0]
    finally:
        conn.close()
    assert n == 1
