"""国土数値情報 A15 鳥獣保護区（神奈川県 14, 平成21/2009年）→ GeoJSON/CSV/JSONL

配布形式は JPGIS 1.0 準拠 XML のみ（shapefile 版は無い）ため、
GM_Surface → GM_SurfaceBoundary(exterior/interior) → GM_Ring
→ GM_CompositeCurve.generator → GM_OrientableCurve → GM_Curve → GM_LineString
の位相参照を解決して面を組み立てる。座標は "緯度 経度" 順。
"""
import sys, pathlib, collections, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import xml.etree.ElementTree as ET
from common import RAW, register, write_jsonl
from nlni_lib import (geod_area_km2, write_geojson, write_csv,
                      extract_attribute_table, write_columns_csv, LICENSE_NONCOM,
                      assign_watershed)
from shapely.geometry import Polygon, MultiPolygon, mapping

SID = "nlni_a15_wildlife"
PAGE = "https://nlftp.mlit.go.jp/ksj/jpgis/datalist/KsjTmplt-A15.html"
ZIPU = "https://nlftp.mlit.go.jp/ksj/jpgis/data/A15/A15-09/A15-09_14.zip"
XML = RAW / SID / "A15-09_14" / "A15-09_14.xml"

# ダウンロードページ「属性情報」原文より
INSTITUTION = {"1": "国指定", "2": "県指定"}
PROTECT = {"1": "鳥獣保護区", "2": "特別保護地区", "3": "休猟区"}

NS = {"ksj": "http://nlftp.mlit.go.jp/ksj/schemas/ksj-app",
      "jps": "http://www.gsi.go.jp/GIS/jpgis/standardSchemas"}


def local(tag):
    return tag.rsplit("}", 1)[-1]


root = ET.parse(XML).getroot()
byid = {}
for el in root.iter():
    i = el.get("id")
    if i:
        byid.setdefault(i, el)


def idref(el, tagname):
    c = el.find(f"{{{NS['ksj']}}}{tagname}")
    return c.get("idref") if c is not None else None


def points_of_curve(cid):
    """GM_Curve id -> [(lon,lat), ...]"""
    cur = byid.get(cid)
    if cur is None:
        return []
    pts = []
    for col in cur.iter():
        if local(col.tag) != "GM_PointArray.column":
            continue
        d = None
        for sub in col.iter():
            lt = local(sub.tag)
            if lt == "GM_PointRef.point":
                p = byid.get(sub.get("idref"))
                if p is not None:
                    for s2 in p.iter():
                        if local(s2.tag) == "DirectPosition.coordinate" and s2.text:
                            d = s2.text
                            break
            elif lt == "DirectPosition.coordinate" and sub.text:
                d = sub.text
            if d:
                break
        if d:
            lat, lon = d.split()[:2]
            pts.append((float(lon), float(lat)))
    return pts


def ring_coords(ring_el):
    segs = []
    for gen in ring_el.iter():
        if local(gen.tag) != "GM_CompositeCurve.generator":
            continue
        oc = byid.get(gen.get("idref"))
        if oc is None:
            continue
        orient = "+"
        prim = None
        for sub in oc:
            lt = local(sub.tag)
            if lt == "GM_OrientablePrimitive.orientation":
                orient = (sub.text or "+").strip()
            elif lt == "GM_OrientablePrimitive.primitive":
                prim = sub.get("idref")
        pts = points_of_curve(prim) if prim else []
        if not pts:
            continue
        segs.append(pts[::-1] if orient == "-" else pts)
    if not segs:
        return []
    # 端点で貪欲に連結（orientation だけでは繋がらないケースがあるため）
    out = list(segs[0])
    rest = segs[1:]
    while rest:
        tail = out[-1]
        best, bi, rev = None, None, False
        for k, s in enumerate(rest):
            for r in (False, True):
                cand = s[::-1] if r else s
                d = (cand[0][0] - tail[0]) ** 2 + (cand[0][1] - tail[1]) ** 2
                if best is None or d < best:
                    best, bi, rev = d, k, r
        s = rest.pop(bi)
        out += (s[::-1] if rev else s)[1:] if best < 1e-12 else (s[::-1] if rev else s)
    if out[0] != out[-1]:
        out.append(out[0])
    return out


def surface_polygon(sid_):
    sf = byid.get(sid_)
    if sf is None:
        return None
    ext, ints = None, []
    for b in sf.iter():
        lt = local(b.tag)
        if lt not in ("GM_SurfaceBoundary.exterior", "GM_SurfaceBoundary.interior"):
            continue
        for ring in b.iter():
            if local(ring.tag) != "GM_Ring":
                continue
            cs = ring_coords(ring)
            if len(cs) < 4:
                continue
            if lt.endswith("exterior") and ext is None:
                ext = cs
            elif lt.endswith("interior"):
                ints.append(cs)
    if not ext:
        return None
    try:
        p = Polygon(ext, ints)
        if not p.is_valid:
            p = p.buffer(0)
        return p
    except Exception:
        return None


def caldate(ref):
    el = byid.get(ref)
    if el is None:
        return None
    for s in el.iter():
        if local(s.tag) == "TM_CalDate.calDate" and s.text:
            t = s.text.strip()
            if re.fullmatch(r"\d{8}", t):
                return f"{t[:4]}-{t[4:6]}-{t[6:]}"
            return t
    return None


feats, rows, skipped = [], [], 0
for bh in root.iter(f"{{{NS['ksj']}}}BH01"):
    fid = bh.get("id")
    are = idref(bh, "ARE")
    poly = surface_polygon(are) if are else None
    if poly is None or poly.is_empty:
        skipped += 1
        geom = None
    else:
        geom = mapping(poly)
    def txt(t):
        e = bh.find(f"{{{NS['ksj']}}}{t}")
        return (e.text or "").strip() if e is not None else None
    dsc, thc = txt("DSC"), txt("THC")
    props = {
        "source_id": SID,
        "source_ref": f"{ZIPU}#A15-09_14.xml:{fid}",
        "feature_id": fid,
        "name_ja": txt("THN"),
        "prefecture_code": txt("PRC"),
        "prefecture_name_ja": "神奈川県",
        "designating_institution_code_raw": dsc,
        "designating_institution_ja": INSTITUTION.get(dsc),
        "protection_class_code_raw": thc,
        "protection_class_ja": PROTECT.get(thc),
        "designated_date": caldate(idref(bh, "DED")),
        "cancel_date": caldate(idref(bh, "CAD")),
        "area_km2": geod_area_km2(poly) if poly is not None else None,
        "centroid_lat": round(poly.centroid.y, 6) if poly is not None else None,
        "centroid_lon": round(poly.centroid.x, 6) if poly is not None else None,
        "data_year": 2009,
    }
    props.update(assign_watershed(poly) if poly is not None else
                 {"watershed_id": None, "water_system_code_old": None,
                  "water_system_name_ja_estimated": None,
                  "watershed_join_method": "ジオメトリ無しのため未割当"})
    if geom:
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    rows.append(props)

print(f"A15: {len(rows)} features (geometry OK {len(feats)}, skipped {skipped})")
write_geojson(SID, feats, crs_note="原データ座標系 JGD2000/(B,L)。WGS84(EPSG:4326)として出力。")
write_csv(SID, rows)
write_jsonl(SID, rows)

cols = extract_attribute_table(RAW / "nlni_pages" / "A15.html")
mapping_out = {"鳥獣保護区ID": "feature_id", "都道府県コード": "prefecture_code",
               "指定機関：指定機関コード": "designating_institution_code_raw / designating_institution_ja",
               "保護区分：保護区分コード": "protection_class_code_raw / protection_class_ja",
               "鳥獣保護区名称": "name_ja", "指定日": "designated_date", "解除日": "cancel_date"}
for c in cols:
    c["output_column"] = mapping_out.get(c["column_name_ja"], "")
cols += [
    {"column_code": "", "column_name_ja": "面積(km2)",
     "description_ja": "本収集で算出。pyproj.Geod(ellps=WGS84).geometry_area_perimeter による測地線多角形面積を km2 換算。",
     "type_ja": "実数", "output_column": "area_km2"},
    {"column_code": "", "column_name_ja": "重心緯度・経度",
     "description_ja": "本収集で算出。shapely centroid（平面近似）。", "type_ja": "実数",
     "output_column": "centroid_lat / centroid_lon"},
    {"column_code": "", "column_name_ja": "所属単位流域",
     "description_ja": "本収集で付与。ポリゴン重心が W12 流域界(神奈川, 昭和52年)のどの単位流域内にあるかで判定。外れる場合は null。",
     "type_ja": "文字列", "output_column": "watershed_id / water_system_code_old / water_system_name_ja_estimated"},
    {"column_code": "", "column_name_ja": "地物ID(XML)",
     "description_ja": "XML 上の ksj:BH01/@id。ダウンロードページ記載の「鳥獣保護区ID(7桁)」属性は本XMLには含まれない。",
     "type_ja": "文字列", "output_column": "feature_id"},
]
write_columns_csv(SID, cols)

byclass = collections.Counter(p["protection_class_ja"] for p in rows)
areas = collections.Counter()
for p in rows:
    areas[p["protection_class_ja"]] += p["area_km2"] or 0
summary = " / ".join(f"{k}:{v}件 {areas[k]:.1f}km2" for k, v in byclass.items())
print("  " + summary)

register(SID, "国土数値情報 鳥獣保護区（神奈川県）", "国土交通省 国土数値情報ダウンロードサイト",
         PAGE, "gis_protected_area", "http_zip_jpgis_xml", "geojson+csv+jsonl",
         LICENSE_NONCOM, 1, len(rows),
         "神奈川県(14) A15-09_14.zip / 平成21(2009)年。配布は JPGIS 準拠 XML のみで shapefile 版は無いため、"
         "GM_Surface の位相参照(Ring→OrientableCurve→Curve→LineString)を自前で解決して面を構築した。"
         f"内訳: {summary}。ジオメトリを構築できなかった地物 {skipped} 件（該当行は geometry 無しで CSV/JSONL のみ）。"
         "指定日 DED / 解除日 CAD は TM_CalDate の 8桁(YYYYMMDD)を YYYY-MM-DD に整形しただけで値の補完はしていない。"
         "ダウンロードページ記載の属性「鳥獣保護区ID(都道府県コード+用地番号+地区番号の7桁)」は本XMLには存在せず、"
         "XML上の地物ID(TJ_n)を feature_id として保持。使用許諾条件は「非商用」。")
