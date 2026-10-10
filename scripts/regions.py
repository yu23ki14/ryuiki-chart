"""地域（region）ごとの収集の定数を1か所に持つ（docs/plans/AMAMI_STEP0.md §4、docs/add_area.md §4 Step 1）。

`registry/region.yaml` は語彙の正（時刻帯・最高峰）で、registry の指紋に入る。収集の定数をそこに
入れると、定数を直すたびに registry と D1 が作り直しになる。なのでこのファイルに分ける。

- キーは region_id。値は全て tuple（リストではなくタプルで不変）。`muni_codes` が None なら県全域。
- `jp-14` は c02/c03/c10/c12/c34 の直書き定数の転記で、この PR では c スクリプトを書き換えない。
  食い違いは `scripts/tests/test_regions.py` が機械的に検出する。
- `jp-46` の GADM gid・iNaturalist place_id・気象庁の block は、実取得で確かめた値
  （`reports/add_area_kagoshima.md`）。
- `bbox`（lon_min, lat_min, lon_max, lat_max）。jp-14 は c80/m01 の `KANAGAWA_BBOX` の転記。jp-46 は C23 の
  奄美5市町村の海岸線（`data/processed/nlni_c23_coastline.geojson`）の範囲 経度129.13〜129.78・緯度27.997〜28.759
  （最南は請島・与路島）に余白を足した (129.1, 27.95, 129.85, 28.8)。喜界島（東経129.9度以東）は
  東端129.85より東、徳之島（北端は北緯約27.88度）は南端27.95より南なので、どちらも入らない。
- `soramame_stations`: 測定局コード -> 名称。jp-14 は c11 の `TARGET_STATIONS` の転記。jp-46 は奄美市名瀬浦上町1-12の
  「奄美」(46225010)。そらまめ君の局マスタ（`/data/sokutei/existence/YYYY/MM/DD/HH.csv`、都道府県コード=46）で確認。
- `jma_sst_areas`: 気象庁「日本沿岸域の海面水温情報」の海域番号。617=奄美群島沿岸北西部／618=南西部／619=南東部／
  620=北東部（`.../kaikyo/series/engan/engan_KG.html` に一覧）。データは
  `https://www.data.jma.go.jp/kaiyou/data/db/kaikyo/series/engan/txt/area<番号>.txt`
  （`yyyy,mm,dd,areaNo.,flag,Temp.` のCSV。1982年〜前日）で確認。jp-14 は範囲外で空。
"""
from __future__ import annotations

import re

REGIONS: dict[str, dict] = {
    "jp-14": {
        "slug": "kanagawa",
        "bbox": (138.9, 35.1, 139.8, 35.7),
        "soramame_stations": (
            ("14209050", "津久井（相模川上流・城山ダム下流）"),
            ("14401010", "愛川町角田（中津川・相模川中流）"),
            ("14321010", "寒川町役場（相模川下流）"),
            ("14206010", "小田原市役所（酒匂川下流）"),
        ),
        "jma_sst_areas": (),
        "name_ja": "神奈川県",
        "label": "神奈川県",              # register() の名称に入れる地域の呼び名（c10/c11/c12）
        "pref_code": "14",
        "pref_name_ja": "神奈川県",    # name_ja とは別（name_ja は対象地域の呼び名。C23 の prefecture_name_ja に使う）
        "muni_codes": None,
        "gbif_gadm_gids": ("JPN.19_1",),
        "inat_place_ids": (10918,),
        # (prec_no, block_no, 種別)。block_no が None なら観測所表から（c10_jma.py の PREC）
        "jma_stations": ((46, None, "all"),),
        # c10: 月別値の対象地点と、日別値（地点・source_id・(年, 開始月, 終了月)・register の注記の頭）
        "jma_targets": ("横浜", "海老名", "辻堂", "小田原", "丹沢湖", "相模湖", "三浦"),
        "jma_daily": {"station": "横浜", "source_id": "jma_daily_yokohama",
                      "periods": ((2024, 1, 12), (2025, 1, 12), (2026, 1, 12)),
                      "note": "2024-01〜直近月の日別値"},
        # c80: 現存植生図2024 のブロックレイヤ（id, 名称）と、地域ブロックフィールドの注記
        "vg_layer": (2, "関東"),
        "vg_block_note": ("対応していない可能性がある(layer2=関東で取得したのに地域ブロック='3'の行が多数を占めた"
                          "実測結果あり)。"),
        # c65: カテゴリごとの注意書き（register の notes に足す）
        "osm_extra_notes": {
            "protected_area": (
                "注意: 神奈川県内でleisure=nature_reserve/boundary=protected_areaが付与されたOSM地物は17件のみで、"
                "実在の保護区（自然環境保全地域・鳥獣保護区等）を網羅していない。OSMのタグ付与状況に依存するため、"
                "保護区の網羅的分析には国土数値情報等の公的データを使うこと。"
            ),
        },
        "jma_sst_area_names": (),
        "jma_sst_label": "",
        # c30: W12 の register notes に足すデータの癖
        "w12_note": ("shapefile 5件(#15,#49,#116,#153,#158)は外環リングを持たず内側リングのみで構成されており、"
                     "pyshp が外環として符号化した（面積は算出済みだが形状の解釈に注意）。"),
        "env_water_prefcodes": ("14",),
        "l03b_meshes": ("5238", "5239", "5338", "5339"),
        "nlni_pref_codes": ("14",),
        "estat_pref_codes": ("14",),
    },
    "jp-46": {
        "slug": "amami",
        "bbox": (129.1, 27.95, 129.85, 28.8),
        "soramame_stations": (("46225010", "奄美（奄美市名瀬浦上町）"),),
        "jma_sst_areas": (617, 618, 619, 620),
        "name_ja": "鹿児島県（奄美大島）",
        "label": "奄美大島",
        "pref_code": "46",
        "pref_name_ja": "鹿児島県",
        # 奄美市・大和村・宇検村・瀬戸内町・龍郷町
        "muni_codes": ("46222", "46523", "46524", "46525", "46527"),
        # GADM level2: 奄美市=JPN.18.4 / 龍郷町=.38 / 宇検村=.41 / 大和村=.44 / 瀬戸内町=.34
        "gbif_gadm_gids": ("JPN.18.4_1", "JPN.18.38_1", "JPN.18.41_1", "JPN.18.44_1", "JPN.18.34_1"),
        # iNaturalist: 奄美市=34051 / 瀬戸内町=34081 / 龍郷町=34085 / 大和村=34091 / 宇検村=34088
        "inat_place_ids": (34051, 34081, 34085, 34091, 34088),
        # 名瀬（官署 s1）・笠利（アメダス a1）・古仁屋（アメダス a1）。prec_no=88 は鹿児島県（奄美地方）
        "jma_stations": ((88, "47909", "s1"), (88, "1520", "a1"), (88, "0980", "a1")),
        "jma_targets": ("名瀬", "笠利", "古仁屋"),
        # 名瀬の日別: 2010年奄美豪雨（2010-10）＋ 横浜と同じ直近2年
        "jma_daily": {"station": "名瀬", "source_id": "jma_daily_nase",
                      "periods": ((2010, 10, 10), (2024, 1, 12), (2025, 1, 12), (2026, 1, 12)),
                      "note": "2010-10（奄美豪雨）と 2024-01〜直近月の日別値"},
        "vg_layer": (7, "九州・沖縄"),
        "vg_block_note": "対応は未確認。",
        "osm_extra_notes": {},
        "w12_note": "",
        "jma_sst_label": "奄美群島",      # 海域617〜620 は群島の沿岸（島名ではない）
        "jma_sst_area_names": ((617, "奄美群島沿岸北西部"), (618, "奄美群島沿岸南西部"),
                               (619, "奄美群島沿岸南東部"), (620, "奄美群島沿岸北東部")),
        "env_water_prefcodes": ("46",),
        # 4229 が奄美大島本島。bbox と C23 の海岸線が掛かる 4129（与路島南端）・4329（島の北端）も要る
        "l03b_meshes": ("4129", "4229", "4329"),
        "nlni_pref_codes": ("46",),
        "estat_pref_codes": ("46",),
    },
}


def add_region_arg(parser) -> None:
    """`--region`（既定 jp-14、REGIONS の鍵だけ）を足す。"""
    parser.add_argument("--region", default="jp-14", choices=sorted(REGIONS))


def get(rid: str) -> dict:
    return REGIONS[rid]


def clip_bbox(rid: str):
    """県の一部だけを対象にする地域（muni_codes がある）の bbox。県全域の地域は None（絞らない）。
    絞り込むかどうかの判定は、地域 ID の比較ではなくこれ1つで行う。"""
    r = REGIONS[rid]
    return r["bbox"] if r["muni_codes"] is not None else None


def in_bbox(bbox, lat, lon) -> bool:
    """(lon_min, lat_min, lon_max, lat_max) の矩形に点が入るか。欠損は False。"""
    return (lat is not None and lon is not None
            and bbox[1] <= lat <= bbox[3] and bbox[0] <= lon <= bbox[2])


def name(base: str, rid: str) -> str:
    """出力名・source_id・raw パスを地域別にする。`kanagawa` を含めば slug に置換、
    含まなければ jp-14 はそのまま・他は `_<slug>` を末尾に付ける。"""
    slug = REGIONS[rid]["slug"]
    if "kanagawa" in base:
        return base.replace("kanagawa", slug)
    return base if rid == "jp-14" else f"{base}_{slug}"


def region_of_source_id(source_id: str) -> str | None:
    """出典名（source_id・出力名）から地域を引く。未知は None（既定は呼び手が決める）。
    規則は `name()` と同じ: 名前に slug が単語（`_` 区切り）として入っていればその地域。
    それで引けない例外（日別値の source_id: `jma_daily_nase` 等）は REGIONS の `jma_daily` から引く。"""
    tokens = set(re.split(r"_+", source_id or ""))
    for rid, r in REGIONS.items():
        if r["slug"] in tokens or r["jma_daily"]["source_id"] == source_id:
            return rid
    return None


def w12_stems() -> list[str]:
    """全地域の W12（流域界）の名前を REGIONS の順に返す。"""
    return [name("nlni_w12_watersheds", rid) for rid in REGIONS]


def site_scope(prefix: str) -> str:
    """site の出典接頭辞（例: `jma_stations_amami`・`jma_sst_amami__617`）→ ID の scope（region_id）。
    slug を含まない接頭辞は、神奈川の既存 ID を変えないため jp-14。"""
    return region_of_source_id(prefix) or "jp-14"
