"""鹿児島県「土砂災害警戒区域データ等」（BODIK 460001_kgod016、2026-02-10 現在）の奄美5市町村を hazard_zones の入力にする。

設計: docs/plans/AMAMI_STEP3C.md §1・§2・§5「A33」。取得は c103a_a33_fetch.py。表への投入は m05_tier1.load_hazard_zones。

- 読み方: `1系/指定/{d,k}_{y,r}zone1.shp`・`j_yzone1.shp`（pyshp。DBF は cp932）。`未指定/`（基礎調査完了・5行）は入れない。
  `new_city` が5市町村の行だけ取る（喜界・徳之島などは範囲外）。
- 座標: JGD2011 第I系（EPSG:6669）-> WGS84（pyproj, always_xy）。無効なジオメトリは shapely.make_valid（直した件数を出す）。
  座標は 6 桁（約0.1m）で単純化なし。面積は変換前の平面（第I系）の値で、ポリゴンごと。**区分（警戒/特別）をまたいで足さない**
  （特別警戒区域は警戒区域の内側にある）。代表点は WGS84 の representative_point。
- 公示日: 変換できるものだけ ISO にする。`令和2月3月13日`（35行。誤記とみられる）は直さず designated_on=NULL・raw は原文のまま。
- river_name_ja は '水系名|河川名'。原表の「-」（なし）は空として扱う。
- zone_id = '<箇所番号>:<r|y>:<同じ箇所番号・同じ色の中の連番 1..>'。箇所番号は120箇所で重複する（分割された区域）。
- 検算（§5）は書く前に全部通す。通らなければ止める。
- geopandas は使わない。shapely・pyproj・pyshp はここで（関数の中で）import する（CI の最小環境が import だけでは落ちないように）。

使い方: python3 scripts/c103b_a33_hazard_zones.py [--dry-run] [--no-register]
"""
import argparse
import csv
import datetime
import glob
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import common
import regions
from era_table import ERA

SOURCE_ID = regions.name("bodik_kagoshima_dosha", "jp-46")      # bodik_kagoshima_dosha_amami
RAW = common.RAW / "bodik_a33"
LICENSE = "CC BY 4.0"
DATASET_URL = "https://data.bodik.jp/dataset/460001_kgod016"

MUNICIPALITIES = ("奄美市", "瀬戸内町", "龍郷町", "宇検村", "大和村")
# shp 名 -> (現象コード, 区分コード, 箇所番号の列, 箇所名の列)
FILES = {
    "d_yzone1": ("debris_flow", "warning", "keiryunum", "keiryuname"),
    "d_rzone1": ("debris_flow", "special_warning", "keiryunum", "keiryuname"),
    "k_yzone1": ("steep_slope", "warning", "kashonum", "kashoname"),
    "k_rzone1": ("steep_slope", "special_warning", "kashonum", "kashoname"),
    "j_yzone1": ("landslide", "warning", "kashonum", "kashoname"),
}
PHENOMENA = {"土石流": "debris_flow", "急傾斜地の崩壊": "steep_slope", "地滑り": "landslide"}
KINDS = {"警戒区域": "warning", "特別警戒区域": "special_warning"}
COLOR = {"warning": "y", "special_warning": "r"}
# §1.2 の実測（ファイル × 市町村）。一致しなければ止める
EXPECTED_COUNTS = {
    "d_yzone1": (388, 355, 145, 98, 42), "d_rzone1": (319, 290, 119, 61, 38),
    "k_yzone1": (881, 575, 346, 160, 79), "k_rzone1": (900, 586, 347, 165, 79),
    "j_yzone1": (16, 10, 12, 27, 0),
}
EXPECTED_TOTAL = 6038
EXPECTED_MULTI_SITES = 120      # 同じ箇所番号・同じ区分で複数行の箇所（分割された区域。宣言した事実）
# 設計時の実測は 198,460（変換前）。make_valid と 6 桁への丸め（連続する同一点が消える）で 0.2% ほど減るので下限は 198,000
MIN_VERTICES = 198_000
# 区分別の面積の総和（km²。ポリゴンごとの平面面積の合計。区分をまたいで足さない）。±0.01
EXPECTED_AREA_KM2 = {
    ("debris_flow", "warning"): 26.2, ("steep_slope", "warning"): 37.8, ("landslide", "warning"): 2.11,
    ("debris_flow", "special_warning"): 0.75, ("steep_slope", "special_warning"): 20.86,
}
BAD_DATE_RAW = "令和2月3月13日"
EXPECTED_BAD_DATES = 35
EXPECTED_PARSED_DATES = 6003
FIELDS = ["zone_id", "site_code", "site_name_ja", "phenomenon_code", "phenomenon_ja", "zone_kind_code", "zone_kind_ja",
          "municipality_ja", "locality_ja", "river_name_ja", "office_ja", "designated_on", "designated_on_raw",
          "notice_no_raw", "area_m2", "centroid_lat", "centroid_lon", "geometry_geojson", "source_id", "source_ref",
          "n_vertices"]    # n_vertices は検算・正解 csv 用（表には入れない。m05 は読まない）
DATE_RE = re.compile(r"^(令和|平成)(元|\d+)年(\d+)月(\d+)日$")


def era_date(raw):
    """公示日の原文 -> ISO（YYYY-MM-DD）。合わなければ None（誤記を直さない）。"""
    m = DATE_RE.match((raw or "").strip())
    if not m:
        return None
    y = ERA[m.group(1)] + (1 if m.group(2) == "元" else int(m.group(2)))
    try:
        return datetime.date(y, int(m.group(3)), int(m.group(4))).isoformat()
    except ValueError:
        return None


def _round_coords(c, nd=6):
    if isinstance(c[0], (int, float)):
        return [round(c[0], nd), round(c[1], nd)]
    return [_round_coords(x, nd) for x in c]


def count_vertices(c):
    if isinstance(c[0], (int, float)):
        return 1
    return sum(count_vertices(x) for x in c)


def _polygonal(geom):
    """make_valid が GeometryCollection を返したら、面の部分だけにする。"""
    from shapely.geometry import MultiPolygon, Polygon
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    parts = []
    for g in getattr(geom, "geoms", []):
        p = _polygonal(g)
        if p is not None and not p.is_empty:
            parts.extend(p.geoms if isinstance(p, MultiPolygon) else [p])
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)


def convert_geometry(geom_plane, transform):
    """第I系の GeoJSON ジオメトリ -> (WGS84 6桁の GeoJSON 文字列, 平面面積 m², 代表点(lat,lon), 頂点数, 直した種別 0/1/2)。"""
    from shapely.geometry import mapping, shape
    from shapely.ops import transform as shp_transform
    from shapely.validation import make_valid
    g = shape(geom_plane)
    fixed = int(not g.is_valid)       # 1=もとの形が無効 / 2=6桁に丸めて無効になった
    if fixed:
        g = _polygonal(make_valid(g))
        if g is None:
            raise ValueError("make_valid の結果に面が無い")
    area = g.area
    w = shp_transform(transform, g)
    gj = mapping(w)
    gj = {"type": gj["type"], "coordinates": _round_coords(gj["coordinates"])}
    rounded = shape(gj)
    if not rounded.is_valid:        # 6桁に丸めて自己接触した。丸めた後の形を直す（直した数に数える）
        fixed = 2
        repaired = _polygonal(make_valid(rounded))
        if repaired is None:        # 面積 0.002 m² ほどの欠片は丸めると消える。その行だけ 9 桁で持つ（行は落とさない）
            gj = {"type": gj["type"], "coordinates": _round_coords(mapping(w)["coordinates"], 9)}
        else:
            m = mapping(repaired)
            gj = {"type": m["type"], "coordinates": _round_coords(m["coordinates"])}
            w = repaired
    pt = w.representative_point()
    return (json.dumps(gj, ensure_ascii=False, separators=(",", ":")), area, (pt.y, pt.x),
            count_vertices(gj["coordinates"]), fixed)


def make_transform():
    from pyproj import Transformer
    return Transformer.from_crs(6669, 4326, always_xy=True).transform


def build_rows(features, transform):
    """features: [{'file','rec_no','props','geometry'}] -> (行 dict のリスト〔zone_id 付き〕, Counter{直した種別: 件数})。
    shp ファイル名から決まる現象・区分と、属性（genshoname・kubun）が食い違えば止める。"""
    rows, fixed_n = [], Counter()
    seq = defaultdict(int)
    for f in features:
        ph, kind, kcol, ncol = FILES[f["file"]]
        p = f["props"]
        if PHENOMENA.get(p["genshoname"]) != ph:
            raise ValueError(f"{f['file']}#{f['rec_no']}: genshoname={p['genshoname']!r}（期待 {ph}）")
        if KINDS.get(p["kubun"]) != kind:
            raise ValueError(f"{f['file']}#{f['rec_no']}: kubun={p['kubun']!r}（期待 {kind}）")
        code = (p[kcol] or "").strip()
        if not code:
            raise ValueError(f"{f['file']}#{f['rec_no']}: 箇所番号が空")
        gj, area, (lat, lon), nv, fixed = convert_geometry(f["geometry"], transform)
        fixed_n[fixed] += 1
        seq[(code, COLOR[kind])] += 1
        raw = (p["koujidate"] or "").strip()
        # 水系名・河川名。空と「-」（原表の「なし」の印）は空として扱い、両方空なら NULL
        river = [(v if v != "-" else "") for v in ((p.get("suikeiname") or "").strip(), (p.get("kasenname") or "").strip())]
        rows.append({
            "zone_id": f"{code}:{COLOR[kind]}:{seq[(code, COLOR[kind])]}",
            "site_code": code, "site_name_ja": (p[ncol] or "").strip() or None,
            "phenomenon_code": ph, "phenomenon_ja": p["genshoname"],
            "zone_kind_code": kind, "zone_kind_ja": p["kubun"],
            "municipality_ja": p["new_city"], "locality_ja": (p["shozaichi"] or "").strip() or None,
            "river_name_ja": "|".join(river) if any(river) else None,
            "office_ja": (p["jimuname"] or "").strip() or None,
            "designated_on": era_date(raw), "designated_on_raw": raw or None,
            "notice_no_raw": (p["koujinum"] or "").strip() or None,
            "area_m2": round(area, 1), "centroid_lat": round(lat, 6), "centroid_lon": round(lon, 6),
            "geometry_geojson": gj, "source_id": SOURCE_ID,
            "source_ref": f"{f['file']}#{f['rec_no']}", "n_vertices": nv,
        })
    return rows, fixed_n


def read_features(base=None):
    """1系/指定 の5つの shp から、5市町村の行を読む。"""
    import warnings
    import shapefile
    warnings.filterwarnings("ignore", message="Specified encoding")   # .cpg は shift_jis。拡張字を含むので cp932 で読む
    base = pathlib.Path(base) if base else RAW / "x"
    dirs = glob.glob(str(base / "*" / "1系" / "指定"))
    if len(dirs) != 1:
        raise SystemExit(f"{base} に 1系/指定 が1つだけ無い（c103a を先に）: {dirs}")
    out = []
    for name in FILES:
        r = shapefile.Reader(str(pathlib.Path(dirs[0]) / name), encoding="cp932")
        cols = [x[0] for x in r.fields[1:]]
        for i, (rec, shp) in enumerate(zip(r.iterRecords(), r.iterShapes())):
            p = dict(zip(cols, rec))
            if p["new_city"] in MUNICIPALITIES:
                out.append({"file": name, "rec_no": i, "props": p, "geometry": shp.__geo_interface__})
    return out


def verify(rows):
    """§5 の検算。通らなければ ValueError。-> 要約の文字列リスト"""
    msgs = []
    if len(rows) != EXPECTED_TOTAL:
        raise ValueError(f"件数 {len(rows)}（期待 {EXPECTED_TOTAL}）")
    got = Counter((r["source_ref"].split("#")[0], r["municipality_ja"]) for r in rows)
    for fn, exp in EXPECTED_COUNTS.items():
        have = tuple(got.get((fn, m), 0) for m in MUNICIPALITIES)
        if have != exp:
            raise ValueError(f"{fn} の市町村別件数 {have}（期待 {exp}）")
    if len({r["zone_id"] for r in rows}) != len(rows):
        raise ValueError("zone_id が一意でない")
    sites = Counter((r["site_code"], r["zone_kind_code"]) for r in rows)
    multi = sum(1 for c in sites.values() if c > 1)
    if multi != EXPECTED_MULTI_SITES:
        raise ValueError(f"同じ箇所番号・同じ区分で複数行の箇所 {multi}（期待 {EXPECTED_MULTI_SITES}）")
    msgs.append(f"箇所番号×区分 {len(sites)} 件（複数行の箇所 {multi}）")
    nv = sum(r["n_vertices"] for r in rows)
    if nv < MIN_VERTICES:
        raise ValueError(f"頂点数 {nv} < {MIN_VERTICES}")
    lon0, lat0, lon1, lat1 = regions.REGIONS["jp-46"]["bbox"]
    for r in rows:
        g = json.loads(r["geometry_geojson"])
        if g["type"] not in ("Polygon", "MultiPolygon"):
            raise ValueError(f"{r['zone_id']}: {g['type']}")
        if not (lon0 <= r["centroid_lon"] <= lon1 and lat0 <= r["centroid_lat"] <= lat1):
            raise ValueError(f"{r['zone_id']}: 代表点が奄美の範囲外 ({r['centroid_lat']}, {r['centroid_lon']})")
        stack = [g["coordinates"]]
        while stack:
            c = stack.pop()
            if isinstance(c[0], (int, float)):
                if not (lon0 <= c[0] <= lon1 and lat0 <= c[1] <= lat1):
                    raise ValueError(f"{r['zone_id']}: 頂点が奄美の範囲外 {c}")
            else:
                stack.extend(c)
    area = defaultdict(float)
    for r in rows:
        area[(r["phenomenon_code"], r["zone_kind_code"])] += r["area_m2"] / 1e6
    for k, exp in EXPECTED_AREA_KM2.items():
        if abs(area[k] - exp) > 0.01:
            raise ValueError(f"面積 {k}: {area[k]:.3f} km²（期待 {exp}±0.01）")
    msgs.append("面積(km²): " + ", ".join(f"{k[0]}/{k[1]}={v:.2f}" for k, v in sorted(area.items())))
    bad = [r for r in rows if r["designated_on"] is None]
    if len(bad) != EXPECTED_BAD_DATES or any(r["designated_on_raw"] != BAD_DATE_RAW for r in bad):
        raise ValueError(f"公示日を変換できない行 {len(bad)}（期待 {EXPECTED_BAD_DATES} 行、すべて {BAD_DATE_RAW!r}）")
    if len(rows) - len(bad) != EXPECTED_PARSED_DATES:
        raise ValueError(f"公示日を変換できた行 {len(rows) - len(bad)}（期待 {EXPECTED_PARSED_DATES}）")
    msgs.append(f"頂点数 {nv:,}・公示日が変換できない行 {len(bad)}（直さない）")
    return msgs


def write_outputs(rows):
    base = common.PROC / SOURCE_ID
    with open(f"{base}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"  [write] {base.relative_to(common.ROOT)}.csv  {len(rows)} rows")
    common.write_jsonl(SOURCE_ID, rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="検算だけして何も書かない")
    ap.add_argument("--no-register", action="store_true", help="source_registry（ryuiki.sqlite）に登録しない")
    a = ap.parse_args()
    feats = read_features()
    rows, fixed = build_rows(feats, make_transform())
    print(f"  [read] {len(rows)} ポリゴン（もとが無効で make_valid {fixed[1]}・6桁に丸めて無効になり直した {fixed[2]}）")
    for m in verify(rows):
        print("  [check]", m)
    if a.dry_run:
        return
    write_outputs(rows)
    if not a.no_register:
        common.register(
            SOURCE_ID, "土砂災害警戒区域・土砂災害特別警戒区域（奄美5市町村）", "鹿児島県土木部砂防課（BODIK）",
            DATASET_URL, "防災", "HTTP GET (CKAN package_show -> ZIP/shapefile)", "Shapefile", LICENSE, True, len(rows),
            notes=f"2026-02-10 現在（20260210_shape.zip）。指定済みのみ（未指定=基礎調査完了の5行は入れない）。座標は第I系->WGS84を6桁、"
                  f"無効ジオメトリ {fixed[1]} 件は make_valid、6桁に丸めて無効になった {fixed[2]} 件も直した。公示日の誤記 {EXPECTED_BAD_DATES} 件（{BAD_DATE_RAW}）は直さず designated_on=NULL。"
                  "特別警戒区域は警戒区域の内側にあり、面積を区分をまたいで足さない。")


if __name__ == "__main__":
    main()
