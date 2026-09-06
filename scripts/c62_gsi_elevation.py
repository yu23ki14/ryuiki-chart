#!/usr/bin/env python3
"""国土地理院 標高API (getelevation.php) によるグリッド標高取得 + 基盤地図情報の登録状況確認。

担当: 国土地理院 標高API・基盤地図情報 (他ソースには触れない)

1. 標高APIの疎通確認（相模川流域内数点＋no-data確認用の海上点＋範囲外点）
2. 神奈川県相当範囲を 0.01度グリッドで点生成し、既存の
   data/processed/nlni_w12_watersheds.geojson （国土数値情報 流域界、他エージェント成果物）
   の和集合ポリゴンでクリップして「陸域のみ」約3000点に絞り、標高APIを叩く。
   -> data/processed/gsi_elevation_grid.csv / .jsonl
3. 基盤地図情報ダウンロードサービスの利用者登録要否を実ページで確認し、
   登録不要では取得しない（人間の承認なしにアカウント登録はしない）方針のもと
   record_count=0 で登録するのみ。
"""
import sys, json, csv, time
sys.path.insert(0, "scripts")
from common import get_json, register, write_jsonl, PROC, RAW, now

SOURCE_ID = "gsi_elevation_grid"
ELEV_URL = "https://cyberjapandata2.gsi.go.jp/general/dem/scripts/getelevation.php"

# ---------------------------------------------------------------
# 0. 疎通確認（記録用ログ。結果はこのファイルのdocstring/報告に転記済み）
#    139.3,35.55  相模川下流付近      -> elevation=197.4  hsrc=1m（レーザ）
#    139.15,35.45 丹沢山塊付近        -> elevation=1007.4 hsrc=5m（レーザ）
#    139.5,35.3   相模湾海上          -> elevation='-----' hsrc='-----'  (no-data)
#    140.0,36.0   範囲外(茨城沖?)     -> elevation=9.5    hsrc=5m（レーザ） (陸上のため値あり)
# ---------------------------------------------------------------

def fetch_elevation(lon, lat):
    r = get_json(ELEV_URL, params={"lon": lon, "lat": lat, "outtype": "JSON"})
    return r


def build_grid_points(step=0.01):
    """nlni_w12_watersheds.geojson (流域界, 神奈川県全域を覆う) の和集合内に入る
    0.01度グリッド点のみを対象にする。ファイルが無ければ矩形bboxのまま返す。"""
    import numpy as np
    lon0, lon1 = 138.9, 139.8
    lat0, lat1 = 35.1, 35.7
    lons = [round(float(x), 2) for x in np.arange(lon0, lon1 + 1e-9, step)]
    lats = [round(float(y), 2) for y in np.arange(lat0, lat1 + 1e-9, step)]
    all_pts = [(lo, la) for lo in lons for la in lats]

    boundary_path = PROC / "nlni_w12_watersheds.geojson"
    if not boundary_path.exists():
        return all_pts, False, len(all_pts)

    from shapely.geometry import shape, Point
    from shapely.strtree import STRtree
    with open(boundary_path, encoding="utf-8") as f:
        gj = json.load(f)
    geoms = []
    for feat in gj["features"]:
        g = shape(feat["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        geoms.append(g)
    tree = STRtree(geoms)

    pts_in = []
    for lo, la in all_pts:
        p = Point(lo, la)
        idx = tree.query(p)
        for i in idx:
            if geoms[i].intersects(p):
                pts_in.append((lo, la))
                break
    return pts_in, True, len(all_pts)


def main():
    step = 0.01
    pts, clipped, grid_total = build_grid_points(step)
    print(f"grid_total(bbox)={grid_total} clipped_to_land={len(pts)} clipped={clipped}")

    rows = []
    out_jsonl = PROC / f"{SOURCE_ID}.partial.jsonl"
    done = set()
    if out_jsonl.exists():
        with open(out_jsonl, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    done.add((r["lon"], r["lat"]))
                    rows.append(r)
                except Exception:
                    pass
        print(f"resuming: {len(done)} points already fetched")

    fout = open(out_jsonl, "a", encoding="utf-8")
    n_new = 0
    for i, (lon, lat) in enumerate(pts):
        if (lon, lat) in done:
            continue
        source_ref = f"{ELEV_URL}?lon={lon}&lat={lat}&outtype=JSON"
        try:
            resp = fetch_elevation(lon, lat)
            elev_raw = resp.get("elevation")
            hsrc = resp.get("hsrc")
            if elev_raw in ("-----", None, ""):
                elevation_m = None
                elevation_raw = f"no-data (hsrc={hsrc})"
            else:
                elevation_m = float(elev_raw)
                elevation_raw = f"{elev_raw} (hsrc={hsrc})"
        except Exception as e:
            elevation_m = None
            elevation_raw = f"ERROR: {e!r}"
        row = {
            "source_id": SOURCE_ID,
            "source_ref": source_ref,
            "lon": lon,
            "lat": lat,
            "elevation_m": elevation_m,
            "elevation_raw": elevation_raw,
        }
        rows.append(row)
        fout.write(json.dumps(row, ensure_ascii=False) + "\n")
        fout.flush()
        n_new += 1
        if n_new % 100 == 0:
            print(f"  progress: {len(rows)}/{len(pts)} ({now()})")
    fout.close()

    # 最終出力 (CSV/JSONL)
    write_jsonl(SOURCE_ID, rows)
    cols = ["source_id", "source_ref", "lon", "lat", "elevation_m", "elevation_raw"]
    with open(PROC / f"{SOURCE_ID}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    n_nodata = sum(1 for r in rows if r["elevation_m"] is None)
    notes = (
        f"グリッド間隔=0.01度、bbox内候補点数={grid_total}、"
        f"data/processed/nlni_w12_watersheds.geojson(国土数値情報流域界,他エージェント成果物)の"
        f"和集合ポリゴンでクリップして陸域相当のみ{len(pts)}点を対象に取得(clipped={clipped})。"
        f"取得試行{len(rows)}点中no-data(海上等){n_nodata}点はelevation_m=null。"
        "no-dataはAPIレスポンスelevation='-----'を検出して判定。"
    )
    register(
        source_id=SOURCE_ID,
        name="国土地理院 標高API グリッド取得（神奈川県相当範囲）",
        publisher="国土交通省国土地理院",
        url="https://maps.gsi.go.jp/development/elevation_s.html",
        category="地形・標高",
        access_method="標高API (cyberjapandata2.gsi.go.jp/general/dem/scripts/getelevation.php) 直接GET",
        fmt="CSV/JSONL",
        license_="国土地理院コンテンツ利用規約（公共データ利用規約(PDL1.0)相当、出典表記必須）"
                 " https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html",
        redistributable=1,
        record_count=len(rows),
        notes=notes,
    )
    print(f"done: {len(rows)} rows, no-data={n_nodata}")


if __name__ == "__main__":
    main()
