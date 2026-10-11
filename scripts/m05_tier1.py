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
from common import appdb, PROC, ROOT, now, ensure_column, round_coords
import regions
from regions import REGIONS
from m01_sites import load_watersheds

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
        self.polys, self.props = load_watersheds()   # m01 と同じ読み込み（全地域の流域。無い地域は飛ばす）
        self.tree = STRtree(self.polys)

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

# ---- 奄美の A10・A15・A45（国土数値情報。c32/c33/c35 --region jp-46。Issue #96） ----
# 神奈川の A10・A15・A45 は入れない（神奈川の区域は県の別出典）。geometry は同名の .geojson から持ってくる。
NLNI_PA_NOTE_A10 = ("国土数値情報 A10-15（2015年版）。名称は原データに無い。原データの面積欄は ha でないため使っていない。"
                    "3レイヤは入れ子（自然公園地域 ⊃ 特別地域 ⊃ 特別保護地区）。category_code をまたいで area_ha を足さない")
A10_CODES = {"11": "natpark_area", "12": "natpark_special", "13": "natpark_special_protection"}
A15_CODES = {"鳥獣保護区": "wildlife_reserve", "特別保護地区": "wildlife_special_protection"}

def _pa_geometry(feature):
    """GeoJSON の geometry を座標 6 桁・空白なしの文字列にし、shapely の図形も返す。"""
    g = feature["geometry"]
    g = {"type": g["type"], "coordinates": round_coords(g["coordinates"])}
    return json.dumps(g, ensure_ascii=False, separators=(",", ":")), shape(g)

def _nlni_pa_rows(src, rows, features, make):
    """CSV の行と .geojson の feature を行順・source_ref で突き合わせ、make(r) が返す辞書に代表点・geometry を足す。"""
    if len(rows) != len(features):
        raise SystemExit(f"{src}: CSV {len(rows)} 行と geojson {len(features)} 件が合わない")
    out = []
    for r, f in zip(rows, features):
        if f["properties"].get("source_ref") != r["source_ref"]:
            raise SystemExit(f"{src}: geojson と CSV の source_ref の順序が合わない（{r['source_ref']}）")
        gj, geom = _pa_geometry(f)
        pt = geom.representative_point()
        d = make(r)
        d.update(lon=pt.x, lat=pt.y, geometry_geojson=gj, source_id=src, source_ref=r["source_ref"])
        out.append(d)
    return out

def _code(codes, src, v):
    k = str(v).strip()
    if k not in codes:
        raise SystemExit(f"{src}: 未知の区分 {k!r}（既知: {sorted(codes)}）")
    return codes[k]

def _area_ha(r):
    """測地面積 area_km2 を ha にする（A10 の面積欄は ha でないので使わない）。"""
    km2 = num(r.get("area_km2"))
    return None if km2 is None else km2 * 100

def _make_a10(r):
    return dict(
        area_id=f"nlni_a10_natparks_amami:{r['object_id']}", name_ja=None,
        category_ja=text(r.get("layer_name_ja")), category_code=_code(A10_CODES, "nlni_a10_natparks_amami", r["layer_no"]),
        municipality_ja=text(r.get("municipality_names_ja")),
        area_ha=_area_ha(r), area_ha_raw=None,
        designated_on=None, designated_on_raw=text(r.get("fiscal_year_raw")),
        note_ja=NLNI_PA_NOTE_A10)

def _make_a15(r):
    d, c = text(r.get("designated_date")), text(r.get("cancel_date"))
    return dict(
        area_id=f"nlni_a15_wildlife_amami:{r['feature_id']}", name_ja=text(r.get("name_ja")),
        category_ja=text(r.get("protection_class_ja")), category_code=_code(A15_CODES, "nlni_a15_wildlife_amami", r["protection_class_ja"]),
        municipality_ja=None, area_ha=_area_ha(r), area_ha_raw=None,
        designated_on=d, designated_on_raw=d,
        note_ja=f"A15-09（2009年版）。指定期間 {d or '不明'}〜{c or '不明'}")

def _make_a45(r):
    shp_no = r["source_ref"].rsplit(":", 1)[1]
    name = " ".join(x for x in (text(r.get("national_forest_name_ja")), text(r.get("compartment_label_ja"))) if x) or None
    return dict(
        area_id=f"nlni_a45_forest_amami:{shp_no}", name_ja=name,
        category_ja="国有林", category_code="national_forest", municipality_ja=text(r.get("municipality_name_ja")),
        area_ha=_area_ha(r), area_ha_raw=text(r.get("area_ha_source")),
        designated_on=None, designated_on_raw=None,
        note_ja=(f"A45-19（2018年度版）。機能類型: {text(r.get('function_type_ja')) or '不明'}、"
                 f"林種: {text(r.get('forest_subtype_ja')) or '不明'}。小班IDは複数行に重複する"))

NLNI_PA_SOURCES = [("nlni_a10_natparks_amami", _make_a10), ("nlni_a15_wildlife_amami", _make_a15),
                   ("nlni_a45_forest_amami", _make_a45)]

def load_protected_areas_nlni(con, ws, sources=NLNI_PA_SOURCES):
    """奄美の A10 自然公園・A15 鳥獣保護区・A45 国有林（c32/c33/c35 --region jp-46）。出典ごとに wipe→検査→INSERT。

    lat/lon は区域の代表点（重心だと細長い区域で区域の外・海上に落ちる）。area_ha は測地面積 area_km2×100。
    area_id が他の出典と衝突したら止める。CSV が1つも無ければ None。"""
    msgs = []
    for src, make in sources:
        rows = read_csv(src)
        if rows is None:
            continue
        bad = sorted({r["source_id"] for r in rows} - {src})
        if bad:
            raise SystemExit(f"{src}: CSV の source_id が {bad} （期待 {src}）")
        gp = PROC / f"{src}.geojson"
        if not gp.exists():
            raise SystemExit(f"{src}: {gp.name} が無い（geometry が取れない）")
        feats = json.loads(gp.read_text(encoding="utf-8"))["features"]
        recs = _nlni_pa_rows(src, rows, feats, make)
        ids = [d["area_id"] for d in recs]
        if len(set(ids)) != len(ids):
            raise SystemExit(f"{src}: area_id が出典の中で重複している")
        _assert_no_id_collision(con, "protected_areas", "area_id", src, ids, "他の出典")
        for d in recs:
            d["watershed"] = ws.find(d["lon"], d["lat"])
        wipe(con, "protected_areas", [src])
        con.executemany(
            """INSERT OR REPLACE INTO protected_areas
               (area_id,name_ja,category_ja,category_code,municipality_ja,area_ha,area_ha_raw,
                designated_on,designated_on_raw,lat,lon,watershed,zone,note_ja,source_id,source_ref,geometry_geojson)
               VALUES (:area_id,:name_ja,:category_ja,:category_code,:municipality_ja,:area_ha,:area_ha_raw,
                :designated_on,:designated_on_raw,:lat,:lon,:watershed,NULL,:note_ja,:source_id,:source_ref,:geometry_geojson)""",
            recs)
        inws = sum(1 for d in recs if d["watershed"])
        msgs.append(f"protected_areas[{src}]: {len(recs)} 行 (流域が引けた {inws})")
    return "; ".join(msgs) if msgs else None

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

def _assert_no_id_collision(con, table, id_col, src, ids, label):
    """他の出典の行と主キーが衝突したら止める（INSERT OR REPLACE が黙って上書きするため。入れる前に調べる）。"""
    ids = sorted(set(ids))
    dup = set()
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        marks = ",".join("?" for _ in chunk)
        dup.update(x for (x,) in con.execute(
            f"SELECT {id_col} FROM {table} WHERE source_id != ? AND {id_col} IN ({marks})", (src, *chunk)))
    if dup:
        raise SystemExit(f"{src}: {table}.{id_col} が{label}の行と衝突している（{len(dup)} 件、例: {sorted(dup)[:3]}）")

def load_vegetation(con, ws, rid=regions.DEFAULT_REGION):
    """現存植生図2024 (c80_biodic_ikimonomap.py)。地域ごとに呼ぶ。

    feature_id は表の主キー。他の地域の行と衝突すると INSERT OR REPLACE が黙って上書きするので、
    衝突したら止める（入れる前に調べる）。同じ出典の中の重複は従来どおり INSERT OR REPLACE が吸収する。"""
    src = regions.name("biodic_veg2024_kanagawa", rid)
    rows = read_csv(src)
    if rows is None:
        return None
    wipe(con, "vegetation_polygons", [src])
    _assert_no_id_collision(con, "vegetation_polygons", "feature_id", src, [r["feature_id"] for r in rows], "他の地域")
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
    return f"vegetation_polygons[{src}]: {len(out)} 行 (流域が引けた {inws})"

def load_hazard_zones(con, ws, rid="jp-46"):
    """土砂災害警戒区域・特別警戒区域 (c103b_a33_hazard_zones.py)。

    zone_id は表の主キー。他の出典の行と衝突すると INSERT OR REPLACE が黙って上書きするので、衝突したら止める。
    流域は代表点が W12 に入った行だけ（海岸近くは W12 が覆っていないので NULL が残る）。"""
    src = regions.name("bodik_kagoshima_dosha", rid)
    rows = read_csv(src)
    if rows is None:
        return None
    wipe(con, "hazard_zones", [src])
    ids = [r["zone_id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise SystemExit(f"{src}: zone_id が出典の中で重複している")
    _assert_no_id_collision(con, "hazard_zones", "zone_id", src, ids, "他の出典")
    bad = sorted({r["source_id"] for r in rows} - {src})
    if bad:
        raise SystemExit(f"{src}: CSV の source_id が {bad} （期待 {src}）")
    out = []
    for r in rows:
        lat, lon = num(r.get("centroid_lat")), num(r.get("centroid_lon"))
        out.append((
            r["zone_id"], text(r.get("site_code")), text(r.get("site_name_ja")),
            text(r.get("phenomenon_code")), text(r.get("phenomenon_ja")),
            text(r.get("zone_kind_code")), text(r.get("zone_kind_ja")),
            text(r.get("municipality_ja")), text(r.get("locality_ja")), text(r.get("river_name_ja")),
            text(r.get("office_ja")), text(r.get("designated_on")), text(r.get("designated_on_raw")),
            text(r.get("notice_no_raw")), num(r.get("area_m2")), lat, lon, ws.find(lon, lat),
            text(r.get("geometry_geojson")), src, text(r.get("source_ref")),
        ))
    con.executemany(
        """INSERT OR REPLACE INTO hazard_zones
           (zone_id,site_code,site_name_ja,phenomenon_code,phenomenon_ja,zone_kind_code,zone_kind_ja,
            municipality_ja,locality_ja,river_name_ja,office_ja,designated_on,designated_on_raw,notice_no_raw,
            area_m2,centroid_lat,centroid_lon,watershed,geometry_geojson,source_id,source_ref)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", out)
    inws = sum(1 for o in out if o[17])
    return f"hazard_zones[{src}]: {len(out)} 行 (流域が引けた {inws})"

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

def build_jobs(con, ws):
    """[(キー, ラベル, 関数)]。キーは --only で指す名前（植生は 'vegetation' で全地域、'vegetation:<rid>' で1地域）。"""
    def csv_job(key, label, src, site_key):
        return (key, label, lambda: load_measurements_csv(con, src, src, site_key=site_key))
    return [
        ("protected_areas", "保護区・緑地台帳",      lambda: load_protected_areas(con, ws)),
        ("protected_areas_amami", "保護区(奄美 国土数値情報)", lambda: load_protected_areas_nlni(con, ws)),
        ("wildlife",        "ツキノワグマ出没記録",  lambda: load_wildlife(con)),
        *[(f"vegetation:{rid}", f"現存植生図2024 ({rid})", lambda rid=rid: load_vegetation(con, ws, rid))
          for rid in REGIONS],
        ("hazard_zones",    "土砂災害警戒区域 (奄美)", lambda: load_hazard_zones(con, ws)),
        ("mammal_mesh",     "哺乳類メッシュ分布",    lambda: load_mammal_mesh(con)),
        ("river_segments",  "相模川水系 流路",       lambda: load_river_segments(con)),
        ("hiratsuka_air",   "平塚市 大気(日別)",     lambda: load_hiratsuka_air(con)),
        csv_job("atsugi", "厚木市 相模川水質", "atsugi_river_water_quality",
                lambda r: text(r.get("site_name_ja"))),
        ("yokohama",        "横浜市 河川水位(日別)", lambda: load_yokohama_waterlevel(con)),
        # 表4 由来の県全体の集計値には観測井戸が無いので、市町名か「県全体」を系列キーにする
        csv_job("jiban", "神奈川県 地盤沈下", "kanagawa_jiban_chinka",
                lambda r: text(r.get("well_id")) or text(r.get("municipality_ja")) or "県全体"),
    ]

def select_jobs(jobs, only):
    """--only の指定（キーかラベル。'vegetation' は 'vegetation:<rid>' 全部）に合うジョブだけ返す。
    指定が無ければ全部。どれにも合わない指定があれば止める。"""
    if not only:
        return jobs
    picked = []
    for name in only:
        hit = [j for j in jobs if name in (j[0], j[1]) or j[0].startswith(name + ":")]
        if not hit:
            raise SystemExit(f"--only {name!r} に合うジョブが無い（キー: {', '.join(j[0] for j in jobs)}）")
        picked += [j for j in hit if j not in picked]
    return [j for j in jobs if j in picked]

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", metavar="KEY",
                    help="指定したジョブだけ回す（キーかラベル。繰り返し可。例: --only hazard_zones）。既定は全部")
    a = ap.parse_args(argv)
    con = appdb()
    con.execute("PRAGMA busy_timeout = 30000")
    ddl = (ROOT / "scripts/schema_tier1.sql").read_text(encoding="utf-8")
    ensure_column(con, "protected_areas", "geometry_geojson", "TEXT")   # 既存の表に列を足してから CREATE IF NOT EXISTS / INDEX を流す
    con.executescript(ddl)
    print("Tier 1 テーブルを用意した")

    ws = Watersheds()
    done, skipped = [], []
    jobs = select_jobs(build_jobs(con, ws), a.only)
    for _key, label, fn in jobs:
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
