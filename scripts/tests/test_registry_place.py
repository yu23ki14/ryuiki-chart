"""scripts/registry/build_place.py の region_id 導出 / place_relation（地点->ゾーン・
地点->流域）/ watershed（place_watershed 属性サテライト）のテスト
（Phase B `phase-b/region-scope` ADR-0022、`phase-b/place-attributes` P-1a）。

本物の `data/db/*.sqlite`（828MB/42MB/449MB）を要さず、
scripts/tests/registry_fixtures.py の小さな自作 sqlite・JSONL だけで完結する。
`registry/place/zone.yaml` だけは実物を読む（`build_place._load_zone_yaml()` が
常にリポジトリのこのファイルを読む設計のため。手書きの正本であり「原本」の
読み取り専用 DB ではないので、CLAUDE.md の原本使用禁止の対象外）。
"""
import sqlite3

import pytest

from registry import build_place as build_place_module
from registry import common
from registry.build_place import build as build_place

from .registry_fixtures import make_ryuiki_places_db, open_places_src, write_watershed_jsonl


def test_region_id_for_scoped_id_derives_from_scope_not_hardcoded():
    """common.region_id_for_scoped_id() 自体の単体テスト（ADR-0022 決定1）。"""
    assert common.region_id_for_scoped_id("common:place:watershed.nlni-83032-0024") is None
    assert common.region_id_for_scoped_id("common:place:grid01.3500_13900") is None
    assert common.region_id_for_scoped_id("jp-14:place:site.jma-jma_0387") == "jp-14"
    assert common.region_id_for_scoped_id("jp-14:place:zone.r2r-1") == "jp-14"


def _build(tmp_path, monkeypatch, sites_rows, watershed_rows=(), organism_records_rows=()):
    """`watershed_rows`: dict のリスト（write_watershed_jsonl() 参照）。空なら
    watershed 節は0件のまま（place_kind='watershed' の行は作られない）。
    """
    ryuiki_path = tmp_path / "ryuiki.sqlite"
    make_ryuiki_places_db(ryuiki_path, sites_rows, organism_records_rows)

    watershed_jsonl_path = tmp_path / "nlni_w12_watersheds.jsonl"
    write_watershed_jsonl(watershed_jsonl_path, watershed_rows)
    monkeypatch.setattr(build_place_module, "WATERSHED_JSONL", watershed_jsonl_path)

    registry_conn = common.create_registry_db(tmp_path / "registry.sqlite")
    registry_conn.row_factory = sqlite3.Row
    src = open_places_src(ryuiki_path)
    try:
        counts = build_place(registry_conn, src)
    finally:
        for c in src.values():
            c.close()
    return registry_conn, counts


# 実データの watershed 行1件ぶん（`_load_watershed_jsonl()` が読むキーを全部持つ）。
# build_place.py が place / place_watershed に振り分ける列の対応関係を検証する
# テストの基礎データとして使う（他のテストは目的に必要な列だけ上書きする）。
_WATERSHED_ROW_FULL = {
    "watershed_id": "83032-0024",
    "water_system_code_old": "83032",
    "water_system_name_ja_estimated": "相模川",
    "water_system_category_ja": "一級河川を含む単一水系域",
    "main_river_names_ja": "相模川|中津川",
    "area_km2": 1.2,
    "centroid_lat": 35.1,
    "centroid_lon": 139.2,
    "data_year": 1977,
    "source_ref": "https://example.invalid/w12",
}


def test_region_id_common_scope_is_null_and_region_scope_matches_id(tmp_path, monkeypatch):
    """common:スコープ(watershed/grid01)は region_id=NULL、jp-14:スコープ(site/zone)は
    region_id='jp-14'（ADR-0022 決定1。「Phase A の対象地域は神奈川だから」で全行 jp-14 に
    していた旧実装の回帰テスト）。
    """
    sites_rows = [("jma_stations_kanagawa__s1", "地点1", 35.0, 139.0, 10.0, "src", "ref", 1, None)]
    organism_records_rows = [(35.001, 139.001)]  # -> mlat=3500, mlon=13900
    conn, counts = _build(
        tmp_path, monkeypatch, sites_rows, [_WATERSHED_ROW_FULL], organism_records_rows
    )

    region_by_kind = {r["place_kind"]: r["region_id"] for r in conn.execute("SELECT place_kind, region_id FROM place")}
    assert region_by_kind["site"] == "jp-14"
    assert region_by_kind["watershed"] is None
    assert region_by_kind["grid01"] is None
    assert region_by_kind["zone"] == "jp-14"
    assert counts["place_relation"] == 1


def test_place_relation_edge_count_matches_sites_with_zone_not_null(tmp_path, monkeypatch):
    """place_relation の辺数は sites.zone IS NOT NULL の地点数と一致する（受け入れ条件3）。"""
    sites_rows = [
        ("jma_stations_kanagawa__s1", "地点1", 35.0, 139.0, 10.0, "src", "ref", 1, None),
        ("jma_stations_kanagawa__s2", "地点2", 35.1, 139.1, 20.0, "src", "ref", 3, None),
        ("jma_stations_kanagawa__s3", "地点3", 35.2, 139.2, 30.0, "src", "ref", None, None),  # zone無し
    ]
    conn, counts = _build(tmp_path, monkeypatch, sites_rows)

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


def test_unresolvable_zone_value_raises(tmp_path, monkeypatch):
    """registry/place/zone.yaml に無いゾーン番号は黙って捨てず例外で止める（ADR-0022 決定2）。"""
    sites_rows = [
        ("jma_stations_kanagawa__s1", "地点1", 35.0, 139.0, 10.0, "src", "ref", 99, None),  # zone.yamlに無い
    ]
    with pytest.raises(ValueError, match="解決できるゾーンが"):
        _build(tmp_path, monkeypatch, sites_rows)


# ---------------------------------------------------------------------------
# grid01（Phase B `phase-b/occurrence-registry`。入力を derived.mesh_all から
# ryuiki.organism_records の座標に変えた。scripts/registry/build_place.py の
# grid01 節参照）
# ---------------------------------------------------------------------------

def test_grid01_dedupes_by_cell_and_includes_dateless_coords(tmp_path, monkeypatch):
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
    conn, counts = _build(
        tmp_path, monkeypatch, sites_rows, organism_records_rows=organism_records_rows
    )

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


def test_grid01_region_id_is_null_and_id_form_unchanged(tmp_path, monkeypatch):
    """grid01 は common スコープ（region_id=NULL）のまま、ID の形（namespace 無し）も
    変わらないことの回帰テスト（入力元を変えても ID 規約自体は変えない）。
    """
    conn, _counts = _build(
        tmp_path, monkeypatch, [], organism_records_rows=[(35.001, 139.001)]
    )
    row = conn.execute(
        "SELECT region_id, place_kind FROM place WHERE place_id='common:place:grid01.3500_13900'"
    ).fetchone()
    assert row["place_kind"] == "grid01"
    assert row["region_id"] is None


# ---------------------------------------------------------------------------
# watershed（Phase B `phase-b/place-attributes`、P-1a。入力を derived.watershed_meta
# から data/processed/nlni_w12_watersheds.jsonl（L1）直読みに変えた。
# scripts/registry/build_place.py の watershed 節参照）
# ---------------------------------------------------------------------------

def test_watershed_place_fields_come_from_jsonl(tmp_path, monkeypatch):
    """place / place_source_ref の watershed 行が JSONL の値からそのまま組み立つ
    ことを確認する（受け入れ条件2の単体版。実データでの突き合わせは
    docs/plans/PHASE_B_PLACE_ATTRIBUTES.md 参照）。
    """
    conn, counts = _build(tmp_path, monkeypatch, [], [_WATERSHED_ROW_FULL])

    # counts["place"] は zone.yaml の5件も含む（zone は常に登録される）ので、
    # watershed 節が作った行数は place_kind で絞って確認する。
    n_watershed = conn.execute(
        "SELECT COUNT(*) FROM place WHERE place_kind='watershed'"
    ).fetchone()[0]
    assert n_watershed == 1
    row = conn.execute(
        "SELECT place_id, region_id, place_kind, name_ja, lat, lon, elevation_m, "
        "area_km2, definition_ref, status FROM place WHERE place_kind='watershed'"
    ).fetchone()
    assert row["place_id"] == "common:place:watershed.nlni-83032-0024"
    assert row["region_id"] is None  # common スコープ（ADR-0022 決定1）
    assert row["name_ja"] == "相模川"
    assert row["lat"] == pytest.approx(35.1)
    assert row["lon"] == pytest.approx(139.2)
    assert row["elevation_m"] is None
    assert row["area_km2"] == pytest.approx(1.2)
    assert row["definition_ref"] == "https://example.invalid/w12"
    assert row["status"] == "ok"

    ref = conn.execute(
        "SELECT external_key, source_id FROM place_source_ref WHERE place_id=?",
        (row["place_id"],),
    ).fetchone()
    # source_id の文字列は改名しない（消費者を増やさないための既存の約束。brief #1）。
    assert ref["external_key"] == "83032-0024"
    assert ref["source_id"] == "watershed_meta.watershed_id"


def test_watershed_place_water_system_name_null_becomes_place_name_null(tmp_path, monkeypatch):
    """水系名が無い流域（JSONL の water_system_name_ja_estimated が JSON null）は
    place.name_ja も NULL になる（v1 の `|| null` と同じ扱い）。
    """
    row = dict(_WATERSHED_ROW_FULL, watershed_id="83032-0099", water_system_name_ja_estimated=None)
    conn, _counts = _build(tmp_path, monkeypatch, [], [row])

    place_row = conn.execute(
        "SELECT name_ja FROM place WHERE place_kind='watershed'"
    ).fetchone()
    assert place_row["name_ja"] is None


def test_place_watershed_holds_kind_specific_attributes(tmp_path, monkeypatch):
    """`place_watershed`（属性サテライト）が water_system_code/category/
    main_rivers/data_year を持ち、place 本体の列には現れないことを確認する
    （ADR-0006「place の属性」追記、ADR-0011 の `place_attribute`）。
    """
    conn, counts = _build(tmp_path, monkeypatch, [], [_WATERSHED_ROW_FULL])

    assert counts["place_watershed"] == 1
    place_id = conn.execute(
        "SELECT place_id FROM place WHERE place_kind='watershed'"
    ).fetchone()["place_id"]
    attr = conn.execute(
        "SELECT water_system_code, water_system_category, main_rivers, data_year "
        "FROM place_watershed WHERE place_id=?",
        (place_id,),
    ).fetchone()
    assert attr["water_system_code"] == "83032"
    assert attr["water_system_category"] == "一級河川を含む単一水系域"
    assert attr["main_rivers"] == "相模川|中津川"
    assert attr["data_year"] == 1977

    place_cols = {d[0] for d in conn.execute("SELECT * FROM place LIMIT 0").description}
    assert "water_system_code" not in place_cols
    assert "main_rivers" not in place_cols


def test_place_watershed_main_rivers_empty_string_is_not_coerced_to_null(tmp_path, monkeypatch):
    """main_rivers が空文字列（水系名を構成する河川が無い流域）の場合、v1
    （`?? null`、nullish coalescing）と同じく NULL には丸めずそのまま持つ
    （brief: main_rivers は JSONL・v1 とも空文字列で NULL ではない）。
    """
    row = dict(_WATERSHED_ROW_FULL, watershed_id="83032-0088", main_river_names_ja="")
    conn, _counts = _build(tmp_path, monkeypatch, [], [row])

    attr = conn.execute("SELECT main_rivers FROM place_watershed").fetchone()
    assert attr["main_rivers"] == ""
    assert attr["main_rivers"] is not None


def test_watershed_place_not_loaded_when_watershed_jsonl_is_empty(tmp_path, monkeypatch):
    """watershed 節への入力が0件なら place_kind='watershed' の行も0件
    （WATERSHED_JSONL の存在は必須だが、中身が空でもクラッシュしない）。
    """
    conn, counts = _build(tmp_path, monkeypatch, [], [])
    assert counts["place_watershed"] == 0
    n = conn.execute("SELECT COUNT(*) FROM place WHERE place_kind='watershed'").fetchone()[0]
    assert n == 0


# ---------------------------------------------------------------------------
# place_relation: 地点 -> 流域（sites.watershed 由来。Phase B
# `phase-b/place-attributes`、P-1a）
# ---------------------------------------------------------------------------

def test_watershed_relation_edge_resolves_via_sites_watershed(tmp_path, monkeypatch):
    """sites.watershed が指す v1 の watershed_id から、place_source_ref
    (source_id='watershed_meta.watershed_id') 経由で流域の place_id を解決し、
    'within' 辺を1本作る（fraction=1.0）。
    """
    sites_rows = [
        ("jma_stations_kanagawa__s1", "地点1", 35.0, 139.0, 10.0, "src", "ref", None, "83032-0024"),
    ]
    conn, counts = _build(tmp_path, monkeypatch, sites_rows, [_WATERSHED_ROW_FULL])

    assert counts["place_relation"] == 1
    row = conn.execute(
        "SELECT parent_id, child_id, relation, fraction FROM place_relation"
    ).fetchone()
    assert row["parent_id"] == "common:place:watershed.nlni-83032-0024"
    assert row["child_id"] == "jp-14:place:site.jma-s1"
    assert row["relation"] == "within"
    assert row["fraction"] == 1.0


def test_watershed_relation_edge_count_matches_sites_with_watershed_not_null(tmp_path, monkeypatch):
    """place_relation の地点->流域の辺数は sites.watershed IS NOT NULL の地点数と
    一致する（受け入れ条件3。実データでは278件のはず——本テストは小規模版）。
    """
    row2 = dict(_WATERSHED_ROW_FULL, watershed_id="83032-0099")
    sites_rows = [
        ("jma_stations_kanagawa__s1", "地点1", 35.0, 139.0, 10.0, "src", "ref", None, "83032-0024"),
        ("jma_stations_kanagawa__s2", "地点2", 35.1, 139.1, 20.0, "src", "ref", None, "83032-0099"),
        ("jma_stations_kanagawa__s3", "地点3", 35.2, 139.2, 30.0, "src", "ref", None, None),  # 流域無し
    ]
    conn, counts = _build(tmp_path, monkeypatch, sites_rows, [_WATERSHED_ROW_FULL, row2])

    assert counts["place_relation"] == 2
    n_within_watershed = conn.execute(
        "SELECT COUNT(*) FROM place_relation pr "
        "JOIN place_source_ref wref ON wref.place_id = pr.parent_id "
        "  AND wref.source_id = 'watershed_meta.watershed_id' "
        "WHERE pr.relation = 'within'"
    ).fetchone()[0]
    assert n_within_watershed == 2


def test_unresolvable_watershed_value_raises(tmp_path, monkeypatch):
    """sites.watershed が指す watershed_id が place に無ければ、黙って捨てず
    例外で止める（`_zone_relation_rows()` と同じ流儀）。
    """
    sites_rows = [
        ("jma_stations_kanagawa__s1", "地点1", 35.0, 139.0, 10.0, "src", "ref", None, "99999-9999"),
    ]
    with pytest.raises(ValueError, match="解決できる.*流域が place に無い"):
        _build(tmp_path, monkeypatch, sites_rows, [_WATERSHED_ROW_FULL])


def test_site_has_at_most_one_watershed_edge_by_construction(tmp_path, monkeypatch):
    """`sites.watershed` は単一列なので、build_place.py が組み立てる地点->流域の
    辺は地点ごとに高々1本になる（r01 側の機械検証
    `_assert_relation_child_is_single_valued(conn, "watershed_meta.watershed_id", ...)`
    が独立に保証する不変条件の、build_place.py 側からの裏付け）。
    """
    row2 = dict(_WATERSHED_ROW_FULL, watershed_id="83032-0099")
    sites_rows = [
        ("jma_stations_kanagawa__s1", "地点1", 35.0, 139.0, 10.0, "src", "ref", None, "83032-0024"),
    ]
    conn, _counts = _build(tmp_path, monkeypatch, sites_rows, [_WATERSHED_ROW_FULL, row2])

    n = conn.execute(
        "SELECT COUNT(*) FROM place_relation pr "
        "JOIN place_source_ref wref ON wref.place_id = pr.parent_id "
        "  AND wref.source_id = 'watershed_meta.watershed_id' "
        "WHERE pr.relation = 'within' AND pr.child_id = 'jp-14:place:site.jma-s1'"
    ).fetchone()[0]
    assert n == 1


# ---------------------------------------------------------------------------
# _load_watershed_jsonl() の防御（code-review 指摘1・11）
# ---------------------------------------------------------------------------

def test_load_watershed_jsonl_raises_file_not_found_when_missing(tmp_path, monkeypatch):
    """`data/processed/nlni_w12_watersheds.jsonl` が無いと分かりやすいエラーで
    止まる（worktree で symlink を張り忘れたときに必ず踏む経路。CLAUDE.md の
    worktree 運用の symlink 手順参照）。
    """
    monkeypatch.setattr(
        build_place_module, "WATERSHED_JSONL", tmp_path / "does_not_exist.jsonl"
    )
    with pytest.raises(FileNotFoundError, match="流域界の原本が無い"):
        build_place_module._load_watershed_jsonl()


def test_load_watershed_jsonl_raises_on_missing_required_key(tmp_path, monkeypatch):
    """JSONL の1行に必須キーが無ければ、黙って NULL 埋めせず例外で止まる
    （code-review 指摘1: `.get()` で読むと、入力側でキーが消えた・改名された
    ときに全行が黙って NULL になり、r01 は「377行できた」と出して通ってしまう）。
    """
    jsonl_path = tmp_path / "nlni_w12_watersheds.jsonl"
    row = dict(_WATERSHED_ROW_FULL)
    del row["area_km2"]  # 必須キーを1つ欠かす
    write_watershed_jsonl(jsonl_path, [row])
    monkeypatch.setattr(build_place_module, "WATERSHED_JSONL", jsonl_path)

    with pytest.raises(ValueError, match="必須キーが無い"):
        build_place_module._load_watershed_jsonl()
