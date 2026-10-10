"""c スクリプトの `--region`（docs/plans/AMAMI_STEP1.md §1・§5-1）。ネットワークにも原本にも触れない。

- jp-14（既定）の出力名・source_id・raw/進捗パス・定数が従来の直書きと1文字も変わらない（表 JP14 を parametrize）
- jp-46 → jp-14 の順で切り替えても、地域依存の値が全て jp-14 に戻る
- jp-46 は地域別の名前になり、jp-14 のパスを踏まない
"""
import pathlib

import pytest

pytest.importorskip("pandas")
pytest.importorskip("requests")
pytest.importorskip("shapely")
pytest.importorskip("pyproj")

import c02_gbif, c03_inaturalist, c10_jma, c11_soramame, c12_env_kousui, c15_jma_sst  # noqa: E402
import c65_osm_overpass, c80_biodic_ikimonomap, c62_gsi_elevation  # noqa: E402
import common, nlni_lib, regions  # noqa: E402
from common import RAW, PROC, LOGS  # noqa: E402

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent
Z = "https://nlftp.mlit.go.jp/ksj"

# 地域を切り替える関数を持つ c スクリプト
SWITCHERS = {
    "c02": (c02_gbif, c02_gbif.configure), "c10": (c10_jma, c10_jma.set_region),
    "c11": (c11_soramame, c11_soramame.set_region), "c12": (c12_env_kousui, c12_env_kousui.set_region),
    "c65": (c65_osm_overpass, c65_osm_overpass.configure), "c80": (c80_biodic_ikimonomap, c80_biodic_ikimonomap.configure),
}

TANUKI = ("14209050", "津久井（相模川上流・城山ダム下流）"), ("14401010", "愛川町角田（中津川・相模川中流）"), \
         ("14321010", "寒川町役場（相模川下流）"), ("14206010", "小田原市役所（酒匂川下流）")

# (スクリプト, 名前の種類) -> jp-14 の期待値。モジュールの属性（SWITCHERS のキー）か layout() の鍵（"layout"）
JP14 = [
    ("c02", "SOURCE_ID", "gbif_kanagawa_occurrences"), ("c02", "AREA_JA", "神奈川県"),
    ("c02", "GADM_PARAM", "JPN.19_1"),
    ("c02", "OUT_JSONL", PROC / "gbif_kanagawa_occurrences.jsonl"), ("c02", "OUT_CSV", PROC / "gbif_kanagawa_occurrences.csv"),
    ("c02", "SUMMARY_DATASET", PROC / "gbif_kanagawa_summary_by_dataset.csv"),
    ("c02", "CHECKLIST", PROC / "gbif_kanagawa_species_checklist.csv"),
    ("c02", "PROGRESS", LOGS / "gbif_progress.json"), ("c02", "PARTITION_REPORT", LOGS / "gbif_partition_report.csv"),
    ("c10", "SID_ST", "jma_stations_kanagawa"), ("c10", "SID_MON", "jma_monthly_kanagawa"),
    ("c10", "SID_DAY", "jma_daily_yokohama"), ("c10", "PREC", 46), ("c10", "BLOCKS", None),
    ("c10", "RAWD", RAW / "jma"), ("c10", "PREF_JA", "神奈川県"), ("c10", "LABEL", "神奈川県"),
    ("c10", "TARGETS", ["横浜", "海老名", "辻堂", "小田原", "丹沢湖", "相模湖", "三浦"]), ("c10", "DAILY_ST", "横浜"),
    ("c10", "DAILY_PERIODS", [(2024, 1, 12), (2025, 1, 12), (2026, 1, 12)]),
    ("c10", "DAILY_NOTE", "2024-01〜直近月の日別値"),
    ("c11", "SID_ST", "soramame_stations_kanagawa"), ("c11", "SID_TS", "soramame_hourly_kanagawa"),
    ("c11", "RAWD", RAW / "soramame"), ("c11", "PREF", "14"), ("c11", "LABEL", "神奈川県"),
    ("c11", "TARGET_STATIONS", dict(TANUKI)), ("c11", "ONLY_TARGETS", False),
    ("c12", "SID_ST", "env_kousui_stations_kanagawa"), ("c12", "SID_Y", "env_kousui_annual_kanagawa"),
    ("c12", "SID_K", "env_kousui_sample_kanagawa"), ("c12", "PREF", "14"), ("c12", "RAWD", RAW / "env_kousui"),
    ("c12", "LABEL", "神奈川県"), ("c12", "BBOX", None), ("c12", "KEEP", None),
    ("c65", "RAW_DIR", RAW / "osm_kanagawa"),
    ("c80", "RAW_DIR", RAW / "biodic_ikimonomap"), ("c80", "BBOX", (138.9, 35.1, 139.8, 35.7)),
    ("c80", "SID_VEG", "biodic_veg2024_kanagawa"), ("c80", "SID_MAMMAL", "biodic_mammal_mesh_kanagawa"),
    ("c80", "AREA_JA", "神奈川県"), ("c80", "VG_BLOCK_JA", "関東"), ("c80", "VG_LAYER_ID", 2),
    ("c80", "VG2024_LAYER_URL", "https://arc-gis.biodic.go.jp/arcgis/rest/services/webgis/vg2024/MapServer/2"),
    # 国土数値情報の layout()（c30〜c35・c62）
    ("layout", "clip_bbox", None), ("layout", "bbox", (138.9, 35.1, 139.8, 35.7)),
    ("layout", "pref", "14"), ("layout", "pref_name_ja", "神奈川県"), ("layout", "pref_short", "神奈川"),
    ("layout", "name_ja", "神奈川県"),
    ("layout", "w05_sid", "nlni_w05_rivers"), ("layout", "w05_nodes_sid", "nlni_w05_river_nodes"),
    ("layout", "w05_dir", RAW / "nlni_w05_rivers"),
    ("layout", "w05_stream_shp", RAW / "nlni_w05_rivers" / "W05-08_14-g_Stream.shp"),
    ("layout", "w05_node_shp", RAW / "nlni_w05_rivers" / "W05-08_14-g_RiverNode.shp"),
    ("layout", "w05_stream_stem", "W05-08_14-g_Stream"), ("layout", "w05_node_stem", "W05-08_14-g_RiverNode"),
    ("layout", "w05_zip_url", f"{Z}/gml/data/W05/W05-08/W05-08_14_GML.zip"),
    ("layout", "w05_year_ja", "平成20年"), ("layout", "w05_year_note", "平成20(2008)年"),
    ("layout", "w12_sid", "nlni_w12_watersheds"),
    ("layout", "w12_shp", RAW / "nlni_w12_watersheds" / "W12-52A-2K-14_WatershedBoundary.shp"),
    ("layout", "w12_zip_url", f"{Z}/gmlold/data/W12/W12-52A/W12-52A-14-01.0a_GML.zip"),
    ("layout", "a10_sid", "nlni_a10_natparks"), ("layout", "a10_zip_url", f"{Z}/gml/data/A10/A10-15/A10-15_14_GML.zip"),
    ("layout", "a15_sid", "nlni_a15_wildlife"), ("layout", "a15_zip_url", f"{Z}/jpgis/data/A15/A15-09/A15-09_14.zip"),
    ("layout", "a15_xml", RAW / "nlni_a15_wildlife" / "A15-09_14" / "A15-09_14.xml"),
    ("layout", "a45_sid", "nlni_a45_forest"), ("layout", "a45_zip_url", f"{Z}/gml/data/A45/A45-19/A45-19_14_GML.zip"),
    ("layout", "l03b_dir", RAW / "nlni_l03b_landuse"), ("layout", "l03b_meshes", ("5238", "5239", "5338", "5339")),
    ("layout", "l03b_by_ws_sid", "nlni_l03b_landuse_by_watershed"), ("layout", "elev_sid", "gsi_elevation_grid"),
]


def _actual(script, attr):
    if script == "layout":
        return nlni_lib.layout("jp-14")[attr]
    return getattr(SWITCHERS[script][0], attr)


@pytest.fixture(autouse=True)
def _restore_jp14():
    yield
    for _, fn in SWITCHERS.values():
        fn("jp-14")


@pytest.mark.parametrize("script,attr,expected", JP14, ids=[f"{s}.{a}" for s, a, _ in JP14])
def test_jp14_is_the_old_literal(script, attr, expected):
    assert _actual(script, attr) == expected


def test_jp14_l03b_sid_and_c03_c15_names():
    L = nlni_lib.layout("jp-14")
    assert [L["l03b_sid"](y) for y in (2006, 2016)] == ["nlni_l03b_landuse_2006", "nlni_l03b_landuse_2016"]
    assert regions.name("inaturalist_kanagawa", "jp-14") == "inaturalist_kanagawa"
    assert c03_inaturalist.flat({"id": 1})["source_id"] == "inaturalist_kanagawa"
    assert regions.get("jp-14")["inat_place_ids"] == (10918,)


@pytest.mark.parametrize("script", sorted(SWITCHERS))
def test_switching_to_jp46_and_back_restores_every_value(script):
    mod, fn = SWITCHERS[script]
    fn("jp-46")
    fn("jp-14")
    for s, attr, expected in JP14:
        if s == script:
            assert getattr(mod, attr) == expected, f"{script}.{attr}"


def test_jp46_values():
    c10_jma.set_region("jp-46")
    m = c10_jma
    assert (m.SID_ST, m.SID_MON, m.SID_DAY) == ("jma_stations_amami", "jma_monthly_amami", "jma_daily_nase")
    assert m.PREC == 88 and m.BLOCKS == {"47909", "1520", "0980"} and m.LABEL == "奄美大島"
    assert m.RAWD == RAW / "jma_amami" and m.TARGETS == ["名瀬", "笠利", "古仁屋"] and m.DAILY_ST == "名瀬"
    assert (2010, 10, 10) in m.DAILY_PERIODS
    c11_soramame.set_region("jp-46")
    assert (c11_soramame.SID_TS, c11_soramame.PREF, c11_soramame.ONLY_TARGETS) == ("soramame_hourly_amami", "46", True)
    assert list(c11_soramame.TARGET_STATIONS) == ["46225010"]
    c12_env_kousui.set_region("jp-46")
    m = c12_env_kousui
    assert (m.SID_ST, m.SID_Y, m.SID_K) == ("env_kousui_stations_amami", "env_kousui_annual_amami", "env_kousui_sample_amami")
    assert m.PREF == "46" and m.RAWD == RAW / "env_kousui_amami" and m.BBOX == regions.get("jp-46")["bbox"]
    c02_gbif.configure("jp-46")
    assert c02_gbif.SOURCE_ID == "gbif_amami_occurrences" and c02_gbif.PROGRESS.name == "gbif_progress_amami.json"
    assert c02_gbif.GADM_PARAM == list(regions.get("jp-46")["gbif_gadm_gids"])
    c80_biodic_ikimonomap.configure("jp-46")
    c = c80_biodic_ikimonomap
    assert c.RAW_DIR.name == "biodic_ikimonomap_amami" and c.SID_VEG == "biodic_veg2024_amami"
    assert c.VG2024_LAYER_URL.endswith("/vg2024/MapServer/7") and c.BBOX == regions.get("jp-46")["bbox"]
    L = nlni_lib.layout("jp-46")
    assert L["clip_bbox"] == L["bbox"] == (129.1, 27.95, 129.85, 28.8)
    assert L["w05_zip_url"] == f"{Z}/gml/data/W05/W05-07/W05-07_46_GML.zip" and L["w05_year_note"] == "平成19(2007)年"
    assert L["w12_sid"] == "nlni_w12_watersheds_amami" and L["l03b_meshes"] == ("4129", "4229", "4329")
    assert L["l03b_sid"](2016) == "nlni_l03b_landuse_2016_amami" and L["elev_sid"] == "gsi_elevation_grid_amami"
    assert L["a15_xml"] == RAW / "nlni_a15_wildlife_amami" / "A15-09_46" / "A15-09_46.xml"


# ---- c65: jp-14 のクエリが1文字も変わらない -------------------------------------
JP14_QUERY_SHA = {
    "water": "47ffcf135fad31d7", "forest": "37257dc560e9e8ec",
    "farmland": "4b79e655400391dc", "protected_area": "09bbb8e47a848a05",
}


@pytest.mark.parametrize("cat", sorted(JP14_QUERY_SHA))
def test_c65_jp14_query_and_ids_unchanged(cat):
    import hashlib
    cfg = c65_osm_overpass.render_cfg(cat, "jp-14")
    assert hashlib.sha256(cfg["query"].encode("utf-8")).hexdigest()[:16] == JP14_QUERY_SHA[cat]
    assert cfg["source_id"] == f"osm_kanagawa_{cat}"
    assert 'area["ISO3166-2"="JP-14"]->.a;' in cfg["query"]


@pytest.mark.parametrize("cat", sorted(JP14_QUERY_SHA))
def test_c65_jp46_uses_bbox(cat):
    cfg = c65_osm_overpass.render_cfg(cat, "jp-46")
    assert cfg["source_id"] == f"osm_amami_{cat}"
    assert "ISO3166-2" not in cfg["query"] and "(27.95,129.1,28.8,129.85)" in cfg["query"]
    assert "神奈川" not in cfg["name"]


def test_c65_extra_notes_are_per_region():
    assert "17件のみ" in regions.get("jp-14")["osm_extra_notes"]["protected_area"]
    assert regions.get("jp-46")["osm_extra_notes"] == {}


# ---- regions の共通関数 -------------------------------------------------------------
def test_clip_bbox_and_in_bbox():
    assert regions.clip_bbox("jp-14") is None
    assert regions.clip_bbox("jp-46") == regions.get("jp-46")["bbox"]
    b = regions.get("jp-46")["bbox"]
    assert regions.in_bbox(b, 28.37, 129.5) and not regions.in_bbox(b, 31.5, 130.5)
    assert not regions.in_bbox(b, None, 129.5) and not regions.in_bbox(b, 28.0, None)


@pytest.mark.parametrize("fn", ["c30_nlni_w12", "c31_nlni_w05", "c32_nlni_a10", "c33_nlni_a15",
                                "c34_nlni_l03b", "c35_nlni_a45", "c62_gsi_elevation"])
def test_scripts_take_region_and_use_layout(fn):
    src = (SCRIPTS / f"{fn}.py").read_text(encoding="utf-8")
    assert "add_region_arg(" in src and "layout(" in src
    assert 'RID != "jp-14"' not in src and 'RID == "jp-14"' not in src


def test_c62_amami_grid_uses_l03b_land_cells(tmp_path, monkeypatch):
    # 陸セル1枚: 格子点 (129.30, 28.20) は入り、(129.31, 28.20) は入らない。
    (tmp_path / "nlni_l03b_landuse_2016_amami.csv").write_text(
        "centroid_lat,centroid_lon\n28.200417,129.300625\n", encoding="utf-8")
    monkeypatch.setattr(c62_gsi_elevation, "PROC", tmp_path)
    assert c62_gsi_elevation.land_points([(129.30, 28.20), (129.31, 28.20)], "jp-46") == [(129.30, 28.20)]


# ---- 正しさ ----------------------------------------------------------------------
def test_c15_jp14_does_nothing(monkeypatch, capsys):
    monkeypatch.setattr(c15_jma_sst, "get", lambda *a, **k: pytest.fail("network"))
    monkeypatch.setattr("sys.argv", ["c15_jma_sst.py", "--region", "jp-14"])
    c15_jma_sst.main()
    assert "何もしない" in capsys.readouterr().out


def test_c15_parse_area_and_empty_file_aborts(monkeypatch):
    txt = "yyyy,mm,dd,areaNo.,flag,Temp.\n1982,01,01,617,R, 21.65\n2026,10,09,617,P, 27.32\n1982,01,03,617,R,\n"
    names = dict(regions.get("jp-46")["jma_sst_area_names"])
    rows = c15_jma_sst.parse_area(txt, 617, "jma_sst_amami", "u", names)
    assert [(r["datetime"], r["value"], r["quality_flag"]) for r in rows] == [
        ("1982-01-01", 21.65, "R"), ("2026-10-09", 27.32, "P")]
    assert rows[0]["area_name_ja"] == "奄美群島沿岸北西部" and rows[0]["unit"] == "degC"

    class R:
        text = ""
    monkeypatch.setattr(c15_jma_sst, "get", lambda *a, **k: R())
    monkeypatch.setattr("sys.argv", ["c15_jma_sst.py", "--region", "jp-46"])
    with pytest.raises(SystemExit, match="海域617"):
        c15_jma_sst.main()


def test_c12_aborts_when_station_master_fails(monkeypatch):
    c12 = c12_env_kousui
    c12.set_region("jp-46")
    monkeypatch.setattr(c12, "fetch_fc", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(c12, "register", lambda *a, **k: None)
    monkeypatch.setattr("sys.argv", ["c12_env_kousui.py", "--region", "jp-46"])
    with pytest.raises(SystemExit, match="abort"):
        c12.main()


def test_c03_safety_cap_spans_places(monkeypatch, tmp_path, capsys):
    c03 = c03_inaturalist
    calls = []

    def fake(url, params=None, **k):
        calls.append(params["place_id"])
        a = params["id_above"]
        return {"results": [{"id": a + i + 1} for i in range(200)]}
    monkeypatch.setattr(c03, "get_json", fake)
    monkeypatch.setattr(c03, "PROC", tmp_path)
    monkeypatch.setattr(c03, "register", lambda *a, **k: None)
    c03.main(["--region", "jp-46"])
    assert set(calls) == {34051}            # 先頭の place で上限に達したら、次の place は取らない
    assert capsys.readouterr().out.count("safety cap") == 1


def test_c10_station_match_checks_amedas_prefix(monkeypatch):
    c10 = c10_jma
    c10.set_region("jp-46")
    pt = ("viewPoint('s','47909','名瀬','ナゼ','28','23','129','29','3','1','1','1','1','1','1','','','','')")

    class R:
        text = pt
        encoding = "utf-8"
    tbl = {"88837": {"kjName": "名瀬", "knName": "ナゼ", "enName": "Naze", "lat": [28, 23], "lon": [129, 29], "alt": 3},
           "46999": {"kjName": "名瀬", "knName": "ナゼ", "enName": "Naze", "lat": [35, 0], "lon": [139, 0], "alt": 1}}
    monkeypatch.setattr(c10, "get", lambda *a, **k: R())
    monkeypatch.setattr(c10, "get_json", lambda *a, **k: tbl)
    monkeypatch.setattr(pathlib.Path, "write_text", lambda *a, **k: 0)
    rows = c10.fetch_stations()
    assert [r["amedas_id"] for r in rows] == ["88837"]
