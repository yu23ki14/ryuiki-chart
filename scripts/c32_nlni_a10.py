"""国土数値情報 A10 自然公園地域（神奈川県 14, 平成27/2015年）→ GeoJSON/CSV/JSONL

3つの shapefile はレイヤ番号で区別される（ダウンロードページ「属性情報」原文）:
  下2けた 11 = 自然公園地域 / 12 = 特別地域 / 13 = 特別保護地区
※原データ(shapefile/GML とも)に「国定公園名」等の公園名称は含まれない（OBJ_NAME は全件空）。
  推測で丹沢大山国定公園等を割り当てることはしない。市町村名 CTV_NAME を原文のまま残す。
"""
import sys, pathlib, glob, collections
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import RAW, register, write_jsonl, to_fiscal_year, to_number
from nlni_lib import (read_shp, geod_area_km2, write_geojson, write_csv,
                      extract_attribute_table, write_columns_csv, LICENSE_NONCOM,
                      assign_watershed)
from shapely.geometry import shape as shp_shape

SID = "nlni_a10_natparks"
PAGE = "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A10-v3_1.html"
ZIPU = "https://nlftp.mlit.go.jp/ksj/gml/data/A10/A10-15/A10-15_14_GML.zip"
BASE = RAW / SID

LAYER = {11: "自然公園地域", 12: "特別地域", 13: "特別保護地区"}
IOSIDE = {0: "毛羽無し", 1: "内向き", 2: "外向き"}

feats, rows = [], []
for shp in sorted(glob.glob(str(BASE / "*.shp"))):
    r, fields, recs, enc = read_shp(shp)
    print(f"{pathlib.Path(shp).name}: {len(recs)} features enc={enc}")
    for i, (sh, rc) in enumerate(zip(r.shapes(), recs)):
        gj = sh.__geo_interface__
        g = shp_shape(gj)
        if not g.is_valid:
            g = g.buffer(0)
        d = dict(zip(fields, rc))
        layer = int(d["LAYER_NO"])
        size_raw = d.get("AREA_SIZE")
        size_val, _ = to_number(size_raw)
        c = g.centroid
        props = {
            "source_id": SID,
            "source_ref": f"{ZIPU}#{pathlib.Path(shp).name}:{i}",
            "object_id": d.get("OBJECTID"),
            "prefecture_code": str(d.get("PREFEC_CD")).zfill(2),
            "prefecture_name_ja": "神奈川県",
            "subprefecture_code": str(d.get("AREA_CD")),
            "municipality_names_ja": d.get("CTV_NAME") or "",
            "fiscal_year_raw": d.get("FIS_YEAR"),
            "fiscal_year": to_fiscal_year(d.get("FIS_YEAR")),
            "thema_no": d.get("THEMA_NO"),
            "layer_no": layer,
            "layer_name_ja": LAYER.get(layer),
            "object_name_ja": d.get("OBJ_NAME") or None,
            "area_size_ha_raw": size_raw,
            "area_size_ha": size_val,
            "ioside_code_raw": d.get("IOSIDE_DIV"),
            "ioside_ja": IOSIDE.get(int(d.get("IOSIDE_DIV") or 0)),
            "remark_ja": d.get("REMARK_STR") or "",
            "shape_length_deg": d.get("Shape_Leng"),
            "shape_area_deg2": d.get("Shape_Area"),
            "area_km2": geod_area_km2(g),
            "centroid_lat": round(c.y, 6),
            "centroid_lon": round(c.x, 6),
            "data_year": 2015,
        }
        props.update(assign_watershed(g))
        feats.append({"type": "Feature", "geometry": gj, "properties": props})
        rows.append(props)

write_geojson(SID, feats, crs_note="原データ .prj = JGD2000。WGS84(EPSG:4326)として出力。")
write_csv(SID, rows)
write_jsonl(SID, rows)

cols = extract_attribute_table(RAW / "nlni_pages" / "A10.html")
mapping = {"PREFEC_CD": "prefecture_code", "AREA_CD": "subprefecture_code",
           "CTV_NAME": "municipality_names_ja", "FIS_YEAR": "fiscal_year_raw / fiscal_year",
           "THEMA_NO": "thema_no", "LAYER_NO": "layer_no / layer_name_ja",
           "OBJ_NAME": "object_name_ja", "AREA_SIZE": "area_size_ha_raw / area_size_ha",
           "IOSIDE_DIV": "ioside_code_raw / ioside_ja", "REMARK_STR": "remark_ja"}
for c in cols:
    c["output_column"] = mapping.get(c["column_code"], "")
cols += [
    {"column_code": "OBJECTID", "column_name_ja": "オブジェクトID",
     "description_ja": "shapefile 固有の連番（ダウンロードページの属性表には記載なし）。",
     "type_ja": "整数", "output_column": "object_id"},
    {"column_code": "Shape_Leng", "column_name_ja": "周長(度)",
     "description_ja": "shapefile 固有。緯度経度そのままの平面周長（単位=度）。距離としては使えない。",
     "type_ja": "実数", "output_column": "shape_length_deg"},
    {"column_code": "Shape_Area", "column_name_ja": "面積(度^2)",
     "description_ja": "shapefile 固有。緯度経度そのままの平面面積（単位=度^2）。面積としては使えない。",
     "type_ja": "実数", "output_column": "shape_area_deg2"},
    {"column_code": "", "column_name_ja": "面積(km2)",
     "description_ja": "本収集で算出。pyproj.Geod(ellps=WGS84).geometry_area_perimeter による測地線多角形面積を km2 換算。",
     "type_ja": "実数", "output_column": "area_km2"},
    {"column_code": "", "column_name_ja": "所属単位流域",
     "description_ja": "本収集で付与。ポリゴン重心が W12 流域界(神奈川, 昭和52年)のどの単位流域内にあるかで判定。外れる場合は null。大きな面ほど重心1点での代表性は落ちる点に注意。",
     "type_ja": "文字列", "output_column": "watershed_id / water_system_code_old / water_system_name_ja_estimated"},
    {"column_code": "", "column_name_ja": "レイヤ番号の意味",
     "description_ja": "ダウンロードページ属性情報の原文「（自然公園地域 下2けた 11）（特別地域 下2けた 12）（特別保護地区 下2けた 13）」より。",
     "type_ja": "文字列", "output_column": "layer_name_ja"},
]
write_columns_csv(SID, cols)

by_layer = collections.Counter(p["layer_name_ja"] for p in rows)
area_by_layer = collections.Counter()
for p in rows:
    area_by_layer[p["layer_name_ja"]] += p["area_km2"] or 0
summary = " / ".join(f"{k}:{v}件 {area_by_layer[k]:.1f}km2" for k, v in by_layer.items())
print("  " + summary)

register(SID, "国土数値情報 自然公園地域（神奈川県）", "国土交通省 国土数値情報ダウンロードサイト",
         PAGE, "gis_protected_area", "http_zip_shapefile", "geojson+csv+jsonl",
         LICENSE_NONCOM, 1, len(rows),
         "神奈川県(14) A10-15_14_GML.zip / 平成27(2015)年度版(第4.1版)。"
         f"レイヤ内訳: {summary}。"
         "※原データに公園名称（丹沢大山国定公園等）は含まれない（OBJ_NAME は全件空、GML の naturalParkCode も 1/2/3 のみ）。"
         "推測で公園名を付与していない。AREA_SIZE(ha) も原データでは全件 0.0。"
         "ダウンロードページ原文注記: 「本データにおける細区分（「特別地域」及び「特別保護地区」）のデータは、"
         "土地利用基本計画においても参考表示の扱いであり、精度は保証できません。」"
         "FIS_YEAR は市町村ごとに 2002/2011 等が混在（各ポリゴンの原典作成年度）。使用許諾条件は「非商用」。")
