"""地理院 標高タイル（DEM10B の dem_png）から、地点ごとの地形指標を計算して
`data/processed/terrain_points.csv` に書く（zone v2 の入力。docs/plans/AMAMI_STEP0.md §1.2・§3・§6-A）。

列: lat, lon, region_id, summit_m, elevation_m, relief_wide_m, relief_near_m, floor_min_m, coast_dist_m, params_digest
（キーは (lat, lon) の小数6桁。同じ座標の地点は1行を共有する。lat, lon 昇順。決定的）

- 対象 `--points sites`（既定）: 原本 ryuiki.sqlite（読み取り専用）の sites のうち elevation_m IS NOT NULL の座標。
  region は出典のマニフェスト（manifests/<source_id>.yml の region）。マニフェストが無い出典は出典名の slug（regions.region_of_source_id）、それでも引けなければ --default-region（jp-14）。
- 対象 `--checkpoints <yaml>`: 確認地点だけ（scripts/tests/fixtures/zone_checkpoints.yaml）。--out に別の CSV を書く。
  先頭に name, expect, known_miss が付く（テストが読む）。
- 窓の半径・タイルのズームは registry/place/zone.yaml の terrain:。変えたら params_digest が変わり、
  ビルド側が止まる（c68 を回し直す）。最高峰は registry/region.yaml の terrain.summit（宣言値。DEM の最大から導出しない）。
- 最高峰の検査: 宣言座標の周辺 500m の DEM 最大が宣言値 ±20m に収まらなければ止まる。
- W12 は読まない（地点→流域は Issue #86）。
- タイルは data/raw/gsi_dem_png/{z}/{x}/{y}.png にキャッシュ（再取得しない。404 は空ファイル）。1.5 秒以上の間隔。

使い方:
  .venv/bin/python3 scripts/c68_gsi_dem_terrain.py [--plan] [--no-fetch] [--no-register]
  .venv/bin/python3 scripts/c68_gsi_dem_terrain.py --checkpoints scripts/tests/fixtures/zone_checkpoints.yaml \\
      --out scripts/tests/fixtures/zone_checkpoints_metrics.csv
  --plan: 足りないタイルの枚数だけ数えて終わる（ネットワークに出ない）。
"""
import argparse
import csv
import pathlib
import sqlite3
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import ROOT, PROC, RAW, DB
import regions
import terrain_lib as T
from registry import zone_rule

SID = "gsi_dem_terrain"
TILE_URL = "https://cyberjapandata.gsi.go.jp/xyz/dem_png/{z}/{x}/{y}.png"
TILE_CACHE = RAW / "gsi_dem_png"
COAST_GEOJSON = PROC / "nlni_c23_coastline.geojson"
ZONE_YAML = zone_rule.ZONE_YAML
REGION_YAML = zone_rule.REGION_YAML
MANIFESTS = ROOT / "manifests"
OUT_DEFAULT = PROC / "terrain_points.csv"
DEFAULT_REGION = "jp-14"
SUMMIT_RADIUS_M = 500.0
SUMMIT_TOL_M = 20.0

COLUMNS = ["lat", "lon", "region_id", "summit_m", "elevation_m", "relief_wide_m", "relief_near_m",
           "floor_min_m", "coast_dist_m", "params_digest"]
CHECK_COLUMNS = ["name", "region_id", "lat", "lon", "expect", "known_miss"] + COLUMNS[3:]


# ---------- 入力 ----------
def load_terrain(zone_yaml):
    try:
        return zone_rule.load_terrain(zone_yaml)
    except zone_rule.ZoneRuleError as e:
        raise SystemExit(str(e)) from e


def load_summits(region_yaml):
    """{region_id: {name_ja, lat, lon, elevation_m}}。terrain.summit を宣言した region だけ（形の検査は migrate/regions.py）。"""
    try:
        return zone_rule.load_region_summit_decls(region_yaml)
    except zone_rule.ZoneRuleError as e:
        raise SystemExit(str(e)) from e


def region_of_source(source_id, default_region, manifests=MANIFESTS):
    p = pathlib.Path(manifests) / f"{source_id}.yml"
    if p.exists():
        r = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("region")
        if r:
            return r
    # マニフェストが無い出典（sites の出典）は名前の slug から引く。引けなければ既定
    return regions.region_of_source_id(source_id) or default_region


def sites_points(db_path, default_region, manifests=MANIFESTS):
    """台帳の sites（elevation_m IS NOT NULL）→ [{lat, lon, region_id}]。座標は小数6桁で重複を1行にまとめる。"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT lat, lon, source_id FROM sites WHERE elevation_m IS NOT NULL "
                           "AND lat IS NOT NULL AND lon IS NOT NULL").fetchall()
    finally:
        con.close()
    by_key = {}
    for lat, lon, sid in rows:
        key = (round(lat, 6), round(lon, 6))
        rid = region_of_source(sid, default_region, manifests)
        if by_key.setdefault(key, rid) != rid:
            raise SystemExit(f"同じ座標 {key} が別の region の出典にある: {by_key[key]} / {rid}")
    return [{"lat": k[0], "lon": k[1], "region_id": rid} for k, rid in by_key.items()]


def checkpoint_points(path):
    raw = yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8"))
    items = raw["checkpoints"] if isinstance(raw, dict) else raw
    out = []
    for c in items:
        out.append({"name": c["name"], "region_id": c["region"], "lat": round(float(c["lat"]), 6),
                    "lon": round(float(c["lon"]), 6), "expect": "|".join(str(z) for z in c["expect"]),
                    "known_miss": 1 if c.get("known_miss") else 0})
    return out


# ---------- タイル ----------
def tile_path(cache, z, x, y):
    return pathlib.Path(cache) / str(z) / str(x) / f"{y}.png"


def cache_loader(cache):
    def load(z, x, y):
        p = tile_path(cache, z, x, y)
        return p.read_bytes() if p.exists() else None
    return load


def missing_tiles(tiles, cache):
    return sorted(t for t in tiles if not tile_path(cache, *t).exists())


def fetch_tiles(missing, cache):
    """足りないタイルを1枚ずつ取ってキャッシュする（common.get の 1.5 秒間隔）。404 は空ファイル。"""
    from common import get
    for n, (z, x, y) in enumerate(missing, 1):
        p = tile_path(cache, z, x, y)
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = get(TILE_URL.format(z=z, x=x, y=y), timeout=30).content
        except RuntimeError as e:
            if "HTTP 404" not in str(e):
                raise
            data = b""
        p.write_bytes(data)
        if n % 50 == 0 or n == len(missing):
            print(f"  [tiles] {n}/{len(missing)}", flush=True)


# ---------- 計算 ----------
def coast_by_region(geojson_path):
    """{region_id: CoastDistance}。C23 の prefecture_code が region（jp-NN）に対応する。"""
    import json
    from shapely.geometry import shape
    fc = json.loads(pathlib.Path(geojson_path).read_text(encoding="utf-8"))
    groups = {}
    for f in fc["features"]:
        groups.setdefault(f["properties"]["prefecture_code"], []).append(shape(f["geometry"]))
    return {f"jp-{pref}": T.CoastDistance(geoms) for pref, geoms in groups.items()}


def require_coasts(geojson_path, region_ids):
    """C23 の GeoJSON が無い、または地点のある region に海岸線が1本も無ければ止まる
    （黙って進むと全地点の coast_dist_m が空になり、zone 5 が付かない）。"""
    if not pathlib.Path(geojson_path).exists():
        raise SystemExit(f"{geojson_path} が無い。scripts/c36_nlni_c23_coastline.py を先に回すこと")
    coasts = coast_by_region(geojson_path)
    no_coast = sorted(set(region_ids) - set(coasts))
    if no_coast:
        raise SystemExit(f"{geojson_path} に海岸線が無い region がある: {no_coast}（c36 の対象県を確認する）")
    return coasts


def _f(v, nd=2):
    return "" if v is None else f"{v:.{nd}f}"


def compute_rows(points, terrain, summits, store, coasts):
    digest = zone_rule.terrain_params_digest(terrain)
    rows = []
    for p in points:
        lat, lon = p["lat"], p["lon"]
        e, rw, rn, fl = T.point_metrics(store, lon, lat, terrain)
        coast = coasts.get(p["region_id"])
        row = dict(p)
        row.update({
            "lat": f"{lat:.6f}", "lon": f"{lon:.6f}",
            "summit_m": _f(float(summits[p["region_id"]]["elevation_m"])),
            "elevation_m": _f(e), "relief_wide_m": _f(rw), "relief_near_m": _f(rn), "floor_min_m": _f(fl),
            "coast_dist_m": _f(coast.query(lon, lat), 1) if coast else "",
            "params_digest": digest,
        })
        rows.append(row)
    return rows


def write_csv(path, rows, columns):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def sort_key(r):
    return (float(r["lat"]), float(r["lon"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--points", choices=["sites"], default="sites")
    ap.add_argument("--checkpoints", help="確認地点の yaml（指定すると --points は使わない）")
    ap.add_argument("--out", help="出力 CSV（既定: data/processed/terrain_points.csv）")
    ap.add_argument("--zone-yaml", default=str(ZONE_YAML))
    ap.add_argument("--region-yaml", default=str(REGION_YAML))
    ap.add_argument("--coast", default=str(COAST_GEOJSON))
    ap.add_argument("--cache", default=str(TILE_CACHE))
    ap.add_argument("--db", default=str(DB / "ryuiki.sqlite"))
    ap.add_argument("--default-region", default=DEFAULT_REGION)
    ap.add_argument("--plan", action="store_true", help="足りないタイルの枚数だけ数えて終わる")
    ap.add_argument("--no-fetch", action="store_true", help="タイルを取らない（足りなければ止まる）")
    ap.add_argument("--no-register", action="store_true", help="source_registry に登録しない")
    a = ap.parse_args(argv)

    terrain = load_terrain(a.zone_yaml)
    summits = load_summits(a.region_yaml)
    points = checkpoint_points(a.checkpoints) if a.checkpoints else sites_points(a.db, a.default_region)
    no_summit = sorted({p["region_id"] for p in points} - set(summits))
    if no_summit:
        raise SystemExit(f"{a.region_yaml} に terrain.summit が無い region の地点がある: {no_summit}")

    need = set()
    for p in points:
        need |= T.required_tiles(p["lon"], p["lat"], terrain)
    for rid in {p["region_id"] for p in points}:
        need |= T.summit_tiles(summits[rid], terrain["dem_tile_zoom"], SUMMIT_RADIUS_M)
    missing = missing_tiles(need, a.cache)
    print(f"対象 {len(points)} 地点、必要なタイル {len(need)} 枚、足りない {len(missing)} 枚")
    if a.plan:
        return
    if missing:
        if a.no_fetch:
            raise SystemExit(f"タイルが {len(missing)} 枚足りない（--no-fetch）")
        fetch_tiles(missing, a.cache)

    store = T.TileStore(cache_loader(a.cache))
    for rid in sorted({p["region_id"] for p in points}):
        ok, hi = T.check_summit(store, summits[rid], terrain["dem_tile_zoom"], SUMMIT_RADIUS_M, SUMMIT_TOL_M)
        s = summits[rid]
        print(f"最高峰の検査 {rid} {s.get('name_ja')}: 宣言 {s['elevation_m']}m / DEM最大 {hi}m -> {'OK' if ok else 'NG'}")
        if not ok:
            raise SystemExit(f"{rid} の最高峰の宣言値 {s['elevation_m']}m が、周辺{SUMMIT_RADIUS_M:g}mの DEM 最大 {hi} と "
                             f"±{SUMMIT_TOL_M:g}m で合わない（region.yaml の terrain.summit を確認する）")

    coasts = require_coasts(a.coast, {p["region_id"] for p in points})
    rows = sorted(compute_rows(points, terrain, summits, store, coasts), key=sort_key)
    if a.checkpoints:
        write_csv(a.out or "zone_checkpoints_metrics.csv", rows, CHECK_COLUMNS)
    else:
        write_csv(a.out or OUT_DEFAULT, rows, COLUMNS)
    print(f"書いた: {a.out or OUT_DEFAULT} ({len(rows)} 行)")

    if not a.checkpoints and not a.no_register and not a.out:
        from common import register
        register(SID, "国土地理院 標高タイル（DEM10B）から計算した地点の地形指標", "国土交通省国土地理院",
                 "https://maps.gsi.go.jp/development/demtile.html", "地形・標高",
                 "標高タイル (cyberjapandata.gsi.go.jp/xyz/dem_png/{z}/{x}/{y}.png) 直接GET", "CSV",
                 "国土地理院コンテンツ利用規約（公共データ利用規約(PDL1.0)相当、出典表記必須）"
                 " https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html",
                 1, len(rows),
                 "台帳 sites の標高がある座標ごとの標高・周囲の起伏量・周囲の最低標高・海岸線（C23）までの距離。"
                 f"定義パラメータは registry/place/zone.yaml の terrain:（params_digest={zone_rule.terrain_params_digest(terrain)}）。"
                 "標高は dem_png の座標を含む画素、起伏量・最低点は円窓の有効画素から計算。")


if __name__ == "__main__":
    main()
