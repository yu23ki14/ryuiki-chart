"""国土数値情報 A45 森林地域（国有林小班・神奈川県 14, 2018年）→ GeoJSON/CSV/JSONL"""
import sys, pathlib, re, html, collections
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import RAW, register, write_jsonl, to_number
from nlni_lib import (read_shp, geod_area_km2, write_geojson, write_csv,
                      extract_attribute_table, write_columns_csv, assign_watershed)
from shapely.geometry import shape as shp_shape

SID = "nlni_a45_forest"
PAGE = "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A45.html"
ZIPU = "https://nlftp.mlit.go.jp/ksj/gml/data/A45/A45-19/A45-19_14_GML.zip"
LICENSE = ("オープンデータ（CC BY 4.0）／国土数値情報利用約款。"
           "ダウンロードページ原文「適用する利用規約に基づく（オープンデータ）」"
           " https://nlftp.mlit.go.jp/ksj/other/agreement.html")


def codelist_pairs(name):
    """コード/内容 が1行に複数組並ぶ形式にも対応した コードリスト読み取り"""
    h = (RAW / "nlni_codelists" / f"{name}.html").read_text(encoding="utf-8")
    out = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S):
        c = [html.unescape(re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", x)))
             for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(c) >= 2 and c[0] == "コード":
            continue
        for i in range(0, len(c) - 1, 2):
            k, v = c[i], c[i + 1]
            if k and v and k != "コード":
                out.setdefault(k, v)
    return out


CL = {n: codelist_pairs(n) for n in
      ("hoanrinCd", "hogorinCd", "jushuCd", "kinouruikeiCd", "midorinokairoCd",
       "rinshunosaibunCd", "shinrinkanriCd", "shouhanshubanCd")}
print("codelists:", {k: len(v) for k, v in CL.items()})

FIELD = {  # A45_xxx -> (英字列名, 日本語属性名, 参照コードリスト)
    "A45_001": ("subcompartment_id", "小班ID", None),
    "A45_002": ("forest_bureau_code", "森林管理局コード", "shinrinkanriCd"),
    "A45_003": ("forest_office_code", "森林管理署コード", "shinrinkanriCd"),
    "A45_004": ("compartment_no", "林班主番", None),
    "A45_005": ("compartment_branch_no", "林班枝番", None),
    "A45_006": ("subcompartment_no", "小班主番", "shouhanshubanCd"),
    "A45_007": ("subcompartment_branch_no", "小班枝番", None),
    "A45_008": ("forest_bureau_name_ja", "局名称", None),
    "A45_009": ("forest_office_name_ja", "署名称", None),
    "A45_010": ("subcompartment_name_ja", "小班名称", None),
    "A45_011": ("compartment_label_ja", "林小班名称", None),
    "A45_012": ("timber_volume_m3", "材積(m3)", None),
    "A45_013": ("national_forest_name_ja", "国有林名称", None),
    "A45_014": ("municipality_name_ja", "県市町村名称", None),
    "A45_015": ("species1_ja", "樹種1", "jushuCd"),
    "A45_016": ("species1_age", "樹種1林齢", None),
    "A45_017": ("species1_age_adj", "樹種1林齢(加算)", None),
    "A45_018": ("species2_ja", "樹種2", "jushuCd"),
    "A45_019": ("species2_age", "樹種2林齢", None),
    "A45_020": ("species2_age_adj", "樹種2林齢(加算)", None),
    "A45_021": ("species3_ja", "樹種3", "jushuCd"),
    "A45_022": ("species3_age", "樹種3林齢", None),
    "A45_023": ("species3_age_adj", "樹種3林齢(加算)", None),
    "A45_024": ("plan_area_name_ja", "計画区名称", None),
    "A45_025": ("forest_subtype_ja", "林種の細分", "rinshunosaibunCd"),
    "A45_026": ("function_type_ja", "機能類型", "kinouruikeiCd"),
    "A45_027": ("area_ha_source", "面積(ha, 原データ)", None),
    "A45_028": ("protection_forest1_ja", "保安林1", "hoanrinCd"),
    "A45_029": ("protection_forest2_ja", "保安林2", "hoanrinCd"),
    "A45_030": ("protection_forest3_ja", "保安林3", "hoanrinCd"),
    "A45_031": ("protection_forest4_ja", "保安林4", "hoanrinCd"),
    "A45_032": ("protected_forest_ja", "保護林", "hogorinCd"),
    "A45_033": ("green_corridor_ja", "緑の回廊", "midorinokairoCd"),
}

r, fields, recs, enc = read_shp(RAW / SID / "A45-19_14")
print(f"A45: {len(recs)} features enc={enc}")
feats, rows = [], []
for i, (sh, rc) in enumerate(zip(r.shapes(), recs)):
    gj = sh.__geo_interface__
    g = shp_shape(gj)
    if not g.is_valid:
        g = g.buffer(0)
    d = dict(zip(fields, rc))
    props = {"source_id": SID, "source_ref": f"{ZIPU}#A45-19_14:{i}"}
    for code, (col, ja, cl) in FIELD.items():
        v = d.get(code)
        v = v.strip() if isinstance(v, str) else v
        props[col] = v if v not in ("", None) else None
        if cl:
            # 原データは略号（例 水涵保）。コードリストで正式名称に展開した列を _full で持つ
            props[col + "_full"] = CL[cl].get(v) if v else None
    props["area_ha_source"], _ = to_number(props["area_ha_source"])
    props["area_km2"] = geod_area_km2(g)
    props["centroid_lat"] = round(g.centroid.y, 6)
    props["centroid_lon"] = round(g.centroid.x, 6)
    props.update(assign_watershed(g))
    props["data_year"] = 2018
    props["prefecture_code"] = "14"
    props["prefecture_name_ja"] = "神奈川県"
    feats.append({"type": "Feature", "geometry": gj, "properties": props})
    rows.append(props)

write_geojson(SID, feats, crs_note="原データ座標系 JGD2011/(B,L)。WGS84(EPSG:4326)として出力。")
write_csv(SID, rows)
write_jsonl(SID, rows)

cols = extract_attribute_table(RAW / "nlni_pages" / "A45.html")
for c in cols:
    m = FIELD.get(c["column_code"])
    c["output_column"] = (m[0] + (" / " + m[0] + "_full" if m[2] else "")) if m else ""
cols += [
    {"column_code": "", "column_name_ja": "面積(km2)",
     "description_ja": "本収集で算出。pyproj.Geod(ellps=WGS84) 測地線多角形面積を km2 換算。原データの面積(ha) A45_027 は area_ha_source に別途保持。",
     "type_ja": "実数", "output_column": "area_km2"},
    {"column_code": "", "column_name_ja": "コードリスト展開列",
     "description_ja": "原データの略号（例: 水涵保, 天, 自然維持, 丹沢緑）を各コードリスト(hoanrinCd/rinshunosaibunCd/kinouruikeiCd/midorinokairoCd/jushuCd/hogorinCd)で正式名称に展開したもの。展開できない値は null。",
     "type_ja": "文字列", "output_column": "*_full"},
    {"column_code": "", "column_name_ja": "所属単位流域",
     "description_ja": "本収集で付与。小班ポリゴンの重心が W12 流域界(神奈川, 昭和52年)のどの単位流域内にあるかで判定。外れる場合は null。",
     "type_ja": "文字列", "output_column": "watershed_id / water_system_code_old / water_system_name_ja_estimated"},
]
write_columns_csv(SID, cols)

by_ws = collections.Counter()
for p in rows:
    by_ws[p["water_system_name_ja_estimated"] or "未割当"] += p["area_km2"] or 0
summ = " / ".join(f"{k}:{v:.1f}km2" for k, v in by_ws.most_common())
print("  流域別: " + summ)
unassigned = sum(1 for p in rows if not p["watershed_id"])

register(SID, "国土数値情報 森林地域（国有林小班・神奈川県）", "国土交通省 国土数値情報ダウンロードサイト",
         PAGE, "gis_forest", "http_zip_shapefile", "geojson+csv+jsonl", LICENSE, 1, len(rows),
         "神奈川県(14) A45-19_14_GML.zip / 2018年(平成30年)。国有林の小班ポリゴン。座標系 JGD2011。"
         "属性は略号（水涵保=水源かん養保安林 等）で格納されているため、各コードリストで展開した *_full 列を追加。"
         f"W12単位流域を重心で割り当て（未割当 {unassigned} 件）。流域別面積: {summ}。"
         "ダウンロードページ原文注記: 「本製品を複製する場合には、国土地理院の長の承認を得なければなりません。」"
         "※本データは国有林のみで、民有林（神奈川県の森林の大半）は含まれない。")
