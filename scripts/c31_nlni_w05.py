"""国土数値情報 W05 河川（神奈川県 14, 平成20/2008年）→ GeoJSON/CSV/JSONL
Stream(流路・線) と RiverNode(河川端点・点) の2レイヤ。

`--region jp-46`（奄美）は鹿児島県 W05-07_46（平成19年。W05-08 に鹿児島は無い）を取り、奄美の bbox
（regions.py）に掛かる流路・端点だけを `nlni_w05_rivers_amami.*` / `nlni_w05_river_nodes_amami.*` に出す。
"""
import argparse, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import RAW, register, write_jsonl, to_fiscal_year
from nlni_lib import (read_shp, geod_length_km, write_geojson, write_csv,
                      extract_attribute_table, write_columns_csv, parse_codelist_html,
                      LICENSE_NONCOM, layout, ensure_extracted, bbox_geom)
from regions import add_region_arg
from shapely.geometry import shape as shp_shape

ap = argparse.ArgumentParser()
add_region_arg(ap)
RID = ap.parse_args().region
L = layout(RID)

PAGE = "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-W05.html"
ZIPU = L["w05_zip_url"]
BASE = L["w05_dir"]
PREF, PREF_NAME, YEAR_JA = L["pref"], L["pref_name_ja"], L["w05_year_ja"]
YEAR_NOTE = {"14": "平成20(2008)年", "46": "平成19(2007)年"}[PREF]
if RID != "jp-14":
    ensure_extracted(ZIPU, BASE / pathlib.PurePosixPath(ZIPU).name, BASE,
                     L["w05_stream_stem"] + ".shp")
CLIP = bbox_geom(L["clip_bbox"]) if L["clip_bbox"] else None

SECTION = {"1": "1級直轄区間", "2": "1級指定区間", "3": "2級河川区間", "4": "指定区間外",
           "5": "1級直轄区間でかつ湖沼区間を兼ねる", "6": "1級指定区間でかつ湖沼区間を兼ねる",
           "7": "2級河川区間でかつ湖沼区間を兼ねる", "8": "指定区間外でかつ湖沼区間を兼ねる",
           "0": "不明"}

ws_names = parse_codelist_html(RAW / "nlni_codelists" / "WaterSystemCodeCd.html", r"\d{6}")
river_names = parse_codelist_html(RAW / "nlni_codelists" / "RiverCodeCd.html", r"\d{10}")
src_names = parse_codelist_html(RAW / "nlni_codelists" / "OriginalDataCodeCd.html", r"\d+")
print(f"codelists: watersystem={len(ws_names)} river={len(river_names)} origsrc={len(src_names)}")

# ================= Stream (流路) =================
SID = L["w05_sid"]
r, fields, recs, enc = read_shp(L["w05_stream_shp"])
print(f"W05 Stream: {len(recs)} features {fields} enc={enc}")
feats, rows = [], []
for i, (sh, rc) in enumerate(zip(r.shapes(), recs)):
    gj = sh.__geo_interface__
    g = shp_shape(gj)
    if CLIP is not None and not g.intersects(CLIP):
        continue
    d = dict(zip(fields, rc))
    props = {
        "source_id": SID,
        "source_ref": f"{ZIPU}#{L['w05_stream_stem']}:{i}",
        "water_system_code": d["W05_001"],
        "water_system_name_ja": ws_names.get(d["W05_001"]),
        "river_code": d["W05_002"],
        "river_code_name_ja": river_names.get(d["W05_002"]),
        "section_type_code_raw": str(d["W05_003"]),
        "section_type_ja": SECTION.get(str(d["W05_003"])),
        "river_name_ja": d["W05_004"],
        "original_source_code_raw": str(d["W05_005"]),
        "original_source_ja": src_names.get(str(d["W05_005"])),
        "flow_direction_known_raw": str(d["W05_006"]),
        "flow_direction_known": (str(d["W05_006"]) in ("1", "true", "True")),
        "start_node_ref": d["W05_007"],
        "end_node_ref": d["W05_008"],
        "stream_start_node_ref": d["W05_009"],
        "stream_end_node_ref": d["W05_010"],
        "length_km": geod_length_km(g),
        "centroid_lat": round(g.centroid.y, 6),
        "centroid_lon": round(g.centroid.x, 6),
        "data_year": to_fiscal_year(YEAR_JA),
        "prefecture_code": PREF,
        "prefecture_name_ja": PREF_NAME,
    }
    feats.append({"type": "Feature", "geometry": gj, "properties": props})
    rows.append(props)
write_geojson(SID, feats, crs_note="原データ座標系 JGD2000/(B,L)。WGS84(EPSG:4326)として出力。")
write_csv(SID, rows)
write_jsonl(SID, rows)

cols = extract_attribute_table(RAW / "nlni_pages" / "W05.html")
mapping = {"W05_001": "water_system_code / water_system_name_ja",
           "W05_002": "river_code / river_code_name_ja",
           "W05_003": "section_type_code_raw / section_type_ja",
           "W05_004": "river_name_ja", "W05_005": "original_source_code_raw / original_source_ja",
           "W05_006": "flow_direction_known_raw / flow_direction_known",
           "W05_007": "start_node_ref", "W05_008": "end_node_ref",
           "W05_009": "stream_start_node_ref", "W05_010": "stream_end_node_ref",
           "W05_011": "elevation_m"}
for c in cols:
    c["output_column"] = mapping.get(c["column_code"], "")
cols += [{"column_code": "", "column_name_ja": "流路延長(km)",
          "description_ja": "本収集で算出。pyproj.Geod(ellps=WGS84) による測地線長を km 換算（原データに延長属性は無い）。",
          "type_ja": "実数", "output_column": "length_km"},
         {"column_code": "", "column_name_ja": "重心緯度・経度",
          "description_ja": "本収集で算出。shapely centroid（平面近似）。", "type_ja": "実数",
          "output_column": "centroid_lat / centroid_lon"}]
write_columns_csv(SID, cols)

SCOPE = "" if CLIP is None else f"（{L['name_ja']}の範囲 bbox {L['bbox']} に掛かる流路だけ。県全体 {len(recs)} 本から絞った）"
register(SID, f"国土数値情報 河川（流路・{PREF_NAME if CLIP is None else L['name_ja']}）", "国土交通省 国土数値情報ダウンロードサイト",
         PAGE, "gis_river", "http_zip_shapefile", "geojson+csv+jsonl", LICENSE_NONCOM, 1, len(rows),
         f"{PREF_NAME}({PREF}) {pathlib.PurePosixPath(ZIPU).name} / {YEAR_NOTE}。Stream(流路,線)レイヤ。{SCOPE}"
         "水系名・河川名はコードリスト WaterSystemCodeCd / RiverCodeCd で名称化（原データの河川名 W05_004 も river_name_ja にそのまま保持）。"
         "延長は pyproj.Geod の測地線長。ダウンロードページの使用許諾条件は「非商用」。"
         f"属性対応表: {SID}_columns.csv")

# ================= RiverNode (河川端点) =================
SID2 = L["w05_nodes_sid"]
r2, f2, rec2, enc2 = read_shp(L["w05_node_shp"])
print(f"W05 RiverNode: {len(rec2)} features {f2} enc={enc2}")
feats2, rows2 = [], []
for i, (sh, rc) in enumerate(zip(r2.shapes(), rec2)):
    gj = sh.__geo_interface__
    d = dict(zip(f2, rc))
    lon, lat = gj["coordinates"][0], gj["coordinates"][1]
    if CLIP is not None and not (L["bbox"][0] <= lon <= L["bbox"][2] and L["bbox"][1] <= lat <= L["bbox"][3]):
        continue
    elev_raw = d.get("W05_011")
    try:
        elev = float(elev_raw)
    except Exception:
        elev = None
    props = {
        "source_id": SID2,
        "source_ref": f"{ZIPU}#{L['w05_node_stem']}:{i}",
        "node_id": d.get("W05_000"),
        "water_system_code": d.get("W05_001"),
        "water_system_name_ja": ws_names.get(d.get("W05_001")),
        "elevation_m_raw": elev_raw,
        "elevation_m": elev,
        "lat": round(lat, 8), "lon": round(lon, 8),
        "data_year": to_fiscal_year(YEAR_JA),
        "prefecture_code": PREF, "prefecture_name_ja": PREF_NAME,
    }
    feats2.append({"type": "Feature", "geometry": gj, "properties": props})
    rows2.append(props)
write_geojson(SID2, feats2, crs_note="原データ座標系 JGD2000/(B,L)。WGS84(EPSG:4326)として出力。")
write_csv(SID2, rows2)
write_jsonl(SID2, rows2)
write_columns_csv(SID2, [c for c in cols if c["column_code"] in ("W05_001", "W05_011")] + [
    {"column_code": "W05_000", "column_name_ja": "河川端点ID",
     "description_ja": "shapefile 上の河川端点識別子（流路の始点/終点参照 W05_007〜010 と対応）。",
     "type_ja": "文字列", "output_column": "node_id"},
    {"column_code": "", "column_name_ja": "緯度・経度", "description_ja": "点ジオメトリの座標。",
     "type_ja": "実数", "output_column": "lat / lon"}])
register(SID2, f"国土数値情報 河川（河川端点・{PREF_NAME if CLIP is None else L['name_ja']}）", "国土交通省 国土数値情報ダウンロードサイト",
         PAGE, "gis_river", "http_zip_shapefile", "geojson+csv+jsonl", LICENSE_NONCOM, 1, len(rows2),
         f"{PREF_NAME}({PREF}) {pathlib.PurePosixPath(ZIPU).name} / {YEAR_NOTE}。RiverNode(河川端点,点)レイヤ。{SCOPE}"
         "標高 W05_011 は「数値地図50mメッシュ（標高）」由来（ダウンロードページ記載）。"
         "使用許諾条件は「非商用」。")
