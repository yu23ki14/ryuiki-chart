"""奄美 Step 1 PR-B（docs/plans/AMAMI_STEP1B.md §0-4・§2.2）: site の ID の scope を出典の名前空間から決める。

- 神奈川の既存 ID は1文字も変わらない（`SITE_NAMESPACE` の神奈川の全接頭辞で固定）。
- 奄美の site は `jp-46:place:site.<ns>.<local>`・`place.region_id='jp-46'`。
- W12 は全地域の jsonl を連結して読み、place_source_ref の版は jsonl の出典で引く。
"""
import json
import pathlib
import sqlite3

import pytest
import regions

from registry import build_place as build_place_module
from registry import common

from .registry_fixtures import make_ryuiki_places_db, open_places_src, write_watershed_jsonl  # noqa: F401
from .test_registry_place import _WATERSHED_ROW_FULL, _build

KANAGAWA_PREFIXES = {
    "env_kousui_stations_kanagawa": "env-pubwater",
    "moni1000_sites": "moni1000",
    "sagami_livecams": "sagami-livecam",
    "jma_stations_kanagawa": "jma",
    "dams_kanagawa": "dams",
    "kanagawa_jiban_chinka": "jiban-chinka",
    "atsugi_river_water_quality": "atsugi-river",
    "hiratsuka_taiki_stations": "hiratsuka-taiki",
    "sagamihara_taiki_stations": "sagamihara-taiki",
    "soramame_stations_kanagawa": "soramame",
    "yokohama_river_waterlevel": "yokohama-waterlevel",
}


def test_kanagawa_site_place_ids_are_unchanged_for_every_prefix():
    """神奈川の全接頭辞で ID が `jp-14:place:site.<ns>.<local>`（PR-B 前と同じ）。ns の対応も固定する。"""
    for prefix, ns in KANAGAWA_PREFIXES.items():
        assert build_place_module.SITE_NAMESPACE[prefix] == ns
        assert regions.site_scope(prefix) == "jp-14"
        assert build_place_module._site_place_id(f"{prefix}__x_1") == f"jp-14:place:site.{ns}.x_1"


def test_kanagawa_place_ids_match_existing_registry_if_available():
    """手元に registry.sqlite があれば、神奈川の site の place_id が全て PR-B 後の ID 関数で再現できる
    （ID を変えていない証拠。無い環境では飛ばす）。"""
    path = common.ROOT / "data" / "db" / "registry.sqlite"
    if not path.exists():
        pytest.skip("registry.sqlite が無い")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT p.place_id, r.external_key FROM place p JOIN place_source_ref r USING (place_id) "
            "WHERE r.key_space='site_id' AND p.place_id LIKE 'jp-14:%'"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        pytest.skip("registry.sqlite に jp-14 の site が無い")
    sup = build_place_module._load_site_supplement()
    for pid, ext in rows:
        local_override = (sup.get(ext) or {}).get("place_local") or None
        assert build_place_module._site_place_id(ext, local_override) == pid


def test_amami_site_ids_use_jp46_scope_and_region(tmp_path, monkeypatch):
    sites_rows = [
        ("jma_stations_amami__jma_47909", "名瀬", 28.385, 129.493, 3.0, "jma_stations_amami", "ref", 4, None),
        ("env_kousui_stations_amami__kousui_4611030", "御殿浜橋", 28.38, 129.498, None, "env_kousui_stations_amami", "ref", None, None),
        ("jma_stations_kanagawa__s1", "地点1", 35.0, 139.0, 10.0, "src", "ref", 1, None),
    ]
    conn, _ = _build(tmp_path, monkeypatch, sites_rows)
    got = {r["place_id"]: r["region_id"] for r in conn.execute("SELECT place_id, region_id FROM place WHERE place_kind='site'")}
    assert got == {
        "jp-46:place:site.jma.jma_47909": "jp-46",
        "jp-46:place:site.env-pubwater.kousui_4611030": "jp-46",
        "jp-14:place:site.jma.s1": "jp-14",
    }


def test_same_local_in_two_regions_does_not_collide(tmp_path, monkeypatch):
    """衝突検査のキーに scope が入る: 別地域で同じ (kind, ns, slug) でも、別 ID なので衝突にならない。"""
    seen: dict = {}
    a = common.place_id("site", "jma", "x 1", scope="jp-14", seen=seen)
    b = common.place_id("site", "jma", "x_1", scope="jp-46", seen=seen)  # slug は同じ x_1 だが scope が違う
    assert a != b
    with pytest.raises(ValueError, match="衝突"):
        common.place_id("site", "jma", "x_1", scope="jp-14", seen=seen)  # 同じ scope なら潰れで止まる


def test_sea_surface_and_soramame_supplement_rows_are_amami_needs_review():
    sup = build_place_module._load_site_supplement()
    ids = {f"jma_sst_amami__{a}" for a in regions.get("jp-46")["jma_sst_areas"]} | {"soramame_stations_amami__soramame_46225010"}
    assert ids <= sup.keys()
    for sid in sorted(ids):
        row = sup[sid]
        assert row["lat"] == "" and row["lon"] == ""  # 座標を推測しない（needs_review になる）
        pid = build_place_module._site_place_id(sid, row["place_local"] or None)
        assert pid.startswith("jp-46:place:site.")
    assert build_place_module._site_place_id("jma_sst_amami__617") == "jp-46:place:site.jma-sst.617"


def test_watershed_jsonls_concatenate_and_edition_follows_each_file(tmp_path, monkeypatch):
    k = tmp_path / "nlni_w12_watersheds.jsonl"
    a = tmp_path / "gsi_dem_watersheds_amami.jsonl"
    write_watershed_jsonl(k, [_WATERSHED_ROW_FULL])
    write_watershed_jsonl(a, [dict(_WATERSHED_ROW_FULL, watershed_id="dem-amami-001", centroid_lat=28.4, centroid_lon=129.6)])
    monkeypatch.setattr(build_place_module, "WATERSHED_JSONLS", [k, a])
    rows = build_place_module._load_watershed_jsonl()
    assert [r["watershed_id"] for r in rows] == ["83032-0024", "dem-amami-001"]
    assert [r["_edition_source_id"] for r in rows] == ["nlni_w12_watersheds", "gsi_dem_watersheds_amami"]


def test_default_watershed_jsonls_cover_every_region():
    names = [p.stem for p in build_place_module.WATERSHED_JSONLS]
    assert names == regions.watershed_stems()
    assert names[0] == "nlni_w12_watersheds"  # 神奈川が先頭（指紋の先頭のハッシュ入力は PR-B 前と同じ）


# --- Issue #94: 奄美の流域は地理院10m標高から計算した面（名前空間 dem）。W12 の nlni とは別 ---

# web の lib/cube/grid.test.ts も同じ JSON の表を読む（place_id ⇔ watershed_id の規則を両側で検査する）
_ID_CASES = json.loads((pathlib.Path(__file__).parent / "fixtures" / "watershed_id_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _ID_CASES, ids=lambda c: c["watershed_id"])
def test_watershed_place_id_cases(case):
    assert common.watershed_place_id(case["watershed_id"]) == case["place_id"]
    ns, key = common.watershed_ns_and_key(case["watershed_id"])
    assert case["place_id"] == f"common:place:watershed.{ns}.{key}"


def test_kanagawa_watershed_place_id_is_unchanged():
    assert common.watershed_place_id("83032-0024") == "common:place:watershed.nlni.83032-0024"
    assert common.watershed_place_id("dem-amami-001") == "common:place:watershed.dem.amami-001"


def test_dem_watershed_builds_place_with_dem_namespace(tmp_path, monkeypatch):
    dem_row = dict(_WATERSHED_ROW_FULL, watershed_id="dem-amami-001", water_system_code_old=None,
                   water_system_name_ja_estimated=None, water_system_category_ja=None,
                   main_river_names_ja="", data_year=None, centroid_lat=28.3, centroid_lon=129.5,
                   unit_kind="coast_group", merged_share=0.25, own_drainage_km2=1.5)
    conn, counts = _build(tmp_path, monkeypatch, [], watershed_rows=[_WATERSHED_ROW_FULL, dem_row])
    assert counts["place_watershed"] == 2
    pid = "common:place:watershed.dem.amami-001"
    assert conn.execute(
        "SELECT place_id FROM place_source_ref WHERE key_space='watershed_id' AND external_key='dem-amami-001'"
    ).fetchone()[0] == pid
    assert conn.execute("SELECT place_kind, region_id FROM place WHERE place_id=?", (pid,)).fetchone()[0] == "watershed"
    # 種別・併合した割合・自前の集水面積は専用列に届く（水系区分の列には混ぜない）。W12 の行は NULL
    assert tuple(conn.execute(
        "SELECT water_system_category, unit_kind, merged_share, own_drainage_km2 FROM place_watershed WHERE place_id=?",
        (pid,)).fetchone()) == (None, "coast_group", 0.25, 1.5)
    assert tuple(conn.execute(
        "SELECT unit_kind, merged_share, own_drainage_km2 FROM place_watershed WHERE place_id='common:place:watershed.nlni.83032-0024'"
    ).fetchone()) == (None, None, None)
    # 神奈川の流域の ID は従来のまま
    assert conn.execute("SELECT COUNT(*) FROM place WHERE place_id='common:place:watershed.nlni.83032-0024'").fetchone()[0] == 1
