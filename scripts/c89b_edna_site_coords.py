#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""神奈川県 eDNA 地点の推定座標台帳を作る（開発用ツール。出力は台帳 CSV だけ）。

設計: docs/plans/KANAGAWA_EDNA.md §5（§11 のメインの判断を反映）。

公開データに座標は無い。地点ごとに「水系・支川名・市町村名」から**推定位置**を出し、根拠区分
（coord_source）と精度（coordinate_uncertainty_m）をつけて data/edna/kanagawa_edna_site_coords.csv に
書く。判別不能は座標も精度も NULL（coord_source='none'）。市町村の重心は使わない
（地点を表さない値を精度つきで流さない）。

手順（地点 1 件ごと）:
 1. 市町村名を「・」「、」で分け、町丁ポリゴン（estat_shozaiki_kanagawa）の和集合 G にする
    （横浜市・川崎市・相模原市は区の和集合）。
 2. 支川名が空・'-' なら本流とみなし、水系名を河川名にする。'…本流' は末尾を外す。
 3. W05 河川線のうち河川名が一致し、かつ水系名が一致するものを候補にする
    （河川名の表記ゆれ ヶ/ケ・淵/渕 は正規化して突き合わせる）。
 4. 候補を G（100 m 膨らませたもの。境界を流れる川を落とさない）で切り取った線の長さ中心点
    ＝位置。方式 river_in_municipality。精度 = 切り取った線の広がり + 300 m（河川線の位置誤差）を
    100 m 単位に切り上げ、下限 500 m。
 5. 切り取りが空なら、候補線の G に最も近い点 = 位置。方式 river_nearest_municipality。
    精度 = G までの距離 + 300 m（同様に切り上げ・下限 500 m）。
 6. 一般名の支川（小水路・不明・本流・湧水・用水・…小河川）、W05 に名前が無い、市町村が引けない、
    精度が 3,000 m を超える（§11）ものは座標 NULL。
 7. 検算: 位置が入る W12 流域の水系名が地点の水系名と食い違えば evidence に WARN を残す。
    grid01 のキーが registry に無ければ grid01_ok=0（座標を NULL にはしない。件数を報告する）。

reviewed=1 の行（人が図を見て読み取った map_image 等）は再実行で上書きしない。
決定的（同じ入力で同じ出力）。
"""
import sys, csv, json, math, re, sqlite3, argparse, pathlib, collections, unicodedata, os

import shapely
from shapely.geometry import shape, Point, LineString, MultiLineString
from shapely.ops import transform, nearest_points
from shapely import STRtree

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
DEFAULT_SITES = PROC / "kanagawa_edna_sites.csv"
DEFAULT_READS = PROC / "kanagawa_edna_reads.csv"
DEFAULT_OUT = ROOT / "data" / "edna" / "kanagawa_edna_site_coords.csv"
DEFAULT_W05 = PROC / "nlni_w05_rivers.geojson"
DEFAULT_TOWNS = PROC / "estat_shozaiki_kanagawa.geojson"
DEFAULT_W12 = PROC / "nlni_w12_watersheds.geojson"
DEFAULT_REGISTRY = pathlib.Path(os.environ.get("RYUIKI_REGISTRY_DB") or ROOT / "data" / "db" / "registry.sqlite")

LEDGER_COLS = ["site_key", "water_system_ja", "tributary_ja", "municipality_ja", "lat", "lon", "coord_source",
               "coordinate_uncertainty_m", "coord_method", "evidence", "grid01_ok", "reviewed"]

MAX_UNCERTAINTY_M = 3000        # §11: estimated_from_name の上限。超えたら none
RIVER_POSITION_ERROR_M = 300    # 河川線の位置誤差（精度に足す）
MIN_UNCERTAINTY_M = 500
MUNI_BUFFER_M = 100             # 市境を流れる川を落とさないための膨らませ
DESIGNATED_CITIES = ("横浜市", "川崎市", "相模原市")
GENERIC_TRIBUTARIES = {"小水路", "不明", "本流", "湧水", "用水"}

# 神奈川の緯度経度 → 平面メートル（等距円筒。県内の距離計算には十分）
LAT0, LON0 = 35.4, 139.4
M_PER_DEG_LAT = 110574.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(LAT0))


def to_m(x, y, z=None):
    return ((x - LON0) * M_PER_DEG_LON, (y - LAT0) * M_PER_DEG_LAT)


def to_lonlat(x, y):
    return (x / M_PER_DEG_LON + LON0, y / M_PER_DEG_LAT + LAT0)


def norm(s):
    """名前の突き合わせ用の正規化: NFKC・空白除去・括弧書き除去・ヶ/ケ と 淵/渕 の統一。"""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"\s+", "", s)
    return s.replace("ケ", "ヶ").replace("淵", "渕")


def split_munis(s):
    return [m for m in re.split(r"[・、,，]", s or "") if m.strip()]


def ceil100(x):
    return int(math.ceil(x / 100.0) * 100)


class Context:
    def __init__(self, lines, towns, w12, grid01):
        self.lines = lines      # (norm 河川名, norm 水系名 or None) → [LineString(m)]
        self.towns = towns      # [(norm city_name, geom(m))]
        self.w12 = w12          # [(Polygon(lonlat), norm 水系名 or None)]
        self.w12_tree = STRtree([g for g, _ in w12]) if w12 else None
        self.grid01 = grid01    # {(mlat, mlon)}
        self._muni_cache = {}

    def muni_geom(self, name):
        """市町村名 → 町丁ポリゴンの和集合（m）。引けなければ None。"""
        n = norm(name)
        if n in self._muni_cache:
            return self._muni_cache[n]
        parts = [g for cn, g in self.towns if cn == n or (n in DESIGNATED_CITIES and cn.startswith(n))]
        geom = shapely.union_all(parts) if parts else None
        self._muni_cache[n] = geom
        return geom


def load_context(w05, towns, w12, registry):
    lines = collections.defaultdict(list)
    for f in json.load(open(w05, encoding="utf-8"))["features"]:
        p = f["properties"]
        if f["geometry"]["type"] != "LineString" or not p.get("river_name_ja"):
            continue
        lines[(norm(p["river_name_ja"]), norm(p.get("water_system_name_ja")) or None)].append(
            transform(to_m, shape(f["geometry"])))
    tw = []
    for f in json.load(open(towns, encoding="utf-8"))["features"]:
        g = shape(f["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        tw.append((norm(f["properties"]["city_name"]), transform(to_m, g)))
    ws = []
    for f in json.load(open(w12, encoding="utf-8"))["features"]:
        g = shape(f["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        ws.append((g, norm(f["properties"].get("water_system_name_ja_estimated")) or None))
    grid = set()
    if registry and pathlib.Path(registry).exists():
        con = sqlite3.connect(f"file:{registry}?mode=ro", uri=True)
        for (k,) in con.execute("SELECT external_key FROM place_source_ref WHERE key_space='grid01_latlon'"):
            a, b = k.split(":", 1)[1].split(",")
            grid.add((int(a), int(b)))
        con.close()
    return Context(lines, tw, ws, grid)


def _line_parts(geom):
    if geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [geom]
    if geom.geom_type in ("MultiLineString", "GeometryCollection"):
        out = []
        for g in geom.geoms:
            out += _line_parts(g)
        return out
    return []


def river_name_for(trib, water):
    """(河川名 | None, 理由)。None は座標を付けない（理由つき）。"""
    t = norm(trib)
    if t in ("", "-", "－", "ー"):
        return norm(water), None
    if t in GENERIC_TRIBUTARIES or t.endswith("小河川"):
        return None, "none_generic_tributary"
    if t.endswith("本流") and len(t) > 2:
        t = t[:-2]
    return t, None


def estimate(site, ctx):
    """1 地点の推定。{lat, lon, coord_source, coordinate_uncertainty_m, coord_method, evidence}。"""
    water = norm(site.get("water_system_ja"))
    river, why = river_name_for(site.get("tributary_ja"), site.get("water_system_ja"))
    none = lambda method, ev: {"lat": None, "lon": None, "coord_source": "none",
                               "coordinate_uncertainty_m": None, "coord_method": method, "evidence": ev}
    if river is None:
        return none(why, f"支川名 {site.get('tributary_ja')!r} は一般名で、特定の川を指さない")

    munis = split_munis(site.get("municipality_ja"))
    geoms = [ctx.muni_geom(m) for m in munis]
    found = [g for g in geoms if g is not None]
    miss = [m for m, g in zip(munis, geoms) if g is None]
    if not found:
        return none("none_municipality_unmatched", f"市町村 {munis} が町丁ポリゴンに無い")
    G = shapely.union_all(found)

    cands = ctx.lines.get((river, water or None), [])
    if not cands:
        return none("none_river_not_in_w05", f"W05 に 河川名={river!r} 水系={water!r} の線が無い")

    gbuf = G.buffer(MUNI_BUFFER_M)
    pieces = []
    for ln in cands:
        pieces += _line_parts(ln.intersection(gbuf))
    pieces = [p for p in pieces if p.length > 0]
    note_miss = f" 引けなかった市町村 {miss}" if miss else ""
    if pieces:
        merged = shapely.line_merge(MultiLineString(pieces)) if len(pieces) > 1 else pieces[0]
        if merged.geom_type == "LineString":
            pt = merged.interpolate(0.5, normalized=True)
        else:
            pt = nearest_points(merged, merged.centroid)[0]
        coords = shapely.get_coordinates(merged)
        spread = float(max(math.hypot(x - pt.x, y - pt.y) for x, y in coords))
        unc = max(MIN_UNCERTAINTY_M, ceil100(spread + RIVER_POSITION_ERROR_M))
        method = "river_in_municipality"
        ev = (f"W05 {river}/{water} 候補線 {len(cands)} 本を {'・'.join(munis)} で切り取り "
              f"{merged.length / 1000:.1f}km、広がり {spread:.0f}m + {RIVER_POSITION_ERROR_M}m{note_miss}")
    else:
        cu = shapely.union_all(cands)
        p_line, p_g = nearest_points(cu, G)
        d = p_line.distance(p_g)
        pt = p_line
        unc = max(MIN_UNCERTAINTY_M, ceil100(d + RIVER_POSITION_ERROR_M))
        method = "river_nearest_municipality"
        ev = (f"W05 {river}/{water} は {'・'.join(munis)} と交わらない。市町村に最も近い点まで "
              f"{d:.0f}m + {RIVER_POSITION_ERROR_M}m{note_miss}")
    if unc > MAX_UNCERTAINTY_M:
        return none("none_uncertainty_over_limit", f"{ev}（精度 {unc}m > {MAX_UNCERTAINTY_M}m）")
    lon, lat = to_lonlat(pt.x, pt.y)
    return {"lat": round(lat, 6), "lon": round(lon, 6), "coord_source": "estimated_from_name",
            "coordinate_uncertainty_m": unc, "coord_method": method, "evidence": ev}


def check_watershed(res, site, ctx):
    """検算: 位置が入る W12 流域の水系名と地点の水系名が食い違えば警告文（無ければ None）。"""
    if res["lat"] is None or ctx.w12_tree is None:
        return None
    p = Point(res["lon"], res["lat"])
    names = {ctx.w12[i][1] for i in ctx.w12_tree.query(p, predicate="intersects")}
    if not names:
        return "WARN:W12 流域の外"
    water = norm(site.get("water_system_ja"))
    if water not in names:
        return f"WARN:W12 流域の水系 {sorted(n or '(不明)' for n in names)} と地点の水系 {water!r} が食い違う"
    return None


def grid01_ok(res, ctx):
    if res["lat"] is None:
        return ""
    key = (math.floor(res["lat"] * 100), math.floor(res["lon"] * 100))
    return 1 if key in ctx.grid01 else 0


def build_ledger(sites, ctx, existing=None):
    """台帳の行（dict）のリスト。existing の reviewed=1 の行は保持する。"""
    keep = {r["site_key"]: r for r in (existing or []) if str(r.get("reviewed")) == "1"}
    out = []
    for s in sorted(sites, key=lambda r: r["site_key"]):
        if s["site_key"] in keep:
            out.append({c: keep[s["site_key"]].get(c, "") for c in LEDGER_COLS})
            continue
        res = estimate(s, ctx)
        warn = check_watershed(res, s, ctx)
        if warn:
            res["evidence"] = f"{warn} / {res['evidence']}"
        out.append({
            "site_key": s["site_key"], "water_system_ja": s.get("water_system_ja") or "",
            "tributary_ja": s.get("tributary_ja") or "", "municipality_ja": s.get("municipality_ja") or "",
            "lat": "" if res["lat"] is None else res["lat"], "lon": "" if res["lon"] is None else res["lon"],
            "coord_source": res["coord_source"],
            "coordinate_uncertainty_m": "" if res["coordinate_uncertainty_m"] is None else res["coordinate_uncertainty_m"],
            "coord_method": res["coord_method"], "evidence": res["evidence"],
            "grid01_ok": grid01_ok(res, ctx), "reviewed": 0})
    return out


def summarize(ledger, detections_by_site=None):
    """台帳の分布（coord_source・精度・grid01_ok=0・警告）。検出行数は reads CSV があれば付ける。"""
    det = detections_by_site or {}
    lines = []
    by_src = collections.Counter(r["coord_source"] for r in ledger)
    lines.append("coord_source 別の地点数" + (" / 検出行数" if det else "") + ":")
    for src, n in sorted(by_src.items()):
        d = sum(det.get(r["site_key"], 0) for r in ledger if r["coord_source"] == src)
        lines.append(f"  {src}: {n}" + (f" / {d}" if det else ""))
    by_method = collections.Counter(r["coord_method"] for r in ledger)
    lines.append("coord_method: " + ", ".join(f"{k}={v}" for k, v in sorted(by_method.items())))
    uncs = [int(r["coordinate_uncertainty_m"]) for r in ledger if r["coordinate_uncertainty_m"] != ""]
    bins = collections.Counter()
    for u in uncs:
        bins["<=500" if u <= 500 else "<=1000" if u <= 1000 else "<=2000" if u <= 2000 else "<=3000"] += 1
    lines.append("精度(m)の分布: " + ", ".join(f"{k}:{bins[k]}" for k in ("<=500", "<=1000", "<=2000", "<=3000")))
    g0 = [r for r in ledger if str(r["grid01_ok"]) == "0"]
    lines.append(f"grid01_ok=0: {len(g0)} 地点" + (f" / 検出行数 {sum(det.get(r['site_key'], 0) for r in g0)}" if det else ""))
    warns = [r for r in ledger if str(r["evidence"]).startswith("WARN:")]
    lines.append(f"水系と流域の食い違い警告: {len(warns)} 地点")
    return "\n".join(lines)


def write_ledger(path, ledger):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_COLS)
        w.writeheader()
        w.writerows(ledger)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sites", default=str(DEFAULT_SITES))
    ap.add_argument("--reads", default=str(DEFAULT_READS), help="検出行数の集計用（無ければ地点数だけ出す）")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--w05", default=str(DEFAULT_W05))
    ap.add_argument("--towns", default=str(DEFAULT_TOWNS))
    ap.add_argument("--w12", default=str(DEFAULT_W12))
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    args = ap.parse_args(argv)

    sites = list(csv.DictReader(open(args.sites, encoding="utf-8", newline="")))
    out = pathlib.Path(args.out)
    existing = list(csv.DictReader(open(out, encoding="utf-8", newline=""))) if out.exists() else None
    ctx = load_context(args.w05, args.towns, args.w12, args.registry)
    if not ctx.grid01:
        print("  [warn] registry の grid01 が読めない。grid01_ok は 0 になる", file=sys.stderr)
    ledger = build_ledger(sites, ctx, existing)
    write_ledger(out, ledger)

    det = None
    if pathlib.Path(args.reads).exists():
        det = collections.Counter()
        for r in csv.DictReader(open(args.reads, encoding="utf-8", newline="")):
            if r["is_detected"] == "1":
                det[r["site_key"]] += 1
    print(f"  [write] {out}  {len(ledger)} 地点")
    print(summarize(ledger, det))


if __name__ == "__main__":
    main()
