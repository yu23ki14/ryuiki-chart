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


def test_insert_sql_declares_explicit_column_list():
    """`_INSERT_WATERSHED_META_SQL` が `INSERT INTO watershed_meta (列名...)` の形で
    列名を明示していること（code-review 指摘8: CREATE の列順と SELECT の列順という
    2つの離れたリテラルを手で揃える暗黙の位置合わせにしない）。
    """
    expected = f"INSERT INTO watershed_meta ({', '.join(b11._WATERSHED_META_COLUMNS)})"
    assert expected in b11._INSERT_WATERSHED_META_SQL


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


def test_missing_place_watershed_table_raises_clear_error(tmp_path):
    """`place_watershed` テーブル自体が無い（P-1a より前にビルドした古い
    registry.sqlite を渡した）場合、素の `sqlite3.OperationalError`（no such table）
    ではなく「r01 を実行し直せ」と分かる `MigrationError` で止まる
    （`scripts/b05_project_v1.py` の `_assert_place_relation_table_exists` と同じ形）。
    """
    registry_db = tmp_path / "registry.sqlite"
    conn = registry_common.create_registry_db(registry_db)
    try:
        conn.execute("DROP TABLE place_watershed")
        conn.commit()
    finally:
        conn.close()

    out_db = tmp_path / "v1_projection_place.sqlite"
    with pytest.raises(migrate_common.MigrationError, match="place_watershed テーブルが無い"):
        b11.build_projections(registry_db, out_db)


def test_duplicate_source_ref_per_place_raises_and_does_not_inflate_rows(tmp_path):
    """同じ place に `place_source_ref(source_id='watershed_meta.watershed_id')` の
    行が2つあると、INNER JOIN がその place を2回ヒットさせて行が水増しされる
    （377→378 のような一番気づきにくい壊れ方）。これを `place_id` で GROUP BY して
    検出する（code-review 指摘: 以前は `external_key` で GROUP BY しており、この
    水増しを検出できていなかった——同じ external_key が別々の place に対応する
    ケース（`external_key` 側の重複）は水増しを起こさないので誤検出だった）。
    """
    registry_db = tmp_path / "registry.sqlite"
    conn = registry_common.create_registry_db(registry_db)
    try:
        _insert_watershed_place(conn, _WATERSHED_ROW)
        # 同じ place_id にもう1件、別の external_key で place_source_ref を足す
        # （水増しの原因になる本物の重複）。
        conn.execute(
            "INSERT INTO place_source_ref (place_id, external_key, source_id) VALUES (?,?,?)",
            (_WATERSHED_ROW["place_id"], "83032-0024-dup", "watershed_meta.watershed_id"),
        )
        conn.commit()
    finally:
        conn.close()
    out_db = tmp_path / "v1_projection_place.sqlite"

    with pytest.raises(migrate_common.MigrationError, match="place_id について単射でない"):
        b11.build_projections(registry_db, out_db)


def test_two_places_sharing_the_same_external_key_is_not_flagged_as_inflation(tmp_path):
    """2つの異なる place が同じ v1 の watershed_id（external_key）を指していても、
    それぞれの place 自身は `place_source_ref` を1件しか持たないので、行の水増し
    （b11 が独立に防ぐ対象）は起きない——このケースを誤って止めない
    （旧実装は `external_key` で GROUP BY しており、このケースを誤検出していた）。
    """
    row_a = dict(_WATERSHED_ROW, place_id="common:place:watershed.nlni-a")
    row_b = dict(_WATERSHED_ROW, place_id="common:place:watershed.nlni-b")  # 同じ watershed_id
    registry_db = tmp_path / "registry.sqlite"
    _make_registry_db(registry_db, [row_a, row_b])
    out_db = tmp_path / "v1_projection_place.sqlite"

    counts = b11.build_projections(registry_db, out_db)
    assert counts == {"watershed_meta": 2}


def test_failed_validation_does_not_touch_previous_output(tmp_path):
    """検証（`_validate_registry`）が失敗したときは `common.fresh_sqlite(out_path)`
    を一切呼ばない——前回の正しい出力ファイルがバイト単位で残る（code-review
    指摘4: 以前は `fresh_sqlite(out)` を検証より先に呼んでおり、検証失敗時に
    前回の出力が消えて空/半端なファイルが残っていた）。
    """
    registry_db = tmp_path / "registry.sqlite"
    _make_registry_db(registry_db, [_WATERSHED_ROW])
    out_db = tmp_path / "v1_projection_place.sqlite"

    b11.build_projections(registry_db, out_db)  # 1回目: 正しい出力を作る
    before = out_db.read_bytes()

    # 2回目の直前に registry.sqlite を壊す（place_watershed テーブルを消す）。
    conn = sqlite3.connect(registry_db)
    try:
        conn.execute("DROP TABLE place_watershed")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(migrate_common.MigrationError):
        b11.build_projections(registry_db, out_db)

    after = out_db.read_bytes()
    assert after == before  # 前回の出力が1バイトも変わっていない


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
