"""e-Stat 統計GIS 小地域境界（2020年国勢調査 町丁・字等別）神奈川県 → GeoJSON/CSV

水道水の水源マップ（docs/WATER_SOURCE_MAP.md）の `zone`。
配水区の割付単位はこの町丁目ポリゴンで、KEY_CODE をそのまま主キーに使う。

取得経路:
  https://www.e-stat.go.jp/gis/statmap-search/data?dlserveyId=A002005212020&code=14
    &coordSys=1&format=shape&downloadType=5
  appId 登録もログインも要らずに 200 が返ることを確認済み（c64 と同じ性質の口）。
  coordSys=1 は世界測地系緯度経度。downloadType=5 は Shapefile。

出力:
  data/processed/estat_shozaiki_kanagawa.geojson  表示用（simplify 済み）
  data/processed/estat_shozaiki_kanagawa.csv      属性のみ（ジオメトリ無し）

simplify について:
  ポリゴンごとに shapely の simplify(preserve_topology=True) を掛ける。隣接ポリゴンの
  共有辺は別々に間引かれるので、拡大すると隙間・重なりが出る。閾値は「その隙間が
  実用ズームで見えない大きさ」で決める。--tolerance-report で候補ごとの実測を出せる。
  原形は data/raw/ の Shapefile に残るので、後で PMTiles に切り替えるときはそちらから作る。

KEY_CODE の重複について:
  飛び地や河川で分断された町丁目は、原本では 1 KEY_CODE が複数レコードに分かれて入っている
  （神奈川県で 273 件）。地図では 1 つの町丁目として扱いたいので MultiPolygon に束ねる。
  面積・重心は束ねた後のジオメトリから計算する。
"""
import sys, pathlib, zipfile, argparse
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import RAW, PROC, get, register, write_jsonl
from nlni_lib import read_shp, geod_area_km2, write_geojson, write_csv

from shapely.geometry import shape as shp_shape, mapping

SID = "estat_shozaiki_kanagawa"
PAGE = ("https://www.e-stat.go.jp/gis/statmap-search?page=1&type=2&aggregateUnitForBoundary=A"
        "&toukeiCode=00200521&serveyId=A002005212020&prefCode=14&coordsys=1&format=shape")
DATA = ("https://www.e-stat.go.jp/gis/statmap-search/data"
        "?dlserveyId=A002005212020&code=14&coordSys=1&format=shape&downloadType=5")
ZIP = RAW / SID / "A002005212020DDSWC14.zip"
LICENSE = "政府標準利用規約2.0 (e-Stat 統計GIS 境界データ)"
PUBLISHER = "総務省統計局 (e-Stat 統計地理情報システム)"

# HCODE: 8101=通常の調査区, 8154=水面調査区。水面は居住区域ではないので割付対象から外す。
HCODE_WATER = "8154"


def fetch():
    ZIP.parent.mkdir(parents=True, exist_ok=True)
    if ZIP.exists() and ZIP.stat().st_size > 0:
        print(f"  [cache] {ZIP.relative_to(RAW.parent.parent)}")
    else:
        r = get(DATA, stream=True)
        with open(ZIP, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
        print(f"  [get] {ZIP.name} {ZIP.stat().st_size/1e6:.1f} MB")
    with zipfile.ZipFile(ZIP) as z:
        z.extractall(ZIP.parent)
    shp = next(ZIP.parent.glob("*.shp"))
    return shp


def merge_by_key(rows):
    """同じ KEY_CODE の複数レコードを 1 つの MultiPolygon に束ねる。属性は最初のものを採る。"""
    from shapely.ops import unary_union
    by_key = {}
    for r in rows:
        by_key.setdefault(r["key_code"], []).append(r)
    out = []
    for key, group in by_key.items():
        head = dict(group[0])
        if len(group) > 1:
            head["geom"] = unary_union([g["geom"] for g in group])
            head["parts"] = len(group)
            # 人口・世帯は分割レコードそれぞれに入っているので足す
            for col in ("jinko", "setai"):
                vals = [g[col] for g in group if isinstance(g[col], (int, float))]
                head[col] = sum(vals) if vals else head[col]
        else:
            head["parts"] = 1
        out.append(head)
    return out


def load(shp):
    r, fields, recs, enc = read_shp(shp)
    print(f"  fields={fields}")
    print(f"  {len(recs)} features, dbf encoding={enc}")
    idx = {name: i for i, name in enumerate(fields)}
    out = []
    for sh, rc in zip(r.shapes(), recs):
        g = shp_shape(sh.__geo_interface__)
        if g.is_empty:
            continue
        if not g.is_valid:
            g = g.buffer(0)
        get_ = lambda k: (rc[idx[k]] if k in idx else None)  # noqa: E731
        out.append({
            "key_code": str(get_("KEY_CODE") or "").strip(),
            "muni_code": (str(get_("PREF") or "") + str(get_("CITY") or ""))[-5:],
            "pref_name": get_("PREF_NAME"),
            "city_name": get_("CITY_NAME"),
            "s_name": get_("S_NAME"),
            "hcode": str(get_("HCODE") or "").strip(),
            "jinko": get_("JINKO"),
            "setai": get_("SETAI"),
            "geom": g,
        })
    return out


def simplify_report(rows, tolerances):
    """候補の許容誤差ごとに、書き出しサイズと最大ずれを実測して出す。"""
    import json
    print("\n  tolerance   概算サイズ   ≒距離   備考")
    for tol in tolerances:
        feats = [{"type": "Feature",
                  "geometry": mapping(r["geom"].simplify(tol, preserve_topology=True) if tol else r["geom"]),
                  "properties": {"key_code": r["key_code"]}} for r in rows]
        size = len(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False).encode())
        m = tol * 111_000  # 緯度1度≒111km。経度は緯度35度で約0.82倍なので上振れ見積り
        print(f"  {tol:<11} {size/1e6:8.1f} MB {m:7.1f} m")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tolerance", type=float, default=0.00005,
                    help="simplify の許容誤差（度）。0 で簡略化しない。既定 0.00005 ≒ 5m")
    ap.add_argument("--tolerance-report", action="store_true",
                    help="候補ごとのサイズを測って終わる（書き出さない）")
    args = ap.parse_args()

    shp = fetch()
    rows = load(shp)

    water = [r for r in rows if r["hcode"] == HCODE_WATER]
    zones = [r for r in rows if r["hcode"] != HCODE_WATER]
    print(f"  水面調査区 (HCODE={HCODE_WATER}) を除外: {len(water)} → 割付対象 {len(zones)}")

    dup = len(zones) - len({r["key_code"] for r in zones})
    zones = merge_by_key(zones)
    print(f"  KEY_CODE 重複 {dup} 件を MultiPolygon に統合 → 町丁目 {len(zones)}")

    if args.tolerance_report:
        simplify_report(zones, [0, 0.00002, 0.00005, 0.0001, 0.0002, 0.0005])
        return

    features, attrs = [], []
    for r in zones:
        g = r["geom"].simplify(args.tolerance, preserve_topology=True) if args.tolerance else r["geom"]
        if g.is_empty:
            g = r["geom"]
        c = r["geom"].centroid
        props = {
            "key_code": r["key_code"],
            "muni_code": r["muni_code"],
            "city_name": r["city_name"],
            "s_name": r["s_name"],
            "name": f"{r['city_name'] or ''}{r['s_name'] or ''}",
        }
        features.append({"type": "Feature", "geometry": mapping(g), "properties": props})
        attrs.append({**props,
                      "pref_name": r["pref_name"],
                      "parts": r["parts"],
                      "hcode": r["hcode"],
                      "jinko": r["jinko"],
                      "setai": r["setai"],
                      "area_km2": geod_area_km2(r["geom"]),
                      "centroid_lat": round(c.y, 6),
                      "centroid_lon": round(c.x, 6)})

    write_geojson(SID, features,
                  crs_note=f"simplify tolerance={args.tolerance} deg (preserve_topology)")
    write_csv(SID, attrs)
    write_jsonl(SID, attrs)
    register(SID, "2020年国勢調査 小地域（町丁・字等別）境界データ 神奈川県",
             PUBLISHER, PAGE, "boundary", "http", "shapefile", LICENSE, 1, len(attrs),
             notes=f"downloadType=5 (Shapefile, 世界測地系緯度経度)。"
                   f"HCODE={HCODE_WATER} の水面調査区 {len(water)} 件を除外。"
                   f"分断された町丁目 {dup} レコードを KEY_CODE で MultiPolygon に統合。"
                   f"表示用 GeoJSON は simplify tolerance={args.tolerance} 度。")


if __name__ == "__main__":
    main()
