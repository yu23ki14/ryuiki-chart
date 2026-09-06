"""国土数値情報(MLIT) 共通ユーティリティ: ダウンロードページ解析 / shapefile→GeoJSON / 面積計算"""
import csv, html, json, re, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import PROC, RAW, ROOT

from pyproj import Geod
from shapely.geometry import shape as shp_shape
from shapely.ops import unary_union

GEOD = Geod(ellps="WGS84")

LICENSE_OPEN = ("国土数値情報利用約款（出典明示で商用利用・再配布可）"
                " https://nlftp.mlit.go.jp/ksj/other/agreement.html")
LICENSE_NONCOM = ("国土数値情報利用約款 + ダウンロードページ記載の使用許諾条件「非商用」"
                  "（出典明示で利用可・商用利用不可）"
                  " https://nlftp.mlit.go.jp/ksj/other/agreement.html")


# ---------- ダウンロードページ解析 ----------
def strip_tags(s):
    return html.unescape(re.sub(r"<[^>]+>", "\t", s))


def page_text(path):
    h = pathlib.Path(path).read_text(encoding="utf-8")
    t = strip_tags(h)
    t = re.sub(r"[ \t　]+", "\t", t)
    return re.sub(r"\n+", "\n", t)


def extract_download_links(path):
    """DownLd('size','filename','path') を抽出 -> [(size, filename, path)]"""
    h = pathlib.Path(path).read_text(encoding="utf-8")
    return re.findall(r"DownLd\(\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'", h)


def extract_attribute_table(page_path):
    """ダウンロードページの「属性情報」表から (属性名_ja, shp属性コード, 説明) を抽出"""
    h = pathlib.Path(page_path).read_text(encoding="utf-8")
    i = h.find("属性情報")
    if i < 0:
        return []
    seg = h[i:]
    for stop in ("ダウンロードするデータの選択", "データダウンロード</", "選択してください"):
        j = seg.find(stop)
        if j > 0:
            seg = seg[:j]
    out, seen = [], set()
    for row in re.finditer(r"<tr[^>]*>(.*?)</tr>", seg, re.S):
        cells = [re.sub(r"\s+", " ", strip_tags(c).replace("\t", " ")).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row.group(1), re.S)]
        cells = [c for c in cells if c]
        if len(cells) < 2:
            continue
        name = cells[0]
        m = re.search(r"[（(]\s*([A-Za-z0-9_\-]+)\s*[）)]", name)
        code = m.group(1) if m else ""
        name_ja = re.sub(r"[（(][^）)]*[）)]", "", name).strip()
        if not name_ja or name_ja in ("属性名", "地物名", "属性の型", "説明"):
            continue
        if name_ja in ("主な品質情報", "データフォーマット（符号化）", "識別子",
                       "その他の情報", "更新履歴", "国土情報ウェブマッピングシステムへの登録",
                       "XMLスキーマ等について", "その他"):
            continue
        key = (name_ja, code)
        if key in seen:
            continue
        seen.add(key)
        out.append({"column_code": code, "column_name_ja": name_ja,
                    "description_ja": cells[1] if len(cells) > 1 else "",
                    "type_ja": cells[2] if len(cells) > 2 else ""})
    return out


def parse_codelist_html(path, code_re=r"\d+"):
    """コードリストHTMLの表 -> {code: 名称}"""
    h = pathlib.Path(path).read_text(encoding="utf-8")
    out = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S):
        c = [html.unescape(re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", x)))
             for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(c) >= 2 and re.fullmatch(code_re, c[0]):
            out[c[0]] = c[1]
    return out


def write_columns_csv(source_id, rows, extra=()):
    p = PROC / f"{source_id}_columns.csv"
    rows = list(rows) + list(extra)
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["column_code", "column_name_ja",
                                          "description_ja", "type_ja", "output_column"])
        w.writeheader()
        for r in rows:
            r.setdefault("output_column", "")
            w.writerow(r)
    print(f"  [write] {p.relative_to(ROOT)}  {len(rows)} rows")
    return p


# ---------- ジオメトリ ----------
def read_shp(path, prefer=("cp932", "utf-8")):
    import shapefile
    last = None
    for enc in prefer:
        try:
            r = shapefile.Reader(str(path), encoding=enc)
            recs = r.records()
            txt = "".join(str(v) for rec in recs[:200] for v in rec if isinstance(v, str))
            # 文字化けチェック: 全角化けは U+FFFD か制御文字で出る
            if "�" in txt:
                last = f"mojibake with {enc}"
                continue
            return r, [f[0] for f in r.fields[1:]], recs, enc
        except Exception as e:  # noqa
            last = f"{enc}: {e!r}"
    raise RuntimeError(f"cannot read {path}: {last}")


def geod_area_km2(geom):
    """測地線面積(km2)。WGS84回転楕円体上の測地線多角形面積(pyproj.Geod)。"""
    try:
        a, _ = GEOD.geometry_area_perimeter(geom)
        return round(abs(a) / 1e6, 6)
    except Exception:
        return None


def geod_length_km(geom):
    try:
        _, p = GEOD.geometry_area_perimeter(geom)
        return round(abs(p) / 1000.0, 6)
    except Exception:
        return None


def write_geojson(source_id, features, crs_note=""):
    p = PROC / f"{source_id}.geojson"
    fc = {"type": "FeatureCollection",
          "name": source_id,
          "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
          "features": features}
    if crs_note:
        fc["note"] = crs_note
    with open(p, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False)
    print(f"  [write] {p.relative_to(ROOT)}  {len(features)} features "
          f"({p.stat().st_size/1e6:.1f} MB)")
    return p


def write_csv(source_id, rows, fieldnames=None):
    p = PROC / f"{source_id}.csv"
    if not rows:
        p.write_text("", encoding="utf-8")
        return p
    fn = fieldnames or list(rows[0].keys())
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fn, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  [write] {p.relative_to(ROOT)}  {len(rows)} rows")
    return p


# ---- W12 単位流域の割り当て（流域単位で束ねるための共通処理） ----
_W12 = None


def w12_index():
    """W12 神奈川県 単位流域の STRtree を返す -> (tree, ids, codes, names)"""
    global _W12
    if _W12 is not None:
        return _W12
    import csv as _csv
    import shapely
    r, fields, recs, _ = read_shp(RAW / "nlni_w12_watersheds"
                                  / "W12-52A-2K-14_WatershedBoundary.shp")
    geoms, ids, codes = [], [], []
    for sh, rc in zip(r.shapes(), recs):
        g = shp_shape(sh.__geo_interface__)
        if not g.is_valid:
            g = g.buffer(0)
        geoms.append(g); ids.append(f"{rc[1]}-{rc[2]}"); codes.append(rc[1])
    names = {}
    p = PROC / "nlni_w12_watersheds.csv"
    if p.exists():
        for row in _csv.DictReader(open(p, encoding="utf-8")):
            names[row["watershed_id"]] = row["water_system_name_ja_estimated"] or None
    _W12 = (shapely.STRtree(geoms), ids, codes, names)
    return _W12


def assign_watershed(geom):
    """ジオメトリの重心が入る W12 単位流域を返す。
    -> dict(watershed_id, water_system_code_old, water_system_name_ja_estimated, watershed_join_method)
    """
    import shapely
    tree, ids, codes, names = w12_index()
    c = geom.centroid
    pt = shapely.points(c.x, c.y)
    hit = tree.query(pt, predicate="within")
    wid = None
    if len(hit):
        wid = int(hit[0])
    else:                       # 重心が流域界外（海側等）→ 最近傍を採らずに null
        return {"watershed_id": None, "water_system_code_old": None,
                "water_system_name_ja_estimated": None,
                "watershed_join_method": "重心がW12流域界の外 → 未割当"}
    return {"watershed_id": ids[wid], "water_system_code_old": codes[wid],
            "water_system_name_ja_estimated": names.get(ids[wid]),
            "watershed_join_method": "重心点がW12単位流域(神奈川,昭和52年)に内包"}
