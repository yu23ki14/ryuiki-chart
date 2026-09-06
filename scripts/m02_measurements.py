"""アプリDB events / measurements / sensor_timeseries の構築。

- sensor_timeseries: 高頻度の機械観測（気象庁アメダス日別・月別、そらまめ君1時間値、
  相模原市大気1時間値）。quality_stage は持たない（スキーマ通り）。
  冪等性: 対象 source_id の既存行を削除してから再投入する（このテーブルは本スクリプトのみが
  書き込む対象であり、他の収集エージェントの source_registry 等には触れない）。
- measurements: 人手が介在する測定（環境省 公共用水域 水質測定：sample=個別採水、
  annual=年度集計値）。sample は (station_id, datetime) 単位で events にまとめ、その下に
  複数変数の measurements をぶら下げる。annual は代表日時が無いため event_id=NULL。
  冪等性: measurement_id / event_id を主キーとして INSERT OR REPLACE。

単位・欠測値は原表記のまま（推測変換しない）。相模原市大気データは unit=NULL のまま。
気象庁の「--」（現象なし）は value=NULL のまま（収集時点で既にNULL化されている）。
"""
import sys, pathlib, json, sqlite3
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import appdb, PROC

def rd_jsonl(name):
    p = PROC / f"{name}.jsonl"
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)

# ============================================================
# 1) sensor_timeseries
# ============================================================
SENSOR_SOURCES = [
    # (jsonl名, site_source_id, サイト側の元IDフィールド)
    ("jma_daily_yokohama", "jma_stations_kanagawa"),
    ("jma_monthly_kanagawa", "jma_stations_kanagawa"),
    ("soramame_hourly_kanagawa", "soramame_stations_kanagawa"),
    ("sagamihara_taiki_hourly", "sagamihara_taiki_stations"),
]

def load_sensor_timeseries(conn):
    total = 0
    for name, site_src in SENSOR_SOURCES:
        conn.execute("DELETE FROM sensor_timeseries WHERE source_id = ?", (name,))
        batch = []
        n = 0
        for r in rd_jsonl(name):
            site_id = f"{site_src}__{r['station_id']}"
            datastream = r.get("variable_ja") or r["variable"]
            batch.append((
                site_id, datastream, r["datetime"], r.get("value"),
                r.get("unit"), None, r["source_id"], 0,
            ))
            n += 1
            if len(batch) >= 20000:
                conn.executemany(
                    "INSERT INTO sensor_timeseries "
                    "(site_id, datastream, phenomenon_time, result, unit, instrument_id, source_id, is_synthetic) "
                    "VALUES (?,?,?,?,?,?,?,?)", batch)
                conn.commit()
                batch = []
        if batch:
            conn.executemany(
                "INSERT INTO sensor_timeseries "
                "(site_id, datastream, phenomenon_time, result, unit, instrument_id, source_id, is_synthetic) "
                "VALUES (?,?,?,?,?,?,?,?)", batch)
            conn.commit()
        print(f"  sensor_timeseries <- {name}: {n} rows (site_source={site_src})")
        total += n
    print(f"  sensor_timeseries total this run: {total}")

# ============================================================
# 2) measurements + events (環境省 公共用水域 水質)
# ============================================================
SITE_SRC_KOUSUI = "env_kousui_stations_kanagawa"

def load_env_kousui_sample(conn):
    """個別採水データ -> events + measurements"""
    conn.execute("DELETE FROM measurements WHERE source_id = ?", ("env_kousui_sample_kanagawa",))
    conn.execute("DELETE FROM events WHERE source_id = ?", ("env_kousui_sample_kanagawa",))

    events = {}  # event_id -> dict
    meas_batch = []
    id_seen = {}
    n_rows = 0

    def event_id_for(station_id, datetime_):
        return f"env_kousui_sample__{station_id}__{datetime_}"

    def meas_id_for(station_id, datetime_, variable):
        key = (station_id, datetime_, variable)
        seq = id_seen.get(key, 0)
        id_seen[key] = seq + 1
        base = f"env_kousui_sample__{station_id}__{datetime_}__{variable}"
        return base if seq == 0 else f"{base}__{seq}"

    # 1st pass: build events dict and measurement rows (need 2 passes because
    # water_temp needs to be folded into events.water_temp_c which may appear
    # anywhere in the per-station variable block)
    rows = list(rd_jsonl("env_kousui_sample_kanagawa"))
    n_rows = len(rows)
    for r in rows:
        eid = event_id_for(r["station_id"], r["datetime"])
        ev = events.setdefault(eid, {
            "event_id": eid, "site_id": f"{SITE_SRC_KOUSUI}__{r['station_id']}",
            "event_date": r["datetime"][:10] if r["datetime"] else None,
            "event_time": r["datetime"][11:19] if r["datetime"] and len(r["datetime"]) > 10 else None,
            "water_temp_c": None, "source_ref": r["source_ref"],
        })
        if r["variable"] == "water_temp" and r.get("value") is not None:
            ev["water_temp_c"] = r["value"]

    for r in rows:
        eid = event_id_for(r["station_id"], r["datetime"])
        mid = meas_id_for(r["station_id"], r["datetime"], r["variable"])
        meas_batch.append((
            mid, eid, f"{SITE_SRC_KOUSUI}__{r['station_id']}",
            r["datetime"][:10] if r["datetime"] else None,
            r.get("variable_ja") or r["variable"], r["variable"],
            r.get("value"), r.get("value_raw"), r.get("unit"),
            "採水・現地分析（環境省 公共用水域水質測定 公表データ, period=sample）",
            None, r.get("quality_flag"),
            "公開済", None, None,
            "env_kousui_sample_kanagawa", r["source_ref"], 0,
        ))

    conn.executemany(
        """INSERT OR REPLACE INTO events
           (event_id, site_id, event_date, event_time, protocol_id, protocol_version,
            weather, precip_24h_mm, water_temp_c, photo_count, gps_offset_m,
            is_backfilled, is_rain_triggered, source_id, source_ref, is_synthetic)
           VALUES (?,?,?,?,NULL,NULL,NULL,NULL,?,NULL,NULL,0,0,?,?,0)""",
        [(e["event_id"], e["site_id"], e["event_date"], e["event_time"], e["water_temp_c"],
          "env_kousui_sample_kanagawa", e["source_ref"]) for e in events.values()])
    conn.commit()

    CHUNK = 20000
    for i in range(0, len(meas_batch), CHUNK):
        conn.executemany(
            """INSERT OR REPLACE INTO measurements
               (measurement_id, event_id, site_id, measured_on, variable, variable_en,
                value, value_raw, unit, method, instrument_id, detection_flag,
                quality_stage, verified_by, verified_on, source_id, source_ref, is_synthetic)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            meas_batch[i:i+CHUNK])
        conn.commit()

    print(f"  env_kousui_sample: {n_rows} rows -> {len(events)} events, {len(meas_batch)} measurements")

def load_env_kousui_annual(conn):
    """年度集計値 -> measurements のみ（event_id=NULL、代表日時なし）"""
    conn.execute("DELETE FROM measurements WHERE source_id = ?", ("env_kousui_annual_kanagawa",))
    meas_batch = []
    n_rows = 0
    for r in rd_jsonl("env_kousui_annual_kanagawa"):
        n_rows += 1
        mid = f"env_kousui_annual__{r['station_id']}__{r['fiscal_year']}__{r['variable']}"
        meas_batch.append((
            mid, None, f"{SITE_SRC_KOUSUI}__{r['station_id']}",
            str(r["fiscal_year"]) if r.get("fiscal_year") else None,
            r.get("variable_ja") or r["variable"], r["variable"],
            r.get("value"), r.get("value_raw"), r.get("unit"),
            "年度集計値（環境省 公共用水域水質測定 公表データ, period=fiscal_year。"
            "年間の代表値のため個別の測定日時は無い）",
            None, r.get("quality_flag"),
            "公開済", None, None,
            "env_kousui_annual_kanagawa", r["source_ref"], 0,
        ))
    CHUNK = 20000
    for i in range(0, len(meas_batch), CHUNK):
        conn.executemany(
            """INSERT OR REPLACE INTO measurements
               (measurement_id, event_id, site_id, measured_on, variable, variable_en,
                value, value_raw, unit, method, instrument_id, detection_flag,
                quality_stage, verified_by, verified_on, source_id, source_ref, is_synthetic)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            meas_batch[i:i+CHUNK])
        conn.commit()
    print(f"  env_kousui_annual: {n_rows} rows -> {len(meas_batch)} measurements (event_id=NULL)")

def main():
    conn = appdb()
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")

    load_sensor_timeseries(conn)
    load_env_kousui_sample(conn)
    load_env_kousui_annual(conn)

    n_ev = conn.execute("select count(*) from events").fetchone()[0]
    n_ms = conn.execute("select count(*) from measurements").fetchone()[0]
    n_ts = conn.execute("select count(*) from sensor_timeseries").fetchone()[0]
    print(f"\n  TOTALS -> events={n_ev} measurements={n_ms} sensor_timeseries={n_ts}")
    conn.close()

if __name__ == "__main__":
    main()
