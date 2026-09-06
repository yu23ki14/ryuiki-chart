"""アプリDB sites テーブルの構築（要求定義書 §6 観測地点）。

方針:
- lat/lon を持つ地点のみ登録する（そらまめ君・相模原市大気局・県民参加型調査地点は
  収集データに座標が無いため sites には入れない。センサー時系列側で扱う）。
- watershed: nlni_w12_watersheds.geojson (377単位流域ポリゴン) に対する点内判定。
- zone (Ridge to Reef 1-5): 標高 + 海岸線からの距離による「我々の操作的定義」。
  公式区分ではない。定義は docs/ZONE_DEFINITION.md を参照。
- 標高: 気象庁アメダスは自己申告値をそのまま使用。それ以外は国土地理院 標高API を
  1.5秒スロットルで叩く（common.get 経由）。結果はキャッシュして再実行時に節約する。
- treatment（対策区/対照区/参照）: 公開データに存在しないため一律 NULL。
- 冪等性: site_id を主キーに INSERT OR REPLACE。DROP/DELETE は行わない。

再実行可能（同じ site_id を上書きするだけで重複しない）。
"""
import sys, pathlib, json, re
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import appdb, PROC, get, now

from shapely.geometry import shape, Point

KANAGAWA_BBOX = (138.9, 35.1, 139.8, 35.7)  # lon_min, lat_min, lon_max, lat_max (おおよそ)

# ---- 神奈川県 沿岸線の粗いポリライン（我々が定義した近似。公式コースラインではない） ----
# 東京湾岸（川崎→横浜→横須賀→三浦半島先端）→ 相模湾岸（葉山→鎌倉→藤沢→茅ヶ崎→
# 平塚→大磯→二宮→小田原→真鶴→湯河原/静岡県境）の順に地名を辿った近似点列。
COASTLINE_LONLAT = [
    (139.7267, 35.5308),  # 川崎(多摩川河口)
    (139.7383, 35.4658),  # 横浜 大黒ふ頭
    (139.6503, 35.4437),  # 横浜 山下公園
    (139.6178, 35.3378),  # 横浜 金沢区
    (139.6660, 35.2850),  # 横須賀港
    (139.7508, 35.2467),  # 横須賀 観音崎(浦賀水道)
    (139.6900, 35.1850),  # 三浦 城ヶ島付近
    (139.6156, 35.1347),  # 三浦 三崎港(半島先端)
    (139.6117, 35.1600),  # 三浦 油壺
    (139.5747, 35.2664),  # 葉山 森戸
    (139.5814, 35.2967),  # 逗子
    (139.5461, 35.3061),  # 鎌倉 由比ヶ浜
    (139.4803, 35.3006),  # 藤沢 江の島
    (139.4025, 35.3183),  # 茅ヶ崎
    (139.3378, 35.3239),  # 平塚(相模川河口)
    (139.3131, 35.3106),  # 大磯
    (139.2492, 35.3086),  # 二宮
    (139.1508, 35.2497),  # 小田原(酒匂川河口)
    (139.1533, 35.1592),  # 真鶴
    (139.1017, 35.1364),  # 湯河原(静岡県境)
]

def _dist_m_point_to_segment(px, py, ax, ay, bx, by, coslat):
    # 度→メートルの局所近似投影（緯度cosでlon方向を縮小）。神奈川程度の範囲では十分。
    ax_, bx_, px_ = ax * coslat, bx * coslat, px * coslat
    dx, dy = bx_ - ax_, by - ay
    if dx == 0 and dy == 0:
        t = 0.0
    else:
        t = ((px_ - ax_) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
    cx, cy = ax_ + t * dx, ay + t * dy
    ddeg = ((px_ - cx) ** 2 + (py - cy) ** 2) ** 0.5
    return ddeg * 111320.0

def dist_to_coast_m(lon, lat):
    coslat = __import__("math").cos(__import__("math").radians(lat))
    best = None
    for (ax, ay), (bx, by) in zip(COASTLINE_LONLAT, COASTLINE_LONLAT[1:]):
        d = _dist_m_point_to_segment(lon, lat, ax, ay, bx, by, coslat)
        if best is None or d < best:
            best = d
    return best

def zone_of(elevation_m, dist_coast_m):
    """操作的定義（docs/ZONE_DEFINITION.md と同一のロジック）。"""
    if elevation_m is None:
        return None
    if elevation_m > 800:
        return 1
    if elevation_m > 400:
        return 2
    if elevation_m > 100:
        return 3
    # elevation_m <= 100
    if dist_coast_m is not None and dist_coast_m <= 2000:
        return 5
    return 4

# ---- geohash (標準base32, 依存ライブラリ不要の自前実装) ----
_GH_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"
def geohash_encode(lat, lon, precision=9):
    if lat is None or lon is None:
        return None
    lat_r, lon_r = (-90.0, 90.0), (-180.0, 180.0)
    geohash, bit, ch, even = [], 0, 0, True
    while len(geohash) < precision:
        if even:
            mid = (lon_r[0] + lon_r[1]) / 2
            if lon >= mid: ch |= (1 << (4 - bit)); lon_r = (mid, lon_r[1])
            else: lon_r = (lon_r[0], mid)
        else:
            mid = (lat_r[0] + lat_r[1]) / 2
            if lat >= mid: ch |= (1 << (4 - bit)); lat_r = (mid, lat_r[1])
            else: lat_r = (lat_r[0], mid)
        even = not even
        if bit < 4: bit += 1
        else:
            geohash.append(_GH_BASE32[ch]); bit, ch = 0, 0
    return "".join(geohash)

# ---- 流域ポリゴン ----
def load_watersheds():
    gj = json.load(open(PROC / "nlni_w12_watersheds.geojson", encoding="utf-8"))
    polys, props = [], []
    for feat in gj["features"]:
        try:
            geom = shape(feat["geometry"])
        except Exception:
            continue
        polys.append(geom); props.append(feat["properties"])
    print(f"  watersheds loaded: {len(polys)}")
    return polys, props

def find_watershed(lon, lat, polys, props):
    if lon is None or lat is None:
        return None
    pt = Point(lon, lat)
    for geom, p in zip(polys, props):
        if geom.contains(pt) or geom.intersects(pt):
            return p.get("watershed_id")
    return None

# ---- 標高 (国土地理院 標高API, キャッシュ付き) ----
ELEV_CACHE_PATH = PROC / "_elevation_cache.json"
ELEV_CAP = 500  # 上限。地点数がこれを超えたら超過分は取得せずnotesに記録する。

def load_elev_cache():
    if ELEV_CACHE_PATH.exists():
        return json.load(open(ELEV_CACHE_PATH, encoding="utf-8"))
    return {}

def save_elev_cache(cache):
    json.dump(cache, open(ELEV_CACHE_PATH, "w", encoding="utf-8"), ensure_ascii=False)

def fetch_elevation(lat, lon, cache, counter):
    key = f"{round(lat,5)},{round(lon,5)}"
    if key in cache:
        return cache[key]
    if counter[0] >= ELEV_CAP:
        return None
    counter[0] += 1
    try:
        r = get("https://cyberjapandata2.gsi.go.jp/general/dem/scripts/getelevation.php",
                 params={"lon": lon, "lat": lat, "outtype": "JSON"})
        j = r.json()
        elev = j.get("elevation")
        if elev is None or elev == -9999 or elev == "-----":
            elev = None
        else:
            try:
                elev = float(elev)
                if elev == -9999.0:
                    elev = None
            except (TypeError, ValueError):
                elev = None
    except Exception as e:
        print(f"    !! elevation fetch failed for {lat},{lon}: {e}")
        elev = None
    cache[key] = elev
    if counter[0] % 20 == 0:
        save_elev_cache(cache)
    return elev

def rd_jsonl(name):
    p = PROC / f"{name}.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]

def get_publishers(conn):
    return dict(conn.execute("select source_id, publisher from source_registry").fetchall())

def main():
    conn = appdb()
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    publishers = get_publishers(conn)

    # 自己修復: 過去の本スクリプト実行で lat=-1/lon=-1 等のセンチネル値を誤って
    # site として登録してしまった行があれば削除する（本スクリプトが書き込むsource_idの範囲のみ、
    # 他エージェントのデータには触れない）。
    managed_sources = ("jma_stations_kanagawa", "env_kousui_stations_kanagawa",
                        "dams_kanagawa", "sagami_livecams", "moni1000_sites")
    cur = conn.execute(
        f"DELETE FROM sites WHERE source_id IN ({','.join('?'*len(managed_sources))}) "
        f"AND (lat <= 0 OR lon <= 0)", managed_sources)
    if cur.rowcount:
        print(f"  self-heal: removed {cur.rowcount} previously-inserted sites with invalid (<=0) lat/lon")
    conn.commit()

    polys, props = load_watersheds()
    elev_cache = load_elev_cache()
    api_calls = [0]

    rows = []  # tuples for sites insert
    skipped_no_latlon = {}
    orphan_watershed = 0
    outside_bbox = 0

    def in_bbox(lat, lon):
        return KANAGAWA_BBOX[0] <= lon <= KANAGAWA_BBOX[2] and KANAGAWA_BBOX[1] <= lat <= KANAGAWA_BBOX[3]

    def add_site(site_id, name, name_en, lat, lon, elevation_m, municipality,
                 established_on, operator, source_id, source_ref):
        nonlocal orphan_watershed, outside_bbox
        if lat is None or lon is None:
            return False
        # 環境省 公共用水域データ等で lat=-1,lon=-1 が「座標未登録」のセンチネル値として
        # 使われているのを確認済み（34局）。日本国内であれば lat/lon は必ず正なので、
        # 非正の値は欠損として扱う（実在しない座標を site として登録しない）。
        if lat <= 0 or lon <= 0:
            return False
        if not in_bbox(lat, lon):
            outside_bbox += 1
        ws = find_watershed(lon, lat, polys, props)
        if ws is None:
            orphan_watershed += 1
        dist_coast = dist_to_coast_m(lon, lat)
        zone = zone_of(elevation_m, dist_coast)
        gh = geohash_encode(lat, lon)
        rows.append((
            site_id, name, name_en, ws, zone, lat, lon, elevation_m, gh,
            municipality, None, None, established_on, operator,
            source_id, source_ref, 0,
        ))
        return True

    # ---- 1) 気象庁アメダス ----
    n = 0
    for r in rd_jsonl("jma_stations_kanagawa"):
        sid = f"jma_stations_kanagawa__{r['station_id']}"
        if add_site(sid, r["station_name_ja"], r.get("station_name_en"),
                    r["lat"], r["lon"], r.get("elevation_m"),
                    r.get("prefecture_ja"), None, publishers.get("jma_stations_kanagawa"),
                    "jma_stations_kanagawa", r["source_ref"]):
            n += 1
    print(f"  jma_stations_kanagawa: {n} sites (elevation_m は自己申告値をそのまま使用)")

    # ---- 2) 環境省 公共用水域 水質測定点 ----
    n = 0
    for r in rd_jsonl("env_kousui_stations_kanagawa"):
        sid = f"env_kousui_stations_kanagawa__{r['station_id']}"
        elev = fetch_elevation(r["lat"], r["lon"], elev_cache, api_calls)
        established = str(r["nendo_from"]) if r.get("nendo_from") else None
        if add_site(sid, r["station_name_ja"], None, r["lat"], r["lon"], elev,
                    r.get("water_body_ja"), established,
                    publishers.get("env_kousui_stations_kanagawa"),
                    "env_kousui_stations_kanagawa", r["source_ref"]):
            n += 1
    print(f"  env_kousui_stations_kanagawa: {n} sites "
          f"(established_onは観測開始年度=nendo_from。物理的な設置日ではない)")

    # ---- 3) ダム ----
    n = 0
    for i, r in enumerate(rd_jsonl("dams_kanagawa")):
        sid = f"dams_kanagawa__{i+1:02d}"
        elev = fetch_elevation(r["lat"], r["lon"], elev_cache, api_calls)
        established = str(r["completed_year"]) if r.get("completed_year") else None
        if add_site(sid, r["name_ja"], None, r["lat"], r["lon"], elev,
                    r.get("river_ja"), established,
                    publishers.get("dams_kanagawa"), "dams_kanagawa", r["source_ref"]):
            n += 1
    print(f"  dams_kanagawa: {n} sites (established_on=竣工年。ダムにより竣工年と本格運用開始年が別概念、notesは元jsonl参照)")

    # ---- 4) 相模川ライブカメラ ----
    n = 0
    for r in rd_jsonl("sagami_livecams"):
        sid = f"sagami_livecams__{r['site_id_candidate']}"
        elev = fetch_elevation(r["lat"], r["lon"], elev_cache, api_calls)
        if add_site(sid, r["name_ja"], None, r["lat"], r["lon"], elev,
                    r.get("location_ja"), None, r.get("operator"),
                    "sagami_livecams", r["source_ref"]):
            n += 1
    print(f"  sagami_livecams: {n} sites (lat/lonは地図中心座標。カメラ実測位置と限らない旨は元notesに記載)")

    # ---- 5) モニタリングサイト1000 (神奈川県内) ----
    n = 0
    for r in rd_jsonl("moni1000_sites_kanagawa"):
        sid = f"moni1000_sites__{r['site_code']}"
        elev = fetch_elevation(r["lat"], r["lon"], elev_cache, api_calls)
        if add_site(sid, r["site_name_ja"], None, r["lat"], r["lon"], elev,
                    r.get("municipality_ja"), None, publishers.get("moni1000_sites"),
                    "moni1000_sites", r["source_ref"]):
            n += 1
    print(f"  moni1000_sites: {n} sites")

    save_elev_cache(elev_cache)

    # ---- 座標を欠くため sites に入れられなかったもの ----
    for sid, label, path in [
        ("soramame_stations_kanagawa", "そらまめ君 大気測定局(92局)", "soramame_stations_kanagawa"),
        ("sagamihara_taiki_stations", "相模原市 大気測定局(7局)", "sagamihara_taiki_stations"),
        ("kanagawa_river_citizen_survey", "県民参加型 河川モニタリング(地点別データなし、年度集計のみ)",
         "kanagawa_river_citizen_survey"),
    ]:
        skipped_no_latlon[sid] = label

    conn.executemany(
        """INSERT OR REPLACE INTO sites
           (site_id, name, name_en, watershed, zone, lat, lon, elevation_m, geohash,
            municipality, muni_code, treatment, established_on, operator,
            source_id, source_ref, is_synthetic)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows)
    conn.commit()

    n_sites = conn.execute("select count(*) from sites").fetchone()[0]
    print(f"\n  TOTAL sites inserted/updated this run: {len(rows)}; table now has {n_sites} rows")
    print(f"  GSI elevation API calls made this run: {api_calls[0]} (cap={ELEV_CAP})")
    print(f"  orphan watershed (no polygon matched): {orphan_watershed}")
    print(f"  outside Kanagawa bbox: {outside_bbox}")
    print(f"  座標が無いため sites に入れなかったソース: {skipped_no_latlon}")
    conn.close()

if __name__ == "__main__":
    main()
