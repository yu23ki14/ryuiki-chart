"""c30〜c35・c62 の `--region`。jp-14 の出力名・source_id・raw パス・URL が従来の直書きと1文字も変わらないこと、
jp-46 が `_amami` 付きになること。ネットワークにも原本にも触れない（`nlni_lib.layout()` は名前を返すだけ）。"""
import pathlib

import pytest

pytest.importorskip("shapely")
pytest.importorskip("pyproj")

from common import RAW  # noqa: E402
import nlni_lib  # noqa: E402

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent
Z = "https://nlftp.mlit.go.jp/ksj"


def test_jp14_names_are_the_old_literals():
    L = nlni_lib.layout("jp-14")
    assert L["clip_bbox"] is None                      # 県全域は絞らない（従来の挙動）
    assert (L["pref"], L["pref_name_ja"], L["pref_short"], L["name_ja"]) == ("14", "神奈川県", "神奈川", "神奈川県")
    # c31
    assert L["w05_sid"] == "nlni_w05_rivers" and L["w05_nodes_sid"] == "nlni_w05_river_nodes"
    assert L["w05_dir"] == RAW / "nlni_w05_rivers"
    assert L["w05_stream_shp"] == RAW / "nlni_w05_rivers" / "W05-08_14-g_Stream.shp"
    assert L["w05_node_shp"] == RAW / "nlni_w05_rivers" / "W05-08_14-g_RiverNode.shp"
    assert (L["w05_stream_stem"], L["w05_node_stem"]) == ("W05-08_14-g_Stream", "W05-08_14-g_RiverNode")
    assert L["w05_zip_url"] == f"{Z}/gml/data/W05/W05-08/W05-08_14_GML.zip"
    assert L["w05_year_ja"] == "平成20年"
    # c30
    assert L["w12_sid"] == "nlni_w12_watersheds"
    assert L["w12_shp"] == RAW / "nlni_w12_watersheds" / "W12-52A-2K-14_WatershedBoundary.shp"
    assert L["w12_zip_url"] == f"{Z}/gmlold/data/W12/W12-52A/W12-52A-14-01.0a_GML.zip"
    # c32 / c33 / c35
    assert L["a10_sid"] == "nlni_a10_natparks"
    assert L["a10_zip_url"] == f"{Z}/gml/data/A10/A10-15/A10-15_14_GML.zip"
    assert L["a15_sid"] == "nlni_a15_wildlife"
    assert L["a15_zip_url"] == f"{Z}/jpgis/data/A15/A15-09/A15-09_14.zip"
    assert L["a15_xml"] == RAW / "nlni_a15_wildlife" / "A15-09_14" / "A15-09_14.xml"
    assert L["a45_sid"] == "nlni_a45_forest"
    assert L["a45_zip_url"] == f"{Z}/gml/data/A45/A45-19/A45-19_14_GML.zip"
    # c34
    assert L["l03b_dir"] == RAW / "nlni_l03b_landuse"
    assert L["l03b_meshes"] == ("5238", "5239", "5338", "5339")
    assert [L["l03b_sid"](y) for y in (2006, 2016)] == ["nlni_l03b_landuse_2006", "nlni_l03b_landuse_2016"]
    assert L["l03b_by_ws_sid"] == "nlni_l03b_landuse_by_watershed"
    # c62
    assert L["elev_sid"] == "gsi_elevation_grid"
    assert L["bbox"] == (138.9, 35.1, 139.8, 35.7)


def test_jp46_names_carry_amami_suffix():
    L = nlni_lib.layout("jp-46")
    assert L["clip_bbox"] == L["bbox"] == (129.1, 27.95, 129.85, 28.8)   # 県の一部なので bbox に絞る
    assert (L["pref"], L["pref_name_ja"], L["pref_short"]) == ("46", "鹿児島県", "鹿児島")
    assert L["w05_sid"] == "nlni_w05_rivers_amami" and L["w05_nodes_sid"] == "nlni_w05_river_nodes_amami"
    assert L["w05_stream_shp"] == RAW / "nlni_w05_rivers_amami" / "W05-07_46-g_Stream.shp"
    assert L["w05_zip_url"] == f"{Z}/gml/data/W05/W05-07/W05-07_46_GML.zip"   # 鹿児島に W05-08 は無い
    assert L["w12_sid"] == "nlni_w12_watersheds_amami"
    assert L["w12_shp"] == RAW / "nlni_w12_watersheds_amami" / "W12-52A-2K-46_WatershedBoundary.shp"
    assert (L["a10_sid"], L["a15_sid"], L["a45_sid"]) == (
        "nlni_a10_natparks_amami", "nlni_a15_wildlife_amami", "nlni_a45_forest_amami")
    assert L["a15_xml"] == RAW / "nlni_a15_wildlife_amami" / "A15-09_46" / "A15-09_46.xml"
    assert L["l03b_meshes"] == ("4229",)
    assert L["l03b_sid"](2016) == "nlni_l03b_landuse_2016_amami"
    assert L["l03b_by_ws_sid"] == "nlni_l03b_landuse_by_watershed_amami"
    assert L["elev_sid"] == "gsi_elevation_grid_amami"


@pytest.mark.parametrize("fn", ["c30_nlni_w12", "c31_nlni_w05", "c32_nlni_a10", "c33_nlni_a15",
                                "c34_nlni_l03b", "c35_nlni_a45", "c62_gsi_elevation"])
def test_scripts_take_region_and_use_layout(fn):
    src = (SCRIPTS / f"{fn}.py").read_text(encoding="utf-8")
    assert "add_region_arg(" in src and "layout(" in src
