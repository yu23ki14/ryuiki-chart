"""地域（region）ごとの収集の定数を1か所に持つ（docs/plans/AMAMI_STEP0.md §4、docs/add_area.md §4 Step 1）。

`registry/region.yaml` は語彙の正（時刻帯・最高峰）で、registry の指紋に入る。収集の定数をそこに
入れると、定数を直すたびに registry と D1 が作り直しになる。なのでこのファイルに分ける。

- キーは region_id。値は全て tuple（リストではなくタプルで不変）。`muni_codes` が None なら県全域。
- `jp-14` は c02/c03/c10/c12/c34 の直書き定数の転記で、この PR では c スクリプトを書き換えない。
  食い違いは `scripts/tests/test_regions.py` が機械的に検出する。
- `jp-46` の GADM gid・iNaturalist place_id・気象庁の block は、実取得で確かめた値
  （`reports/add_area_kagoshima.md`）。
"""
from __future__ import annotations

REGIONS: dict[str, dict] = {
    "jp-14": {
        "name_ja": "神奈川県",
        "pref_code": "14",
        "muni_codes": None,
        "gbif_gadm_gids": ("JPN.19_1",),
        "inat_place_ids": (10918,),
        # (prec_no, block_no, 種別)。block_no が None なら観測所表から（c10_jma.py の PREC）
        "jma_stations": ((46, None, "all"),),
        "env_water_prefcodes": ("14",),
        "l03b_meshes": ("5238", "5239", "5338", "5339"),
        "nlni_pref_codes": ("14",),
        "estat_pref_codes": ("14",),
    },
    "jp-46": {
        "name_ja": "鹿児島県（奄美大島）",
        "pref_code": "46",
        # 奄美市・大和村・宇検村・瀬戸内町・龍郷町
        "muni_codes": ("46222", "46523", "46524", "46525", "46527"),
        # GADM level2: 奄美市=JPN.18.4 / 龍郷町=.38 / 宇検村=.41 / 大和村=.44 / 瀬戸内町=.34
        "gbif_gadm_gids": ("JPN.18.4_1", "JPN.18.38_1", "JPN.18.41_1", "JPN.18.44_1", "JPN.18.34_1"),
        # iNaturalist: 奄美市=34051 / 瀬戸内町=34081 / 龍郷町=34085 / 大和村=34091 / 宇検村=34088
        "inat_place_ids": (34051, 34081, 34085, 34091, 34088),
        # 名瀬（官署 s1）・笠利（アメダス a1）・古仁屋（アメダス a1）。prec_no=88 は鹿児島県（奄美地方）
        "jma_stations": ((88, "47909", "s1"), (88, "1520", "a1"), (88, "0980", "a1")),
        "env_water_prefcodes": ("46",),
        "l03b_meshes": ("4229",),
        "nlni_pref_codes": ("46",),
        "estat_pref_codes": ("46",),
    },
}
