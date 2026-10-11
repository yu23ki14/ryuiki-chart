"""地理院 標高タイル（DEM10B の dem_png）から奄美大島の集水域を計算する（Issue #94。設計: docs/plans/AMAMI_WATERSHED_DEM.md）。
W12 の25面（陸の42.5%）に代わる。神奈川は W12 のまま（regions.py の `watershed.method`）。

手順: 陸のタイル（C23 の海岸線から決める。c68 と同じキャッシュ）→ モザイク → 岩礁の除去 → 窪地埋め・D8（pyflwdir）→
海に接する画素ごとの流域 → 面積 A_min 未満の流域を隣へ併合 → ポリゴン化（coverage_simplify）→ W05 の河口から水系名を推定。
出力（W12 と同じ列名＋追加。列は dem_watershed_lib.ROW_KEYS）:
  data/processed/<stem>.geojson   data/processed/<stem>.jsonl      （stem = regions の watershed.stem）
決定的（同じ入力・同じ版でバイト一致）。params_digest は定義パラメータ・pyflwdir の版・モザイクの sha256 から作り、全行に入れる。

使い方（依存は scripts/requirements-dem.txt。ルートの requirements.txt には無い）:
  .venv-dem/bin/python3 scripts/c69_gsi_dem_watersheds.py --plan          # 足りないタイルの枚数だけ数える（ネットワークに出ない）
  .venv-dem/bin/python3 scripts/c69_gsi_dem_watersheds.py                 # 取得（新規タイルのみ）→ 計算 → 書く → 出典を登録
  .venv-dem/bin/python3 scripts/c69_gsi_dem_watersheds.py --check         # 計算し直して検査（§3）。reports/amami_watershed_dem_checks.json
  .venv-dem/bin/python3 scripts/c69_gsi_dem_watersheds.py --check-fresh   # 0=新鮮 / 10=古い / 3=判定不能
  --no-fetch: タイルを取らない（足りなければ止まる）  --no-register: 出典を登録しない
"""
import argparse
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import ROOT, PROC  # noqa: E402
import regions  # noqa: E402
import terrain_lib as T  # noqa: E402
import dem_watershed_lib as L  # noqa: E402
import c68_gsi_dem_terrain as c68  # noqa: E402  （タイルのキャッシュ・取得を共有する）

COAST_GEOJSON = PROC / "nlni_c23_coastline.geojson"
DECLARATIONS = pathlib.Path(__file__).resolve().parent / "migrate" / "dem_watershed_declarations.yaml"
REPORT = ROOT / "reports" / "amami_watershed_dem_checks.json"
EXIT_FRESH, EXIT_STALE, EXIT_UNKNOWN = 0, 10, 3


def watershed_cfg(rid):
    cfg = regions.get(rid).get("watershed")
    if not cfg or cfg.get("method") != "dem":
        raise SystemExit(f"{rid} は regions.py の watershed.method が dem ではない（c69 は DEM で流域を作る地域だけ）")
    return cfg


def read_jsonl(path):
    return [json.loads(line) for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------- 計算 ----------
def compute(cfg, rid, dem, origin, mosaic_sha, mouths, want_upa=False):
    """モザイク → 面・ポリゴン・出力テキスト。純粋に入力から決まる（ファイルに書かない）。"""
    x0, y0 = origin
    z = cfg["dem_zoom"]
    h, w = dem.shape
    row_area = L.row_area_km2(y0, h, z)
    valid, dropped_comp_km2, dropped_comp_n = L.drop_small_components(np.isfinite(dem), row_area, cfg["min_island_km2"])
    lab, pits, upa, flow_version = L.flow_basins(dem, valid, row_area, want_upa=want_upa)
    n = len(pits)
    basin_area = L.basin_areas(lab, row_area, n)
    root_of = L.merge_basins(L.basin_adjacency(lab, n), basin_area, cfg["a_min_km2"])
    pits_rc = np.stack(np.divmod(pits, w), axis=1)
    lab_final, units, dropped_units = L.assemble_units(
        lab, root_of, basin_area, pits_rc, row_area, cfg["a_min_km2"], cfg["min_island_km2"], x0, y0, z,
        id_prefix=f"dem-{regions.get(rid)['slug']}")
    polys = L.labels_to_polygons(lab_final, x0, y0, z, cfg["simplify_px"])
    L.attach_w05(units, mouths, cfg["w05_match_m"])
    digest = L.params_digest(cfg, flow_version, mosaic_sha)
    pairs = L.unit_rows(units, polys, cfg, digest)
    return {
        "units": units, "polys": polys, "digest": digest, "valid": valid, "upa": upa,
        "dropped_components": {"n": dropped_comp_n, "area_km2": dropped_comp_km2}, "dropped_units": dropped_units,
        "jsonl": L.dump_jsonl([r for r, _ in pairs]), "geojson": L.dump_geojson([f for _, f in pairs]),
        "n_basins": n, "origin": origin,
    }


def load_mosaic(cfg, polys, cache):
    tiles = L.required_tiles(polys, cfg["dem_zoom"])
    dem, origin = L.build_mosaic(tiles, c68.cache_loader(cache))
    return dem, origin, L.mosaic_sha256(dem)


# ---------- 検査 ----------
def run_checks(cfg, res, land_polys, mouths, w12_path, out_paths):
    decl = L.load_declarations(DECLARATIONS)
    units, polys = res["units"], res["polys"]
    geoms = [polys[u["id"]] for u in units]
    ids = [u["watershed_id"] for u in units]
    z = cfg["dem_zoom"]
    x0, y0 = res["origin"]
    from shapely.geometry import shape
    w12 = [(f["properties"]["watershed_id"], shape(f["geometry"]))
           for f in json.loads(pathlib.Path(w12_path).read_text(encoding="utf-8"))["features"]]
    cands = L.mouths_with_catchment(mouths, res["upa"], x0, y0, z, cfg["a_min_km2"])
    on_disk = {k: pathlib.Path(p).read_bytes() if pathlib.Path(p).exists() else None for k, p in out_paths.items()}
    checks = {
        "w05_outlet_to_mouth": L.check_outlet_to_mouth(units, mouths, decl),
        "w05_mouth_to_outlet": L.check_mouth_to_outlet(cands, units, decl),
        "land_coverage": L.check_land_coverage(land_polys, geoms, decl),
        "overlap_pairs": L.check_overlap_pairs(geoms, ids, decl),
        "w12_containment": L.check_w12_containment(w12, geoms, decl),
        "outlet_on_coast": L.check_outlet_on_coast(res["valid"], units, decl),
        "dropped_area_km2": L.check_dropped_area(res["dropped_components"]["area_km2"], res["dropped_units"], decl),
        "determinism": L.check_determinism({"geojson": res["geojson"], "jsonl": res["jsonl"]}, on_disk, decl),
        "largest_unit_outlet": L.check_largest_unit_outlet(units, decl),
        "unit_count": L.check_unit_count(units, decl),
    }
    assert set(checks) == set(L.CHECK_NAMES)
    return {"params_digest": res["digest"], "passed": all(c["passed"] for c in checks.values()),
            "checks": {k: checks[k] for k in L.CHECK_NAMES}}


def check_fresh(cfg, polys, cache, jsonl_path):
    """jsonl の params_digest と、いまのモザイク・パラメータから作った指紋が一致するか（流向は計算しない）。"""
    try:
        rows = read_jsonl(jsonl_path)
        dem, _, sha = load_mosaic(cfg, polys, cache)
        digest = L.params_digest(cfg, L.flow_version(), sha)
    except (FileNotFoundError, T.TileNotCached, ImportError) as e:
        print(f"判定不能: {type(e).__name__}: {e}")
        return EXIT_UNKNOWN
    have = {r["params_digest"] for r in rows}
    if have == {digest}:
        print(f"新鮮: params_digest={digest}")
        return EXIT_FRESH
    print(f"古い: ファイル {sorted(have)} / 現在 {digest}（c69 を回し直す）")
    return EXIT_STALE


# ---------- 入口 ----------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="jp-46", choices=sorted(regions.REGIONS))
    ap.add_argument("--plan", action="store_true", help="足りないタイルの枚数だけ数えて終わる")
    ap.add_argument("--no-fetch", action="store_true", help="タイルを取らない（足りなければ止まる）")
    ap.add_argument("--no-register", action="store_true", help="source_registry に登録しない")
    ap.add_argument("--check", action="store_true", help="計算し直して検査する（ファイルは書かない）")
    ap.add_argument("--check-fresh", action="store_true", help="出力が現在の入力・パラメータで作られたか（0/10/3）")
    ap.add_argument("--coast", default=str(COAST_GEOJSON))
    ap.add_argument("--cache", default=str(c68.TILE_CACHE))
    ap.add_argument("--report", default=str(REPORT))
    a = ap.parse_args(argv)

    rid = a.region
    cfg = watershed_cfg(rid)
    out = {"geojson": PROC / f"{cfg['stem']}.geojson", "jsonl": PROC / f"{cfg['stem']}.jsonl"}
    if not pathlib.Path(a.coast).exists():
        raise SystemExit(f"{a.coast} が無い。scripts/c36_nlni_c23_coastline.py を先に回すこと")
    land = L.land_polygons(a.coast, regions.get(rid)["pref_code"])
    tiles = L.required_tiles(land, cfg["dem_zoom"])
    missing = c68.missing_tiles(tiles, a.cache)
    print(f"陸のポリゴン {len(land)} 面、必要なタイル {len(tiles)} 枚、足りない {len(missing)} 枚")
    if a.plan:
        return 0
    if a.check_fresh:
        return check_fresh(cfg, land, a.cache, out["jsonl"])
    if missing:
        if a.no_fetch:
            raise SystemExit(f"タイルが {len(missing)} 枚足りない（--no-fetch）")
        c68.fetch_tiles(missing, a.cache)

    name = regions.name
    mouths = L.w05_mouths(read_jsonl(PROC / f"{name('nlni_w05_rivers', rid)}.jsonl"),
                          read_jsonl(PROC / f"{name('nlni_w05_river_nodes', rid)}.jsonl"))
    dem, origin, sha = load_mosaic(cfg, land, a.cache)
    res = compute(cfg, rid, dem, origin, sha, mouths, want_upa=a.check)
    kinds = {k: sum(1 for u in res["units"] if u["unit_kind"] == k) for k in L.CATEGORY_JA}
    print(f"面 {len(res['units'])}（{kinds}）、流域 {res['n_basins']}、落とした岩礁 {res['dropped_components']['n']} 成分 "
          f"{res['dropped_components']['area_km2']:.2f} km²、落とした面 {res['dropped_units']['n']}、params_digest={res['digest']}")

    if a.check:
        report = run_checks(cfg, res, land, mouths, PROC / f"{name('nlni_w12_watersheds', rid)}.geojson", out)
        rp = pathlib.Path(a.report)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for k, c in report["checks"].items():
            print(f"  [{'OK' if c['passed'] else 'NG'}] {k}: {c['measured']}"
                  + (f" 宣言の無い外れ={c['undeclared_failures']}" if c["undeclared_failures"] else "")
                  + (f" 使われなかった例外={c['declared_exceptions_unused']}" if c["declared_exceptions_unused"] else ""))
        print(f"書いた: {rp}")
        return 0 if report["passed"] else 1

    for k, p in out.items():
        p.write_text(res[k], encoding="utf-8", newline="")
        print(f"書いた: {p} ({p.stat().st_size / 1e6:.2f} MB)")
    if not a.no_register:
        from common import register
        register(cfg["stem"], "国土地理院 標高タイル（DEM10B）から計算した集水域（奄美大島）", "国土交通省国土地理院",
                 "https://maps.gsi.go.jp/development/demtile.html", "地形・標高・流域",
                 "標高タイル (cyberjapandata.gsi.go.jp/xyz/dem_png/{z}/{x}/{y}.png) 直接GET → 窪地埋め・D8 流向（pyflwdir）で計算",
                 "GeoJSON/JSONL",
                 "国土地理院コンテンツ利用規約（公共データ利用規約(PDL1.0)相当、出典表記必須）"
                 " https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html",
                 1, len(res["units"]),
                 f"海に接する画素ごとの流域を面積 {cfg['a_min_km2']} km² 未満は隣へ併合した計算上の集水域であり、公式の流域界ではない。"
                 f"unit_kind（basin/coast_group/island）・merged_share を開示。params_digest={res['digest']}。"
                 "W05 の河口との突き合わせは --check。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
