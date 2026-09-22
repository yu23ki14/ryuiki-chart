"""scripts/registry/build_place.py の region_id 導出 / place_relation（地点->ゾーン）の
テスト（Phase B `phase-b/region-scope`, ADR-0022）。

本物の `data/db/*.sqlite`（828MB/42MB/449MB）を要さず、
scripts/tests/registry_fixtures.py の小さな自作 sqlite だけで完結する。
`registry/place/zone.yaml` だけは実物を読む（`build_place._load_zone_yaml()` が
常にリポジトリのこのファイルを読む設計のため。手書きの正本であり「原本」の
読み取り専用 DB ではないので、CLAUDE.md の原本使用禁止の対象外）。
"""
import sqlite3

import pytest

from registry import common
from registry.build_place import build as build_place

from .registry_fixtures import make_derived_places_db, make_ryuiki_places_db, open_places_src


def test_region_id_for_scoped_id_derives_from_scope_not_hardcoded():
    """common.region_id_for_scoped_id() 自体の単体テスト（ADR-0022 決定1）。"""
    assert common.region_id_for_scoped_id("common:place:watershed.nlni-83032-0024") is None
    assert common.region_id_for_scoped_id("common:place:grid01.3500_13900") is None
    assert common.region_id_for_scoped_id("jp-14:place:site.jma-jma_0387") == "jp-14"
    assert common.region_id_for_scoped_id("jp-14:place:zone.r2r-1") == "jp-14"


def _build(tmp_path, sites_rows, watershed_rows=(), organism_records_rows=()):
    ryuiki_path = tmp_path / "ryuiki.sqlite"
    derived_path = tmp_path / "derived.sqlite"
    make_ryuiki_places_db(ryuiki_path, sites_rows, organism_records_rows)
    make_derived_places_db(derived_path, watershed_rows)

    registry_conn = common.create_registry_db(tmp_path / "registry.sqlite")
    registry_conn.row_factory = sqlite3.Row
    src = open_places_src(ryuiki_path, derived_path)
    try:
        counts = build_place(registry_conn, src)
    finally:
        for c in src.values():
            c.close()
    return registry_conn, counts


def test_region_id_common_scope_is_null_and_region_scope_matches_id(tmp_path):
    """common:スコープ(watershed/grid01)は region_id=NULL、jp-14:スコープ(site/zone)は
    region_id='jp-14'（ADR-0022 決定1。「Phase A の対象地域は神奈川だから」で全行 jp-14 に
    していた旧実装の回帰テスト）。
    """
    sites_rows = [("jma_stations_kanagawa__s1", "地点1", 35.0, 139.0, 10.0, "src", "ref", 1)]
    watershed_rows = [("83032-0024", "相模川水系", 1.2, 35.1, 139.2, "ref")]
    organism_records_rows = [(35.001, 139.001)]  # -> mlat=3500, mlon=13900
    conn, counts = _build(tmp_path, sites_rows, watershed_rows, organism_records_rows)

    region_by_kind = {r["place_kind"]: r["region_id"] for r in conn.execute("SELECT place_kind, region_id FROM place")}
    assert region_by_kind["site"] == "jp-14"
    assert region_by_kind["watershed"] is None
    assert region_by_kind["grid01"] is None
    assert region_by_kind["zone"] == "jp-14"
    assert counts["place_relation"] == 1


def test_place_relation_edge_count_matches_sites_with_zone_not_null(tmp_path):
    """place_relation の辺数は sites.zone IS NOT NULL の地点数と一致する（受け入れ条件3）。"""
    sites_rows = [
        ("jma_stations_kanagawa__s1", "地点1", 35.0, 139.0, 10.0, "src", "ref", 1),
        ("jma_stations_kanagawa__s2", "地点2", 35.1, 139.1, 20.0, "src", "ref", 3),
        ("jma_stations_kanagawa__s3", "地点3", 35.2, 139.2, 30.0, "src", "ref", None),  # zone無し
    ]
    conn, counts = _build(tmp_path, sites_rows)

    assert counts["place_relation"] == 2
    rows = conn.execute(
        "SELECT parent_id, child_id, relation, fraction FROM place_relation ORDER BY child_id"
    ).fetchall()
    assert [r["relation"] for r in rows] == ["within", "within"]
    # fraction は NOT NULL・常に 1.0（地点は1つのゾーンに完全に含まれる。ADR-0022 決定2）。
    assert [r["fraction"] for r in rows] == [1.0, 1.0]
    assert rows[0]["parent_id"] == "jp-14:place:zone.r2r-1"
    assert rows[0]["child_id"] == "jp-14:place:site.jma-s1"
    assert rows[1]["parent_id"] == "jp-14:place:zone.r2r-3"
    assert rows[1]["child_id"] == "jp-14:place:site.jma-s2"


def test_unresolvable_zone_value_raises(tmp_path):
    """registry/place/zone.yaml に無いゾーン番号は黙って捨てず例外で止める（ADR-0022 決定2）。"""
    sites_rows = [
        ("jma_stations_kanagawa__s1", "地点1", 35.0, 139.0, 10.0, "src", "ref", 99),  # zone.yamlに無い
    ]
    with pytest.raises(ValueError, match="解決できるゾーンが"):
        _build(tmp_path, sites_rows)


# ---------------------------------------------------------------------------
# grid01（Phase B `phase-b/occurrence-registry`。入力を derived.mesh_all から
# ryuiki.organism_records の座標に変えた。scripts/registry/build_place.py の
# grid01 節参照）
# ---------------------------------------------------------------------------

def test_grid01_dedupes_by_cell_and_includes_dateless_coords(tmp_path):
    """grid01 は organism_records の座標を (mlat, mlon) で重複排除して作る。日付列は
    そもそも参照しない（build_place.py は lat/lon だけを SELECT する）ので、
    実データで「日付の無い記録」だった行も引き続き1セルとして数えられることを
    表す（受け入れ条件2-3。実データでは4,083→4,087セルの差のうち1セルがこれ）。
    """
    sites_rows = []
    organism_records_rows = [
        (35.001, 139.001),  # mlat=3500, mlon=13900
        (35.009, 139.009),  # 同じセル(3500,13900)。重複排除される
        (35.501, 139.501),  # mlat=3550, mlon=13950（別セル）
    ]
    conn, counts = _build(tmp_path, sites_rows, organism_records_rows=organism_records_rows)

    grid01_rows = conn.execute(
        "SELECT place_id, lat, lon FROM place WHERE place_kind='grid01' ORDER BY place_id"
    ).fetchall()
    assert [r["place_id"] for r in grid01_rows] == [
        "common:place:grid01.3500_13900",
        "common:place:grid01.3550_13950",
    ]
    # セル中心 = mlat/100+0.005（build_place.py のコメント参照。実世界の座標を推測しない）。
    assert grid01_rows[0]["lat"] == pytest.approx(35.005)
    assert grid01_rows[0]["lon"] == pytest.approx(139.005)

    ref_rows = conn.execute(
        "SELECT external_key, source_id FROM place_source_ref WHERE place_id='common:place:grid01.3500_13900'"
    ).fetchall()
    assert len(ref_rows) == 1
    assert ref_rows[0]["external_key"] == "grid01:3500,13900"
    # source_id は derived.mesh_all ではなく organism_records の座標由来になったことを表す。
    assert ref_rows[0]["source_id"] == "organism_records.lat_lon"


def test_grid01_region_id_is_null_and_id_form_unchanged(tmp_path):
    """grid01 は common スコープ（region_id=NULL）のまま、ID の形（namespace 無し）も
    変わらないことの回帰テスト（入力元を変えても ID 規約自体は変えない）。
    """
    conn, _counts = _build(tmp_path, [], organism_records_rows=[(35.001, 139.001)])
    row = conn.execute(
        "SELECT region_id, place_kind FROM place WHERE place_id='common:place:grid01.3500_13900'"
    ).fetchone()
    assert row["place_kind"] == "grid01"
    assert row["region_id"] is None
