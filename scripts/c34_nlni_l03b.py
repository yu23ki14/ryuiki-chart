"""国土数値情報 L03-b 土地利用細分メッシュ（100mメッシュ）神奈川県域 2006/2016 → GeoJSON/CSV/JSONL

- 1次メッシュ 5238/5239/5338/5339（神奈川県を覆う4枚）の JGD2000 版を取得。
- ZIP 内の .shp は 1枚 85MB あるが、100mメッシュのセル形状は **メッシュコードから一意に決まる**ため
  .dbf のみを展開し、セル矩形はメッシュコードから厳密に生成する（.shp と一致することを検証する）。
- W12 流域界（単位流域 377面）にセル重心が入るものだけを残し、流域IDを付与する
  → 流域単位の土地利用集計が可能になる。
"""
import sys, pathlib, zipfile, tempfile, collections, csv, json, shutil
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import numpy as np
import shapefile
import shapely
from shapely.geometry import shape as shp_shape
from common import RAW, PROC, ROOT, register, write_jsonl
from nlni_lib import (read_shp, write_csv, extract_attribute_table, write_columns_csv,
                      parse_codelist_html, GEOD)

PAGE = "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b.html"
BASE = RAW / "nlni_l03b_landuse"
MESHES = ("5238", "5239", "5338", "5339")
YEARS = {"16": 2016, "06": 2006}
LICENSE = {
    2016: ("国土数値情報利用約款 / 平成28年度分は「適用する利用規約に基づく（オープンデータ）」"
           " https://nlftp.mlit.go.jp/ksj/other/agreement.html"),
    2006: ("国土数値情報利用約款 / ダウンロードページ記載の使用許諾条件「商用可」"
           " https://nlftp.mlit.go.jp/ksj/other/agreement.html"),
}
CODELIST = {2016: "LandUseCd-09", 2006: "LandUseCd-YY"}


def mesh_cell(code):
    """10桁メッシュコード -> (lon0, lat0, lon1, lat1)。1/10細分区画=100mメッシュ。"""
    lat = int(code[0:2]) / 1.5
    lon = int(code[2:4]) + 100.0
    lat += int(code[4]) / 12.0
    lon += int(code[5]) / 8.0
    lat += int(code[6]) / 120.0
    lon += int(code[7]) / 80.0
    lat += int(code[8]) / 1200.0
    lon += int(code[9]) / 800.0
    return lon, lat, lon + 1 / 800.0, lat + 1 / 1200.0


# ---- メッシュコード→矩形 の検証（2016年 5339 の .shp と突き合わせ）----
_v = BASE / "L03-b-16_5339.shp"
if _v.exists():
    vr = shapefile.Reader(str(_v).replace(".shp", ""), encoding="cp932")
    bad = 0
    for i in (0, 1, 12345, 400000, 629999):
        code = vr.record(i)[0]
        pts = vr.shape(i).points
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        b = mesh_cell(code)
        if (abs(min(xs) - b[0]) > 1e-9 or abs(min(ys) - b[1]) > 1e-9
                or abs(max(xs) - b[2]) > 1e-9 or abs(max(ys) - b[3]) > 1e-9):
            bad += 1
    print(f"  mesh_cell() 検証: 不一致 {bad}/5 (0 なら .shp と厳密一致)")
    assert bad == 0, "メッシュコード→矩形の生成が .shp と一致しない"
else:
    print("  [warn] 検証用 .shp が無いため mesh_cell() の突き合わせを省略")

# ---- W12 単位流域（流域IDの付与元）----
w12, w12fields, w12recs, _ = read_shp(RAW / "nlni_w12_watersheds"
                                      / "W12-52A-2K-14_WatershedBoundary.shp")
w12geoms, w12ids, w12codes = [], [], []
for sh, rc in zip(w12.shapes(), w12recs):
    g = shp_shape(sh.__geo_interface__)
    if not g.is_valid:
        g = g.buffer(0)
    w12geoms.append(g)
    w12ids.append(f"{rc[1]}-{rc[2]}")
    w12codes.append(rc[1])
tree = shapely.STRtree(w12geoms)
print(f"  W12 unit watersheds for join: {len(w12geoms)}")

# 単位流域ごとの水系名（c30 の出力を利用）
ws_name = {}
p_by = PROC / "nlni_w12_watersheds.csv"
if p_by.exists():
    for r_ in csv.DictReader(open(p_by, encoding="utf-8")):
        ws_name[r_["watershed_id"]] = (r_["water_system_name_ja_estimated"] or "",
                                       r_["water_system_category_ja"] or "")

agg_all = []
for yy, year in YEARS.items():
    landuse = parse_codelist_html(RAW / "nlni_codelists" / f"{CODELIST[year]}.html", r"[0-9A-G]+")
    landuse = {k: v for k, v in landuse.items() if v and v != "-"}
    SID = f"nlni_l03b_landuse_{year}"
    codes, lus, dates, srcrefs = [], [], [], []
    for m in MESHES:
        zp = BASE / f"L03-b-{yy}_{m}-jgd_GML.zip"
        z = zipfile.ZipFile(zp)
        dbfname = [n for n in z.namelist() if n.lower().endswith(".dbf")][0]
        tmp = tempfile.mkdtemp()
        dbf = z.extract(dbfname, tmp)
        rr = shapefile.Reader(dbf=dbf, encoding="cp932")
        fn = [f[0] for f in rr.fields[1:]]
        for rec in rr.records():
            d = dict(zip(fn, rec))
            codes.append(d.get("メッシュ") or d.get("L03b_001"))
            lus.append(d.get("土地利用種") or d.get("L03b_002"))
            dates.append(d.get("撮影年月日") or "")
        srcrefs.append((m, f"https://nlftp.mlit.go.jp/ksj/gml/data/L03-b/L03-b-{yy}/"
                           f"L03-b-{yy}_{m}-jgd_GML.zip"))
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"  {zp.name}: fields={fn} cumulative={len(codes)}")

    # セル矩形 & 重心
    arr = np.array([mesh_cell(c) for c in codes])          # lon0,lat0,lon1,lat1
    cx = (arr[:, 0] + arr[:, 2]) / 2.0
    cy = (arr[:, 1] + arr[:, 3]) / 2.0
    pts = shapely.points(cx, cy)
    qi, ti = tree.query(pts, predicate="within")           # (点index, 流域index)
    assign = {}
    for a, b in zip(qi, ti):
        assign.setdefault(int(a), int(b))                  # 重複は先勝ち
    print(f"  {year}: {len(codes)} cells -> {len(assign)} cells inside W12 watersheds")

    # セル面積(km2): 緯度に依存するので緯度帯ごとに測地線面積を算出して使い回す
    area_cache = {}

    def cell_area(lat0, lon0, lat1, lon1):
        key = round(lat0, 6)
        if key not in area_cache:
            poly = shapely.geometry.box(lon0, lat0, lon1, lat1)
            a, _ = GEOD.geometry_area_perimeter(poly)
            area_cache[key] = abs(a) / 1e6
        return area_cache[key]

    feats, rows, boxes = [], [], {}
    agg = collections.Counter()
    agg_area = collections.Counter()
    zipurl = dict(srcrefs)
    for i in sorted(assign):
        wi = assign[i]
        code, lu = codes[i], lus[i]
        lon0, lat0, lon1, lat1 = arr[i]
        a_km2 = cell_area(lat0, lon0, lat1, lon1)
        wid = w12ids[wi]
        nm, cat = ws_name.get(wid, ("", ""))
        props = {
            "source_id": SID,
            "source_ref": f"L03-b-{yy}_{code[:4]}-jgd_GML.zip#{code}",
            "mesh_code": code,
            "landuse_code_raw": lu,
            "landuse_name_ja": landuse.get(lu),
            "survey_date_raw": dates[i] or None,
            "watershed_id": wid,
            "water_system_code_old": w12codes[wi],
            "water_system_name_ja_estimated": nm or None,
            "cell_area_km2": round(a_km2, 6),
            "centroid_lat": round((lat0 + lat1) / 2, 8),
            "centroid_lon": round((lon0 + lon1) / 2, 8),
            "data_year": year,
        }
        rows.append(props)
        boxes.setdefault((wid, lu), []).append(
            shapely.box(float(lon0), float(lat0), float(lon1), float(lat1)))
        agg[(wid, lu)] += 1
        agg_area[(wid, lu)] += a_km2

    # GeoJSON: 100mセルを (単位流域 × 土地利用種) でディゾルブして出力。
    # セル単位の全属性は .csv/.jsonl 側にあり、セル矩形は mesh_code から厳密に復元できる
    # （復元式は _columns.csv に明記）。セル1枚ずつ出すと 230MB を超え地図表示にも耐えないため。
    for (wid, lu), bx in sorted(boxes.items()):
        merged = shapely.union_all(bx)
        nm, cat = ws_name.get(wid, ("", ""))
        feats.append({"type": "Feature", "properties": {
            "source_id": SID,
            "source_ref": f"L03-b-{yy}#{wid}#{lu}",
            "watershed_id": wid,
            "water_system_code_old": wid.split("-")[0],
            "water_system_name_ja_estimated": nm or None,
            "landuse_code_raw": lu,
            "landuse_name_ja": landuse.get(lu),
            "n_cells": len(bx),
            "area_km2": round(agg_area[(wid, lu)], 6),
            "data_year": year,
            "geometry_note": "100mメッシュセルを単位流域×土地利用種でディゾルブした面",
        }, "geometry": shapely.geometry.mapping(merged)})
    gp = PROC / f"{SID}.geojson"
    with open(gp, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "name": SID,
                   "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
                   "note": "原データ座標系 JGD2000/(B,L)。WGS84(EPSG:4326)として出力。"
                           "100mメッシュを単位流域×土地利用種でディゾルブ済み。",
                   "features": feats}, f, ensure_ascii=False)
    print(f"  [write] {gp.relative_to(ROOT)}  {len(feats)} dissolved features "
          f"({gp.stat().st_size/1e6:.1f} MB)")
    write_csv(SID, rows)
    write_jsonl(SID, rows)

    for (wid, lu), n in sorted(agg.items()):
        nm, cat = ws_name.get(wid, ("", ""))
        agg_all.append({
            "source_id": "nlni_l03b_landuse_by_watershed",
            "source_ref": f"{PAGE}#L03-b-{yy}",
            "data_year": year,
            "watershed_id": wid,
            "water_system_code_old": wid.split("-")[0],
            "water_system_name_ja_estimated": nm or None,
            "landuse_code_raw": lu,
            "landuse_name_ja": landuse.get(lu),
            "n_cells": n,
            "area_km2": round(agg_area[(wid, lu)], 6),
        })

    cols = extract_attribute_table(RAW / "nlni_pages" / "L03b.html")
    for c in cols:
        c["output_column"] = {"L03b_001": "mesh_code", "L03b_002": "landuse_code_raw / landuse_name_ja"}.get(
            c["column_code"], "")
    cols += [
        {"column_code": "メッシュ", "column_name_ja": "メッシュコード",
         "description_ja": "3次メッシュ1/10細分区画(100mメッシュ)の10桁コード。平成28年度版shapefileの列名は日本語。",
         "type_ja": "文字列", "output_column": "mesh_code"},
        {"column_code": "土地利用種", "column_name_ja": "土地利用種別",
         "description_ja": f"コードリスト {CODELIST[year]} による。" +
                           " / ".join(f"{k}={v}" for k, v in sorted(landuse.items())),
         "type_ja": "文字列", "output_column": "landuse_code_raw / landuse_name_ja"},
        {"column_code": "撮影年月日", "column_name_ja": "撮影年月日",
         "description_ja": "原典画像の撮影年月日(YYYYMMDD)。平成18年度版には無い。",
         "type_ja": "文字列", "output_column": "survey_date_raw"},
        {"column_code": "", "column_name_ja": "セル面積(km2)",
         "description_ja": "本収集で算出。メッシュコードから生成した矩形の pyproj.Geod 測地線面積を km2 換算（緯度帯ごとに算出しキャッシュ）。",
         "type_ja": "実数", "output_column": "cell_area_km2"},
        {"column_code": "", "column_name_ja": "セル矩形の復元式",
         "description_ja": "mesh_code(10桁)から厳密に復元できる。lat=int(c[0:2])/1.5+int(c[4])/12+int(c[6])/120+int(c[8])/1200, "
                           "lon=100+int(c[2:4])+int(c[5])/8+int(c[7])/80+int(c[9])/800, セルは (lon, lat)〜(lon+1/800, lat+1/1200)。",
         "type_ja": "—", "output_column": "mesh_code / centroid_lat / centroid_lon"},
        {"column_code": "", "column_name_ja": "所属単位流域",
         "description_ja": "本収集で付与。セル重心が W12 流域界(神奈川県, 昭和52年)のどの単位流域ポリゴン内にあるかで判定。境界上/複数該当は先勝ち。",
         "type_ja": "文字列", "output_column": "watershed_id / water_system_code_old / water_system_name_ja_estimated"},
    ]
    write_columns_csv(SID, cols)

    lu_summary = collections.Counter()
    for r_ in rows:
        lu_summary[r_["landuse_name_ja"] or f"code:{r_['landuse_code_raw']}"] += r_["cell_area_km2"]
    summ = " / ".join(f"{k}:{v:.1f}km2" for k, v in lu_summary.most_common())
    print("   " + summ)
    register(SID, f"国土数値情報 土地利用細分メッシュ（神奈川県流域内, {year}年）",
             "国土交通省 国土数値情報ダウンロードサイト", PAGE, "gis_landuse",
             "http_zip_shapefile(dbf)", "geojson+csv+jsonl", LICENSE[year], 1, len(rows),
             f"1次メッシュ {'/'.join(MESHES)} の JGD2000(-jgd)版。100mメッシュ。"
             f"セル形状はメッシュコードから厳密生成し .shp と一致することを検証済み（.shpは85MB/枚のため未展開）。"
             f"W12流域界(神奈川)内に重心が入るセルのみ {len(rows)} 件を残した（原データ4枚合計 {len(codes)} セル）。"
             f"CSV/JSONL はセル単位（{len(rows)}行）、GeoJSON は単位流域×土地利用種でディゾルブした {len(feats)} 面"
             "（セル単位GeoJSONは230MB超で地図表示に耐えないため。セル矩形は mesh_code から厳密復元でき、復元式は _columns.csv に記載）。"
             f"土地利用種コードは {CODELIST[year]} で名称化。内訳: {summ}。"
             "【時系列比較の注意】平成18(2006)年度は1桁コード(LandUseCd-YY)で幹線交通用地が「9」の1区分、"
             "平成28(2016)年度は4桁コード(LandUseCd-09)で「0901 道路」「0902 鉄道」に分かれる。"
             "また 2006 年度には土地利用種「0」(コードリスト外) のセルが存在し名称を与えていない。"
             "昭和51/62・平成3/9年度版は日本測地系(TD)のみの提供でメッシュ番号の準拠測地系が異なるため、"
             "メッシュコードによる直接比較は行わず本収集では取得していない。")

write_csv("nlni_l03b_landuse_by_watershed", agg_all)
write_jsonl("nlni_l03b_landuse_by_watershed", agg_all)
register("nlni_l03b_landuse_by_watershed", "土地利用細分メッシュ 流域別集計（神奈川県 2006/2016）",
         "国土交通省 国土数値情報ダウンロードサイト（本収集で集計）", PAGE, "gis_landuse",
         "derived", "csv+jsonl", LICENSE[2016], 1, len(agg_all),
         "L03-b(2006/2016)の100mメッシュを W12 単位流域ID×土地利用種で件数・面積集計したもの。"
         "面積はセル面積(測地線)の単純合計。2006年度と2016年度でコード体系が異なる点に注意"
         "（幹線交通用地 9 ⇔ 道路0901/鉄道0902）。")
