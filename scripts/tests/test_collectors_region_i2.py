"""Step 1 I2: c02/c03/c80/c65 の `--region`（docs/plans/AMAMI_STEP1.md §3, §5-1）。

- jp-14（既定）の出力名・source_id・raw/進捗パス・Overpass クエリが変更前と1文字も変わらない
- jp-46 では地域別になり、jp-14 のパスを踏まない
ネットワークに出ない。
"""
import hashlib
import pathlib

import pytest

import regions as rc

SCRIPTS = pathlib.Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


# ---- c02 -----------------------------------------------------------------
@pytest.fixture
def c02():
    import c02_gbif
    c02_gbif.configure("jp-14")
    yield c02_gbif
    c02_gbif.configure("jp-14")


def test_c02_jp14_unchanged(c02):
    assert c02.GADM == "JPN.19_1" and c02.GADM_PARAM == "JPN.19_1"
    assert c02.SOURCE_ID == "gbif_kanagawa_occurrences"
    proc, logs = ROOT / "data" / "processed", ROOT / "data" / "logs"
    assert c02.OUT_JSONL == proc / "gbif_kanagawa_occurrences.jsonl"
    assert c02.OUT_CSV == proc / "gbif_kanagawa_occurrences.csv"
    assert c02.SUMMARY_DATASET == proc / "gbif_kanagawa_summary_by_dataset.csv"
    assert c02.CHECKLIST == proc / "gbif_kanagawa_species_checklist.csv"
    assert c02.PROGRESS == logs / "gbif_progress.json"
    assert c02.PARTITION_REPORT == logs / "gbif_partition_report.csv"
    assert c02.AREA_JA == "神奈川県"


def test_c02_jp46_is_regional(c02):
    c02.configure("jp-46")
    assert c02.SOURCE_ID == "gbif_amami_occurrences"
    assert c02.GADM_PARAM == list(rc.get("jp-46")["gbif_gadm_gids"])
    assert c02.OUT_JSONL.name == "gbif_amami_occurrences.jsonl"
    assert c02.PROGRESS.name == "gbif_progress_amami.json"
    assert c02.PARTITION_REPORT.name == "gbif_partition_report_amami.csv"
    assert c02.SUMMARY_DATASET.name == "gbif_amami_summary_by_dataset.csv"
    assert c02.CHECKLIST.name == "gbif_amami_species_checklist.csv"


# ---- c03 -----------------------------------------------------------------
def test_c03_names():
    import c03_inaturalist as c03
    assert rc.name("inaturalist_kanagawa", "jp-14") == "inaturalist_kanagawa"
    assert rc.name("inaturalist_kanagawa", "jp-46") == "inaturalist_amami"
    assert rc.get("jp-14")["inat_place_ids"] == (10918,)
    assert c03.flat({"id": 1}, "x")["source_id"] == "x"
    assert c03.flat({"id": 1})["source_id"] == "inaturalist_kanagawa"


# ---- c80 -----------------------------------------------------------------
@pytest.fixture
def c80():
    import c80_biodic_ikimonomap
    c80_biodic_ikimonomap.configure("jp-14")
    yield c80_biodic_ikimonomap
    c80_biodic_ikimonomap.configure("jp-14")


def test_c80_jp14_unchanged(c80):
    assert c80.RAW_DIR == ROOT / "data" / "raw" / "biodic_ikimonomap"
    assert c80.BBOX == (138.9, 35.1, 139.8, 35.7)
    assert c80.SID_VEG == "biodic_veg2024_kanagawa"
    assert c80.SID_MAMMAL == "biodic_mammal_mesh_kanagawa"
    assert c80.VG2024_LAYER_URL.endswith("/vg2024/MapServer/2")
    assert c80.VG_BLOCK_JA == "関東" and c80.AREA_JA == "神奈川県"


def test_c80_jp46_is_regional(c80):
    c80.configure("jp-46")
    assert c80.RAW_DIR.name == "biodic_ikimonomap_amami"
    assert c80.BBOX == rc.get("jp-46")["bbox"]
    assert c80.SID_VEG == "biodic_veg2024_amami"
    assert c80.SID_MAMMAL == "biodic_mammal_mesh_amami"
    assert c80.VG2024_LAYER_URL.endswith("/vg2024/MapServer/7")  # 九州・沖縄ブロック


# ---- c65 -----------------------------------------------------------------
JP14_QUERY_SHA = {
    "water": "47ffcf135fad31d7",
    "forest": "37257dc560e9e8ec",
    "farmland": "4b79e655400391dc",
    "protected_area": "09bbb8e47a848a05",
}


@pytest.mark.parametrize("cat", sorted(JP14_QUERY_SHA))
def test_c65_jp14_query_and_ids_unchanged(cat):
    import c65_osm_overpass as c65
    cfg = c65.render_cfg(cat, "jp-14")
    assert _sha(cfg["query"]) == JP14_QUERY_SHA[cat]
    assert cfg["source_id"] == f"osm_kanagawa_{cat}"
    assert cfg["name"] == c65.CATEGORIES[cat]["name"]
    assert 'area["ISO3166-2"="JP-14"]->.a;' in cfg["query"]


@pytest.mark.parametrize("cat", sorted(JP14_QUERY_SHA))
def test_c65_jp46_uses_bbox(cat):
    import c65_osm_overpass as c65
    cfg = c65.render_cfg(cat, "jp-46")
    assert cfg["source_id"] == f"osm_amami_{cat}"
    assert "ISO3166-2" not in cfg["query"] and "area.a" not in cfg["query"]
    assert "(27.95,129.1,28.8,129.85)" in cfg["query"]
    assert "神奈川" not in cfg["name"]
