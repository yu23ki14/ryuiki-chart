"""Tier 1 で収集したデータをアプリのデータモデルに流し込む。

docs/UNDATAFIED_TIERS.md の Tier 1 を c80〜c88 で収集した結果
(data/processed/*.csv) を読んで、ryuiki.sqlite に入れる。

方針:
- 測定値のように既存のモデルに収まるものは既存表 (measurements / sensor_timeseries / sites) に入れる。
- 台帳・区域・メッシュのように収まらないものだけ新設表に入れる (DDL は scripts/schema_tier1.sql)。
- 座標を持たない観測局は sites に入れない (m01_sites.py と同じ方針)。時系列側だけで扱う。
- 流域 (watershed) / ゾーン(zone) は座標があるものだけ点内判定で埋める。無い場合は NULL のまま。
  **ジオコーディングで座標を推測しない。**
- 冪等: 各 source_id ぶんを DELETE してから INSERT し直す。原本 CSV が消えたソースは触らない。

収集スクリプトが未実行のソースは黙って飛ばす (どれを飛ばしたかは最後に出す)。
"""
import sys, pathlib, json, csv, sqlite3
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import appdb, PROC, ROOT, now

from shapely.geometry import shape, Point
from shapely import STRtree

csv.field_size_limit(1 << 27)  # geometry_geojson が長い

# ------------------------------------------------------------------ #
# 共通ヘルパ                                                          #
# ------------------------------------------------------------------ #

def read_csv(name):
    """data/processed/<name>.csv を読む。無ければ None。"""
    p = PROC / f"{name}.csv"
    if not p.exists():
        return None
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))

def num(v):
    """空文字・None・数値化できない文字列は None。0 は 0 のまま返す。"""
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None

def integer(v):
    f = num(v)
    return None if f is None else int(f)

def text(v):
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None

# ---- 流域ポリゴン (m01_sites.py と同じ原本。点数が多いので STRtree で引く) ----
class Watersheds:
    def __init__(self):
        gj = json.load(open(PROC / "nlni_w12_watersheds.geojson", encoding="utf-8"))
        self.polys, self.props = [], []
        for feat in gj["features"]:
            try:
                self.polys.append(shape(feat["geometry"]))
            except Exception:
                continue
            self.props.append(feat["properties"])
        self.tree = STRtree(self.polys)
        print(f"  流域ポリゴン: {len(self.polys)}")

    def find(self, lon, lat):
        if lon is None or lat is None:
            return None
        pt = Point(lon, lat)
        for i in self.tree.query(pt):
            if self.polys[i].contains(pt) or self.polys[i].intersects(pt):
                return self.props[i].get("watershed_id")
        return None

def wipe(con, table, source_ids):
    """同じ source_id の行を消してから入れ直す (冪等性)。"""
    if not source_ids:
        return
    qs = ",".join("?" for _ in source_ids)
    con.execute(f"DELETE FROM {table} WHERE source_id IN ({qs})", tuple(source_ids))

# ------------------------------------------------------------------ #
# 各ソースの投入                                                      #
# ------------------------------------------------------------------ #

def load_protected_areas(con, ws):
    """保護区・緑地・保存樹木の台帳 (c82_green_areas.py)。"""
    rows = read_csv("green_areas_all")
    if rows is None:
        return None
    src = sorted({r["source_id"] for r in rows})
    wipe(con, "protected_areas", src)
    out, with_coords = [], 0
    for r in rows:
        lat, lon = num(r.get("lat")), num(r.get("lon"))
        watershed = ws.find(lon, lat)
        if lat is not None:
            with_coords += 1
        out.append((
            r["area_id"], text(r.get("name_ja")), text(r.get("category_ja")),
            text(r.get("category_code")), text(r.get("municipality_ja")),
            num(r.get("area_ha")), text(r.get("area_ha_raw")),
            text(r.get("designated_on")), text(r.get("designated_on_raw")),
            lat, lon, watershed, None, text(r.get("note_ja")),
            r["source_id"], text(r.get("source_ref")),
        ))
    con.executemany(
        """INSERT OR REPLACE INTO protected_areas
           (area_id,name_ja,category_ja,category_code,municipality_ja,area_ha,area_ha_raw,
            designated_on,designated_on_raw,lat,lon,watershed,zone,note_ja,source_id,source_ref)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", out)
    return f"protected_areas: {len(out)} 行 (うち座標あり {with_coords})"

def load_wildlife(con):
    """ツキノワグマ出没・目撃記録 (c81_kanagawa_kuma.py)。"""
    rows = read_csv("kanagawa_kuma_sightings")
    if rows is None:
        return None
    wipe(con, "wildlife_sightings", ["kanagawa_kuma_sightings"])
    out = [(
        r["sighting_id"], "ツキノワグマ", integer(r.get("fiscal_year")),
        text(r.get("observed_on")), text(r.get("observed_on_raw")), text(r.get("observed_time_raw")),
        num(r.get("individual_count")), text(r.get("individual_count_raw")),
        text(r.get("situation_ja")), text(r.get("locality_ja")), text(r.get("area_kind_ja")),
        None, None, None,                       # municipality / lat / lon: 原本に無い
        integer(r.get("is_preliminary")) or 0,
        text(r.get("note_ja")), r["source_id"], text(r.get("source_ref")),
    ) for r in rows]
    con.executemany(
        """INSERT OR REPLACE INTO wildlife_sightings
           (sighting_id,species_ja,fiscal_year,observed_on,observed_on_raw,observed_time_raw,
            individual_count,individual_count_raw,situation_ja,locality_ja,area_kind_ja,
            municipality_ja,lat,lon,is_preliminary,note_ja,source_id,source_ref)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", out)
    undated = sum(1 for r in rows if not text(r.get("observed_on")))
    return f"wildlife_sightings: {len(out)} 行 (日付が確定できなかった行 {undated})"

def load_vegetation(con, ws):
    """現存植生図2024 (c80_biodic_ikimonomap.py)。"""
    rows = read_csv("biodic_veg2024_kanagawa")
    if rows is None:
        return None
    wipe(con, "vegetation_polygons", ["biodic_veg2024_kanagawa"])
    out = []
    for r in rows:
        lat, lon = num(r.get("centroid_lat")), num(r.get("centroid_lon"))
        out.append((
            r["feature_id"], text(r.get("legend_code")), text(r.get("legend_name_ja")),
            text(r.get("veg_division_ja")), num(r.get("naturalness")),
            text(r.get("naturalness_class_ja")), integer(r.get("survey_year")),
            text(r.get("block_ja")), num(r.get("area_m2")), lat, lon,
            ws.find(lon, lat), text(r.get("geometry_geojson")),
            r["source_id"], text(r.get("source_ref")),
        ))
    con.executemany(
        """INSERT OR REPLACE INTO vegetation_polygons
           (feature_id,legend_code,legend_name_ja,veg_division_ja,naturalness,naturalness_class_ja,
            survey_year,block_ja,area_m2,centroid_lat,centroid_lon,watershed,geometry_geojson,
            source_id,source_ref)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", out)
    inws = sum(1 for o in out if o[11])
    return f"vegetation_polygons: {len(out)} 行 (流域が引けた {inws})"

def load_mammal_mesh(con):
    """中大型哺乳類3種のメッシュ分布 (c80_biodic_ikimonomap.py)。"""
    rows = read_csv("biodic_mammal_mesh_kanagawa")
    if rows is None:
        return None
    wipe(con, "mammal_mesh", ["biodic_mammal_mesh_kanagawa"])
    out = [(
        text(r.get("mesh_code")), text(r.get("species")), text(r.get("species_ja")),
        text(r.get("survey_label")), integer(r.get("survey_year")),
        integer(r.get("confirmed")) or 0, num(r.get("lat")), num(r.get("lon")),
        r["source_id"], text(r.get("source_ref")),
    ) for r in rows]
    con.executemany(
        """INSERT INTO mammal_mesh
           (mesh_code,species,species_ja,survey_label,survey_year,confirmed,lat,lon,
            source_id,source_ref) VALUES (?,?,?,?,?,?,?,?,?,?)""", out)
    conf = sum(1 for o in out if o[5])
    return f"mammal_mesh: {len(out)} 行 (確認ありは {conf} 行。残りは「その調査で確認されなかった」という記録)"

def load_river_segments(con):
    """相模川水系の流路 (c83_sagami_river_geojson.py)。"""
    rows = read_csv("geoshape_sagami_river")
    if rows is None:
        return None
    wipe(con, "river_segments", ["geoshape_sagami_river"])
    out = [(
        r["feature_id"], text(r.get("name_ja")), text(r.get("section_type_ja")),
        text(r.get("prefecture_ja")), num(r.get("length_m")),
        num(r.get("start_lat")), num(r.get("start_lon")),
        num(r.get("end_lat")), num(r.get("end_lon")),
        text(r.get("geometry_geojson")), r["source_id"], text(r.get("source_ref")),
    ) for r in rows]
    con.executemany(
        """INSERT OR REPLACE INTO river_segments
           (feature_id,name_ja,section_type,prefecture_ja,length_m,start_lat,start_lon,
            end_lat,end_lon,geometry_geojson,source_id,source_ref)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", out)
    from collections import Counter
    byp = Counter(o[3] for o in out)
    return f"river_segments: {len(out)} 行 (県別 {dict(byp)})"

def load_hiratsuka_air(con):
    """平塚市 大気環境の日別集計 (c85_hiratsuka_taiki.py) -> sensor_timeseries。

    局に座標が無いので sites には入れない (m01_sites.py と同じ方針)。
    日平均が数値にならない項目 (風向 WD は N/NNE/... の文字列) は入れない。
    """
    rows = read_csv("hiratsuka_taiki")
    if rows is None:
        return None
    wipe(con, "sensor_timeseries", ["hiratsuka_taiki"])
    out, skipped = [], 0
    for r in rows:
        mean = num(r.get("daily_mean"))
        if mean is None:          # 風向のような非数値項目、または終日欠測
            skipped += 1
            continue
        site_id = f"hiratsuka_taiki_stations__hiratsuka_{r['station_code']}"
        out.append((site_id, f"{r['item_name_ja']}_日平均", r["obs_date"],
                    mean, text(r.get("unit_ja")), None, "hiratsuka_taiki", 0))
    con.executemany(
        """INSERT INTO sensor_timeseries
           (site_id,datastream,phenomenon_time,result,unit,instrument_id,source_id,is_synthetic)
           VALUES (?,?,?,?,?,?,?,?)""", out)
    return (f"sensor_timeseries(平塚市大気 日平均): {len(out)} 行 "
            f"(日平均が数値にならず入れなかった行 {skipped}: 風向と終日欠測)")

def load_yokohama_waterlevel(con):
    """横浜市 河川水位 (c86) -> sensor_timeseries。

    原本は5分間隔で1,083万行 (CSV 2.4GB / JSONL 3.9GB)。相模川水系ではない隣接下流都市の
    参考データなので、平塚市の大気と同じく**日別集計**にして入れる。

    2026-08-30: 容量が過大なため data/processed/yokohama_river_waterlevel.csv/.jsonl は削除した。
    月次の原本は data/raw/yokohama_river_waterlevel/ (25本, 521MB) に残してあるので、
    再生成が要るときは `.venv/bin/python scripts/c86_ckan_bodik_yokohama.py` を流せば
    ネットワークに出ずに作り直せる (download() が raw のキャッシュを使う)。
    処理済み CSV が無い間、この関数は何もせず飛ばす (既存の投入済みデータは消さない)。

    地点マスタには座標があるが、対象河川が流域外なので sites には入れない。
    """
    p = PROC / "yokohama_river_waterlevel.csv"
    if not p.exists():
        return None
    wipe(con, "sensor_timeseries", ["yokohama_river_waterlevel"])
    # 1行ずつ読んで日別に畳む (全部メモリに載せない)
    # 1,000万行超なので DictReader は使わず列位置で読む
    agg = {}
    n_raw = 0
    with open(p, encoding="utf-8", newline="") as f:
        rd = csv.reader(f)
        head = next(rd)
        i_st, i_at, i_v = head.index("station_id"), head.index("observed_at"), head.index("water_level_m")
        for row in rd:
            n_raw += 1
            try:
                v = float(row[i_v])
            except (ValueError, IndexError):
                continue
            at = row[i_at][:10]
            if len(at) != 10:
                continue
            k = (row[i_st], at)
            a = agg.get(k)
            if a is None:
                agg[k] = [v, v, 1]         # sum, max, n
            else:
                a[0] += v
                if v > a[1]: a[1] = v
                a[2] += 1
    out = []
    for (station_id, day), (sm, mx, n) in agg.items():
        site_id = f"yokohama_river_waterlevel__{station_id}"
        out.append((site_id, "河川水位_日平均", day, sm / n, "m", None,
                    "yokohama_river_waterlevel", 0))
        out.append((site_id, "河川水位_日最高", day, mx, "m", None,
                    "yokohama_river_waterlevel", 0))
    con.executemany(
        """INSERT INTO sensor_timeseries
           (site_id,datastream,phenomenon_time,result,unit,instrument_id,source_id,is_synthetic)
           VALUES (?,?,?,?,?,?,?,?)""", out)
    return (f"sensor_timeseries(横浜市 河川水位 日別): {len(out)} 行 "
            f"(10分値 {n_raw:,} 行を地点×日に畳んだ。日平均と日最高の2系列)")

def load_measurements_csv(con, name, source_id, site_key, variable_col="variable_ja"):
    """縦持ちの水質・沈下量 CSV を measurements に入れる汎用ローダー。

    定量下限 (`<0.5` 等) は value を NULL のままにし、value_raw と detection_flag に残す。
    **0 に潰さない。**

    site_key は行から系列のキーを作る関数。座標が無いので sites 表には入れないが、
    site_id を空にすると derived の meas_daily / meas_year が site_id で GROUP BY するときに
    別々の地点が1系列に潰れてしまう。座標を持たない大気常時監視局と同じ扱いで、
    sites に無い site_id を振っておく (soramame_stations_kanagawa__* と同じ作法)。
    """
    rows = read_csv(name)
    if rows is None:
        return None
    wipe(con, "measurements", [source_id])
    out, below, no_time = [], 0, 0
    for i, r in enumerate(rows):
        measured_on = text(r.get("sampled_on")) or text(r.get("fiscal_year"))
        if measured_on is None:
            # 時点を持たない行は測定値ではない(観測所プロフィール等のメタ情報)。
            # 捨てずに data/processed の CSV には残っている。
            no_time += 1
            continue
        raw = text(r.get("value_raw"))
        val = num(r.get("value"))
        flag = text(r.get("detection_flag"))
        if val is None and raw and raw.lstrip().startswith("<"):
            flag = flag or "<"
            below += 1
        key = site_key(r)
        sid = f"{source_id}__{key}" if key else None
        out.append((
            f"{source_id}__{i:06d}", None, sid, measured_on,
            text(r.get(variable_col)), None, val, raw, text(r.get("unit_ja")),
            None, None, flag, "公開済", None, None, source_id,
            text(r.get("source_ref")), 0,
        ))
    con.executemany(
        """INSERT OR REPLACE INTO measurements
           (measurement_id,event_id,site_id,measured_on,variable,variable_en,value,value_raw,
            unit,method,instrument_id,detection_flag,quality_stage,verified_by,verified_on,
            source_id,source_ref,is_synthetic) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", out)
    n_series = len({o[2] for o in out})
    return (f"measurements({source_id}): {len(out)} 行 / {n_series} 系列 "
            f"(定量下限未満 {below} 行は value=NULL のまま / "
            f"時点を持たずメタ情報とみなして入れなかった行 {no_time})")

# ------------------------------------------------------------------ #

def main():
    con = appdb()
    con.execute("PRAGMA busy_timeout = 30000")
    ddl = (ROOT / "scripts/schema_tier1.sql").read_text(encoding="utf-8")
    con.executescript(ddl)
    print("Tier 1 テーブルを用意した")

    ws = Watersheds()
    done, skipped = [], []

    jobs = [
        ("保護区・緑地台帳",      lambda: load_protected_areas(con, ws)),
        ("ツキノワグマ出没記録",  lambda: load_wildlife(con)),
        ("現存植生図2024",        lambda: load_vegetation(con, ws)),
        ("哺乳類メッシュ分布",    lambda: load_mammal_mesh(con)),
        ("相模川水系 流路",       lambda: load_river_segments(con)),
        ("平塚市 大気(日別)",     lambda: load_hiratsuka_air(con)),
        ("厚木市 相模川水質",     lambda: load_measurements_csv(
            con, "atsugi_river_water_quality", "atsugi_river_water_quality",
            site_key=lambda r: text(r.get("site_name_ja")))),
        ("横浜市 河川水位(日別)", lambda: load_yokohama_waterlevel(con)),
        # 表4 由来の県全体の集計値には観測井戸が無いので、市町名か「県全体」を系列キーにする
        ("神奈川県 地盤沈下",     lambda: load_measurements_csv(
            con, "kanagawa_jiban_chinka", "kanagawa_jiban_chinka",
            site_key=lambda r: (text(r.get("well_id")) or text(r.get("municipality_ja"))
                                or "県全体"))),
    ]
    for label, fn in jobs:
        msg = fn()
        if msg is None:
            skipped.append(label)
            print(f"  - {label}: 収集データが無いので飛ばした")
        else:
            done.append(msg)
            print(f"  + {msg}")

    con.commit()
    print("\n=== 投入結果 ===")
    for m in done:
        print(" ", m)
    if skipped:
        print("未収集のため飛ばした:", "、".join(skipped))
    con.close()

if __name__ == "__main__":
    main()
