"""国土数値情報(MLIT) 共通ユーティリティ: ダウンロードページ解析 / shapefile→GeoJSON / 面積計算"""
import csv, html, json, re, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import PROC, RAW, ROOT, download
import regions

from pyproj import Geod
from shapely.geometry import shape as shp_shape
from shapely.ops import unary_union

GEOD = Geod(ellps="WGS84")

# W05 河川は県ごとに版が違う（神奈川は W05-08＝平成20年、鹿児島は W05-07＝平成19年しか無い）。
W05_EDITION = {"14": ("08", "平成20年"), "46": ("07", "平成19年")}


def layout(rid):
    """国土数値情報の c スクリプト群（c30〜c35・c62）が使う出力名・source_id・raw パス・URL。

    jp-14 は従来の直書きと1文字も変わらない（scripts/tests/test_nlni_region.py が固定）。
    他の地域は regions.name() で `_<slug>` を付ける。ネットワークにも disk にも触れない。
    """
    reg = regions.get(rid)
    pref = reg["pref_code"]
    nm = lambda base: regions.name(base, rid)  # noqa: E731
    w05_ed, w05_yr = W05_EDITION[pref]
    w05_dir = nm("nlni_w05_rivers")
    w05_stem = f"W05-{w05_ed}_{pref}-g"
    w12_sid = nm("nlni_w12_watersheds")
    return {
        "rid": rid, "pref": pref, "pref_name_ja": reg["pref_name_ja"],
        "pref_short": reg["pref_name_ja"].removesuffix("県"),
        "name_ja": reg["name_ja"],
        # 県全域でない地域（muni_codes がある）は bbox に絞る。県全域の jp-14 は絞らない。
        "clip_bbox": reg["bbox"] if reg["muni_codes"] is not None else None,
        "bbox": reg["bbox"],
        # W05
        "w05_sid": w05_dir, "w05_nodes_sid": nm("nlni_w05_river_nodes"), "w05_dir": RAW / w05_dir,
        "w05_year_ja": w05_yr, "w05_edition": w05_ed,
        "w05_zip_url": f"https://nlftp.mlit.go.jp/ksj/gml/data/W05/W05-{w05_ed}/W05-{w05_ed}_{pref}_GML.zip",
        "w05_stream_shp": RAW / w05_dir / f"{w05_stem}_Stream.shp",
        "w05_node_shp": RAW / w05_dir / f"{w05_stem}_RiverNode.shp",
        "w05_stream_stem": f"{w05_stem}_Stream", "w05_node_stem": f"{w05_stem}_RiverNode",
        # W12
        "w12_sid": w12_sid,
        "w12_zip_url": f"https://nlftp.mlit.go.jp/ksj/gmlold/data/W12/W12-52A/W12-52A-{pref}-01.0a_GML.zip",
        "w12_dir": RAW / w12_sid,
        "w12_shp": RAW / w12_sid / f"W12-52A-2K-{pref}_WatershedBoundary.shp",
        # A10 / A15 / A45
        "a10_sid": nm("nlni_a10_natparks"),
        "a10_zip_url": f"https://nlftp.mlit.go.jp/ksj/gml/data/A10/A10-15/A10-15_{pref}_GML.zip",
        "a15_sid": nm("nlni_a15_wildlife"),
        "a15_zip_url": f"https://nlftp.mlit.go.jp/ksj/jpgis/data/A15/A15-09/A15-09_{pref}.zip",
        "a15_xml": RAW / nm("nlni_a15_wildlife") / f"A15-09_{pref}" / f"A15-09_{pref}.xml",
        "a45_sid": nm("nlni_a45_forest"),
        "a45_zip_url": f"https://nlftp.mlit.go.jp/ksj/gml/data/A45/A45-19/A45-19_{pref}_GML.zip",
        # L03-b
        "l03b_dir": RAW / nm("nlni_l03b_landuse"),
        "l03b_meshes": reg["l03b_meshes"],
        "l03b_sid": lambda year: nm(f"nlni_l03b_landuse_{year}"),
        "l03b_by_ws_sid": nm("nlni_l03b_landuse_by_watershed"),
        # 標高
        "elev_sid": nm("gsi_elevation_grid"),
    }


def ensure_extracted(url, zip_path, out_dir, probe, subdir=None):
    """`probe`（out_dir 直下のファイル名）が無ければ zip を取って平らに展開する（zip-slip 防止）。
    subdir があればその下に展開する。取得済みなら何もしない。"""
    import zipfile
    dest = out_dir / subdir if subdir else out_dir
    if (dest / probe).exists():
        return dest
    download(url, zip_path)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            fn = pathlib.PurePosixPath(n).name
            if fn:
                (dest / fn).write_bytes(z.read(n))
    return dest


def bbox_geom(bbox):
    from shapely.geometry import box
    return box(*bbox)

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
_W12 = {}


def w12_index(rid="jp-14"):
    """W12 単位流域の STRtree を返す -> (tree, ids, codes, names)。地域ごとに1回だけ作る。
    県全域でない地域は、c30 と同じ bbox の絞り込みを掛ける（c30 の出力と流域IDが一致する）。"""
    if rid in _W12:
        return _W12[rid]
    import csv as _csv
    import shapely
    L = layout(rid)
    r, fields, recs, _ = read_shp(L["w12_shp"])
    clip = bbox_geom(L["clip_bbox"]) if L["clip_bbox"] else None
    geoms, ids, codes = [], [], []
    for sh, rc in zip(r.shapes(), recs):
        g = shp_shape(sh.__geo_interface__)
        if not g.is_valid:
            g = g.buffer(0)
        if clip is not None and not g.intersects(clip):
            continue
        geoms.append(g); ids.append(f"{rc[1]}-{rc[2]}"); codes.append(rc[1])
    names = {}
    p = PROC / f"{L['w12_sid']}.csv"
    if p.exists():
        for row in _csv.DictReader(open(p, encoding="utf-8")):
            names[row["watershed_id"]] = row["water_system_name_ja_estimated"] or None
    _W12[rid] = (shapely.STRtree(geoms), ids, codes, names)
    return _W12[rid]


def assign_watershed(geom, rid="jp-14"):
    """ジオメトリの重心が入る W12 単位流域を返す。
    -> dict(watershed_id, water_system_code_old, water_system_name_ja_estimated, watershed_join_method)
    """
    import shapely
    tree, ids, codes, names = w12_index(rid)
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
            "watershed_join_method": f"重心点がW12単位流域({layout(rid)['pref_short']},昭和52年)に内包"}
