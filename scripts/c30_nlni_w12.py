"""国土数値情報 W12 流域界・非集水域（神奈川県 14, 昭和52/1977年）→ GeoJSON/CSV/JSONL

流域名について:
  W12 の属性は「旧水系域コード(5桁)」のみで、公式コードリスト OldWaterSystemCd には
  コード体系の説明しか無く、水系名の対応表が存在しない（製品仕様書 KS-PS-W12-v1_1.pdf 付録も同様）。
  そこで **推定列** として、同じ国土数値情報の W05 河川（神奈川, 平成20年）の流路を
  各流域ポリゴンで空間クロスさせ、ポリゴン内合計延長が最大の「水系域コード(6桁, 新)」を
  コードリスト WaterSystemCodeCd で名称化したものを `*_estimated` 列に入れる。
  推定であることが判る列名・estimate_method 列を必ず付け、原コードは無加工で残す。
"""
import sys, pathlib, collections
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import RAW, PROC, register, write_jsonl, to_fiscal_year
from nlni_lib import (read_shp, geod_area_km2, write_geojson, write_csv,
                      extract_attribute_table, write_columns_csv, parse_codelist_html,
                      LICENSE_OPEN)
from shapely.geometry import shape as shp_shape
from shapely.strtree import STRtree
from shapely import prepared

SID = "nlni_w12_watersheds"
PAGE = "https://nlftp.mlit.go.jp/ksj/gmlold/datalist/gmlold_KsjTmplt-W12.html"
ZIPU = "https://nlftp.mlit.go.jp/ksj/gmlold/data/W12/W12-52A/W12-52A-14-01.0a_GML.zip"
SHP = RAW / SID / "W12-52A-2K-14_WatershedBoundary.shp"
W05_SHP = RAW / "nlni_w05_rivers" / "W05-08_14-g_Stream.shp"

WATERSHED_TYPE = {"0": "流域界", "1": "非集水域界"}

# 公式コードリスト OldWaterSystemCd（旧水系域コード）より
BUREAU = {"81": "北海道開発局", "82": "東北地方建設局", "83": "関東地方建設局",
          "84": "北陸地方建設局", "85": "中部地方建設局", "86": "近畿地方建設局",
          "87": "中国地方建設局", "88": "四国地方建設局", "89": "九州地方建設局",
          "90": "沖縄開発局"}


def ws_category(code):
    """旧水系域コード下3桁の設定基準（OldWaterSystemCd 原文）"""
    try:
        n = int(str(code)[2:5])
    except Exception:
        return None
    if n == 0:
        return "対象外地域"
    if 1 <= n <= 199:
        return "一級河川を含む単一水系域"
    if 201 <= n <= 499:
        return "主要二級河川を含む単一水系域"
    if 501 <= n <= 949:
        return "複合水系域"
    if 951 <= n <= 999:
        return "流出口のない水系域"
    return None

# ---- 読み込み ----
r, fields, recs, enc = read_shp(SHP)
shapes = r.shapes()
print(f"W12: {len(recs)} features, fields={fields}, dbf encoding={enc}")

# ---- W05 河川で水系名を推定 ----
ws_names = parse_codelist_html(RAW / "nlni_codelists" / "WaterSystemCodeCd.html", r"\d{6}")
r5, f5, rec5, enc5 = read_shp(W05_SHP)
streams = []
for sh, rc in zip(r5.shapes(), rec5):
    g = shp_shape(sh.__geo_interface__)
    if g.is_empty:
        continue
    streams.append((g, rc[0], rc[3]))   # geom, W05_001 水系域コード, W05_004 河川名
tree = STRtree([s[0] for s in streams])
print(f"W05 streams for naming: {len(streams)}")

features, rows = [], []
for i, (sh, rc) in enumerate(zip(shapes, recs)):
    gj = sh.__geo_interface__
    g = shp_shape(gj)
    if not g.is_valid:
        g = g.buffer(0)
    ws_code, uv_code, wtype = rc[1], rc[2], str(rc[0])
    area = geod_area_km2(g)
    c = g.centroid

    by_sys, by_river = collections.Counter(), collections.Counter()
    for idx in tree.query(g):
        sg, scode, sname = streams[int(idx)]
        try:
            inter = sg.intersection(g)
        except Exception:
            continue
        if inter.is_empty:
            continue
        ln = inter.length
        if ln <= 0:
            continue
        by_sys[scode] += ln
        by_river[sname] += ln
    est_code = by_sys.most_common(1)[0][0] if by_sys else None
    est_name = ws_names.get(est_code) if est_code else None
    tot = sum(by_sys.values())
    est_share = round(by_sys[est_code] / tot, 4) if tot else None
    # 妥当性チェック: 一級水系域(旧コード上2桁=管轄地建番号)には 6桁新コードも同じ地建番号が付く。
    # 一致しない場合は推定を信用しない（例: 85045 は中部地建の一級水系だが関東側の二級河川に当たってしまう）。
    cat = ws_category(ws_code)
    if not est_code:
        est_flag = "no_stream_matched"
    elif cat == "一級河川を含む単一水系域" and est_code[:2] != str(ws_code)[:2]:
        est_flag = "bureau_mismatch"
    else:
        est_flag = "ok"
    if est_flag != "ok":
        est_name = None
    rivers = "|".join(n for n, _ in by_river.most_common(5) if n and n != "名称不明")

    props = {
        "source_id": SID,
        "source_ref": f"{ZIPU}#W12-52A-2K-14_WatershedBoundary:{i}",
        "watershed_id": f"{ws_code}-{uv_code}",
        "watershed_type_code_raw": wtype,
        "watershed_type_ja": WATERSHED_TYPE.get(wtype),
        "water_system_code_old": ws_code,
        "unit_valley_code": uv_code,
        "area_km2": area,
        "centroid_lat": round(c.y, 6),
        "centroid_lon": round(c.x, 6),
        "water_system_bureau_ja": BUREAU.get(str(ws_code)[:2]),
        "water_system_category_ja": cat,
        "water_system_code_w05_estimated": est_code,
        "water_system_name_ja_estimated": est_name,
        "estimate_share": est_share,
        "estimate_matched_streams": len(by_sys),
        "estimate_flag": est_flag,
        "main_river_names_ja": rivers,
        "estimate_method": ("W05河川(神奈川,平成20年)の流路を当ポリゴンで交差させ、"
                            "交差延長最大の水系域コードをWaterSystemCodeCdで名称化した推定値"),
        "data_year": to_fiscal_year("昭和52年"),
        "prefecture_code": "14",
        "prefecture_name_ja": "神奈川県",
    }
    features.append({"type": "Feature", "geometry": gj, "properties": props})
    rows.append(props)

write_geojson(SID, features,
              crs_note="原データ座標系 JGD2000/(B,L)。WGS84(EPSG:4326)としてそのまま出力（差は数cm）。")
write_csv(SID, rows)
write_jsonl(SID, rows)

# ---- 水系域単位の集計（流域単位で束ねる用） ----
agg = {}
for p in rows:
    k = p["water_system_code_old"]
    a = agg.setdefault(k, {"water_system_code_old": k, "n_unit_watersheds": 0,
                           "area_km2": 0.0, "names": collections.Counter(),
                           "rivers": collections.Counter()})
    a.setdefault("category", p["water_system_category_ja"])
    a.setdefault("bureau", p["water_system_bureau_ja"])
    a["n_unit_watersheds"] += 1
    a["area_km2"] += p["area_km2"] or 0
    if p["water_system_name_ja_estimated"]:
        a["names"][p["water_system_name_ja_estimated"]] += p["area_km2"] or 0
    for rn in (p["main_river_names_ja"] or "").split("|"):
        if rn:
            a["rivers"][rn] += 1
agg_rows = []
for k, a in sorted(agg.items()):
    agg_rows.append({
        "source_id": SID + "_by_system",
        "source_ref": f"{ZIPU}#water_system_code_old={k}",
        "water_system_code_old": k,
        "water_system_bureau_ja": a["bureau"],
        "water_system_category_ja": a["category"],
        "n_unit_watersheds": a["n_unit_watersheds"],
        "area_km2": round(a["area_km2"], 4),
        "water_system_name_ja_estimated": (
            None if a["category"] == "複合水系域"
            else (a["names"].most_common(1)[0][0] if a["names"] else None)),
        "name_candidates_ja": "|".join(f"{n}:{round(v,1)}km2" for n, v in a["names"].most_common()),
        "main_river_names_ja": "|".join(n for n, _ in a["rivers"].most_common(8)),
        "note": ("複合水系域のため単一の水系名は与えない（name_candidates_ja を参照）"
                 if a["category"] == "複合水系域"
                 else ("W05河川の水系域コードと管轄地建番号が一致せず水系名を確定できない"
                       "（estimate_flag=bureau_mismatch）" if not a["names"] else "")),
        "data_year": 1977,
    })
write_csv(SID + "_by_system", agg_rows)
write_jsonl(SID + "_by_system", agg_rows)

# ---- 属性対応表 ----
cols = extract_attribute_table(RAW / "nlni_pages" / "W12.html")
for c in cols:
    c["output_column"] = {"W12_001": "watershed_type_code_raw / watershed_type_ja",
                          "W12_002": "water_system_code_old",
                          "W12_003": "unit_valley_code"}.get(c["column_code"], "")
cols += [
    {"column_code": "", "column_name_ja": "面積(km2)",
     "description_ja": "本収集で算出。pyproj.Geod(ellps=WGS84).geometry_area_perimeter による測地線多角形面積を km2 換算（原データに面積属性は無い）。",
     "type_ja": "実数", "output_column": "area_km2"},
    {"column_code": "", "column_name_ja": "重心緯度・経度",
     "description_ja": "本収集で算出。shapely centroid（平面近似）。", "type_ja": "実数",
     "output_column": "centroid_lat / centroid_lon"},
    {"column_code": "", "column_name_ja": "推定水系名",
     "description_ja": "本収集で推定。W05河川の流路とポリゴンの交差延長が最大の水系域コード(6桁)を WaterSystemCodeCd で名称化。原データには水系名は含まれない。",
     "type_ja": "文字列", "output_column": "water_system_name_ja_estimated / water_system_code_w05_estimated"},
    {"column_code": "", "column_name_ja": "推定の確からしさ",
     "description_ja": "本収集で算出。ポリゴン内で交差した全流路延長のうち採用した水系域コードが占める割合。1.0なら単一水系のみ。",
     "type_ja": "実数", "output_column": "estimate_share / estimate_matched_streams / estimate_flag"},
    {"column_code": "", "column_name_ja": "推定の妥当性フラグ",
     "description_ja": "ok=採用 / bureau_mismatch=旧コードの管轄地建番号と推定新コードの上2桁が不一致のため水系名を付けない / no_stream_matched=ポリゴン内にW05流路が無い。",
     "type_ja": "文字列", "output_column": "estimate_flag"},
    {"column_code": "", "column_name_ja": "管轄地建・水系域区分",
     "description_ja": "旧水系域コード上2桁(管轄地建番号)と下3桁の設定基準を公式コードリスト OldWaterSystemCd の記述どおり展開したもの。",
     "type_ja": "文字列", "output_column": "water_system_bureau_ja / water_system_category_ja"},
    {"column_code": "", "column_name_ja": "単位流域ID",
     "description_ja": "本収集で作成。水系域コード + '-' + 単位流域コード。", "type_ja": "文字列",
     "output_column": "watershed_id"},
]
write_columns_csv(SID, cols)

NOTES = ("神奈川県(14)/世界測地系版 W12-52A-14-01.0a_GML.zip。基準年 昭和52(1977)年。"
         "原データに水系名は無く旧水系域コード(5桁)のみ。公式コードリスト OldWaterSystemCd には"
         "名称対応表が存在しないため、水系名は W05河川との空間クロスによる推定値を "
         "*_estimated 列に格納（estimate_method 列に方法を明記）。"
         "面積は pyproj.Geod の測地線多角形面積(WGS84)を km2 換算。"
         "ダウンロードページ原文注記: 「※本データには出典不明・年度不明のデータが含まれており、"
         "データの一部は領域外にあるものがあるため、利用には注意を要する。」"
         "「旧フォーマットに記録されていた”非集水域界”のデータについては、幾何形状に課題があったため"
         "GML変換時に削除した。」→ 実際に watershed_type は全件 0(流域界) で非集水域界は0件。"
         "shapefile 5件(#15,#49,#116,#153,#158)は外環リングを持たず内側リングのみで構成されており、"
         "pyshp が外環として符号化した（面積は算出済みだが形状の解釈に注意）。"
         f"付随出力: {SID}_by_system.csv/.jsonl（旧水系域コード単位の集計）, {SID}_columns.csv")
register(SID, "国土数値情報 流域界・非集水域（神奈川県）", "国土交通省 国土数値情報ダウンロードサイト",
         PAGE, "gis_watershed", "http_zip_shapefile", "geojson+csv+jsonl",
         LICENSE_OPEN, 1, len(rows), NOTES)

# ---- 目視確認 ----
print("\n=== 旧水系域コード別 集計（相模川水系の確認） ===")
for a in agg_rows:
    print(f"  {a['water_system_code_old']}  n={a['n_unit_watersheds']:3d}  "
          f"{a['area_km2']:9.2f} km2  {a['water_system_category_ja']}  "
          f"推定={a['water_system_name_ja_estimated']}  候補={a['name_candidates_ja'][:70]}")
