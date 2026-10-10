"""アプリDB sites テーブルの構築（要求定義書 §6 観測地点）。

方針:
- lat/lon を持つ地点のみ登録する（そらまめ君・相模原市大気局・県民参加型調査地点は
  収集データに座標が無いため sites には入れない。センサー時系列側で扱う）。
- watershed: nlni_w12_watersheds.geojson (377単位流域ポリゴン) に対する点内判定。
- zone (Ridge to Reef 1-5): ここでは書かない（NULL）。v2 の定義（地形指標による操作的区分。
  公式区分ではない。docs/ZONE_DEFINITION.md・registry/place/zone.yaml）では、座標から
  scripts/c68_gsi_dem_terrain.py が計算した data/processed/terrain_points.csv を
  scripts/m09_site_zone.py が読んで sites.zone を更新する。m01 の再実行は既存の sites.zone を保持する
  （UPSERT。新しい地点だけ NULL。新しい地点があれば続けて m09 を回す。順序: c36 → c68 → m01 → m09 → r01）。
- 標高: 気象庁アメダスは自己申告値をそのまま使用。それ以外は国土地理院 標高API を
  1.5秒スロットルで叩く（common.get 経由）。結果はキャッシュして再実行時に節約する。
- treatment（対策区/対照区/参照）: 公開データに存在しないため一律 NULL。
- 冪等性: site_id を主キーに UPSERT（zone 列は上書きしない）。DROP/DELETE は行わない。

再実行可能（同じ site_id を上書きするだけで重複しない）。
"""
import sys, pathlib, json, re
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import appdb, PROC, get, now
import regions
from regions import REGIONS

from shapely.geometry import shape, Point

# bbox（lon_min, lat_min, lon_max, lat_max）は regions.REGIONS[rid]["bbox"]（地域ごと）

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
    """全地域の W12 を連結して読む（無い地域は飛ばす。W12 が覆わない点は流域 NULL）。"""
    paths = regions.w12_paths(PROC, missing_ok=True)
    if not paths:
        raise SystemExit("W12 の geojson が1つも無い（data/processed/nlni_w12_watersheds*.geojson）")
    polys, props = [], []
    for path in paths:
        gj = json.load(open(path, encoding="utf-8"))
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

SITES_COLUMNS = ("site_id", "name", "name_en", "watershed", "zone", "lat", "lon", "elevation_m", "geohash",
                 "municipality", "muni_code", "treatment", "established_on", "operator",
                 "source_id", "source_ref", "is_synthetic")
# 再実行で既存の sites.zone を消さない（INSERT OR REPLACE は zone=NULL を書いて m09 の結果を捨てる）。
# 新しい地点は zone=NULL のまま（m09_site_zone.py が付ける）。zone 以外の列は上書きする。
# treatment も同様（s01_synthetic.py が合成12地点に書く。本スクリプトは常に NULL を渡すので上書きさせない）。
UPSERT_SITES_SQL = (
    f"INSERT INTO sites ({', '.join(SITES_COLUMNS)}) VALUES ({','.join('?' * len(SITES_COLUMNS))}) "
    "ON CONFLICT(site_id) DO UPDATE SET "
    + ", ".join(f"{c}=excluded.{c}" for c in SITES_COLUMNS if c not in ("site_id", "zone", "treatment"))
)


# 地域ごとに同じ形で持つ観測局の出典（キーは神奈川の出典名。他の地域は regions.name が slug に置換する）。
# main() の取り込みと、自己修復の対象（managed_sources）が同じ組を共有する。
#   elevation(r, fetch): 標高。気象庁は自己申告値をそのまま、環境省は国土地理院の標高 API（fetch()）
#   municipality: 市区町村欄に入れる列名 / established_on(r): 設置日欄 / note: 件数表示に添える断り
REGIONAL_STATION_SOURCES = {
    "jma_stations_kanagawa": {
        "elevation": lambda r, fetch: r.get("elevation_m"),
        "municipality": "prefecture_ja",
        "established_on": lambda r: None,
        "note": "elevation_m は自己申告値をそのまま使用",
    },
    "env_kousui_stations_kanagawa": {
        "elevation": lambda r, fetch: fetch(),
        "municipality": "water_body_ja",
        "established_on": lambda r: str(r["nendo_from"]) if r.get("nendo_from") else None,
        "note": "established_onは観測開始年度=nendo_from。物理的な設置日ではない",
    },
}


def main():
    conn = appdb()
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    publishers = get_publishers(conn)

    # 自己修復: 過去の本スクリプト実行で lat=-1/lon=-1 等のセンチネル値を誤って
    # site として登録してしまった行があれば削除する（本スクリプトが書き込むsource_idの範囲のみ、
    # 他エージェントのデータには触れない）。
    managed_sources = tuple(regions.name(b, rid) for rid in REGIONS
                            for b in REGIONAL_STATION_SOURCES) + (
                        "dams_kanagawa", "sagami_livecams", "moni1000_sites") + tuple(
                        s for s in (regions.kasen_stations_source(rid) for rid in REGIONS) if s)
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

    def add_site(site_id, name, name_en, lat, lon, elevation_m, municipality,
                 established_on, operator, source_id, source_ref, rid=regions.DEFAULT_REGION):
        nonlocal orphan_watershed, outside_bbox
        if lat is None or lon is None:
            return False
        # 環境省 公共用水域データ等で lat=-1,lon=-1 が「座標未登録」のセンチネル値として
        # 使われているのを確認済み（34局）。日本国内であれば lat/lon は必ず正なので、
        # 非正の値は欠損として扱う（実在しない座標を site として登録しない）。
        if lat <= 0 or lon <= 0:
            return False
        if not regions.in_bbox(REGIONS[rid]["bbox"], lat, lon):
            outside_bbox += 1
        ws = find_watershed(lon, lat, polys, props)
        if ws is None:
            orphan_watershed += 1
        zone = None  # zone は m09_site_zone.py が terrain_points.csv から付ける（AMAMI_STEP0 §3）
        gh = geohash_encode(lat, lon)
        rows.append((
            site_id, name, name_en, ws, zone, lat, lon, elevation_m, gh,
            municipality, None, None, established_on, operator,
            source_id, source_ref, 0,
        ))
        return True

    # ---- 1) 気象庁アメダス / 2) 環境省 公共用水域 水質測定点（地域ごと。ファイルが無い地域は飛ばす） ----
    for rid in REGIONS:
        for base, spec in REGIONAL_STATION_SOURCES.items():
            src = regions.name(base, rid)
            n = 0
            for r in rd_jsonl(src):
                if add_site(f"{src}__{r['station_id']}", r["station_name_ja"], r.get("station_name_en"),
                            r["lat"], r["lon"], spec["elevation"](r, lambda: fetch_elevation(r["lat"], r["lon"], elev_cache, api_calls)),
                            r.get(spec["municipality"]), spec["established_on"](r), publishers.get(src),
                            src, r["source_ref"], rid):
                    n += 1
            print(f"  {src}: {n} sites ({spec['note']})")

    # ---- 2b) 鹿児島県 河川砂防情報システムの局（座標のある局だけ。無い局は add_site が飛ばし、
    #          registry/place/site_supplement.csv に載せる〔scripts/registry/gen_site_supplement_kasen.py〕。ファイルが無い地域は飛ばす） ----
    for rid in REGIONS:
        src = regions.kasen_stations_source(rid)
        if not src:
            continue
        n = rows_n = 0
        for r in rd_jsonl(src):
            rows_n += 1
            if add_site(f"{src}__{r['station_id']}", r["station_name_ja"], None, r.get("lat"), r.get("lon"),
                        None, r.get("municipality"), None, publishers.get(src), src,
                        r.get("source_ref") or src, rid):
                n += 1
        print(f"  {src}: {n} sites / 局の表 {rows_n} 行（座標の無い局は sites に入れない。標高は取らない）")

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

    conn.executemany(UPSERT_SITES_SQL, rows)
    conn.commit()

    n_sites = conn.execute("select count(*) from sites").fetchone()[0]
    print(f"\n  TOTAL sites inserted/updated this run: {len(rows)}; table now has {n_sites} rows")
    print(f"  GSI elevation API calls made this run: {api_calls[0]} (cap={ELEV_CAP})")
    print(f"  orphan watershed (no polygon matched): {orphan_watershed}")
    print(f"  outside region bbox: {outside_bbox}")
    print(f"  座標が無いため sites に入れなかったソース: {skipped_no_latlon}")
    conn.close()

if __name__ == "__main__":
    main()
