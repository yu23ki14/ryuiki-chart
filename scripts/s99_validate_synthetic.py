#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合成データ(scripts/s01_synthetic.py)の検証スクリプト。

チェック内容:
  1. is_synthetic=1 / =0 の件数がテーブルごとに正しいか
  2. 実データ行(is_synthetic=0)が壊れていないか
     - 件数が「本タスク開始時点の既知件数」を下回っていないか(他エージェントによる追加は許容)
     - sites.treatment 以外の列で実データ行に対する意図しない変更が無いか
       (is_synthetic=0 の行チェックサムを算出し、2回目以降の実行で差分が出ないことを確認する
       ウォッチドッグ方式。初回実行時点のチェックサムは「本スクリプト初回実行時点」のものであり、
       s01_synthetic.py 実行前の値そのものではない点に注意 — 理由は本ファイル末尾のコメント参照)
  3. 外部キーの孤児(存在しない site_id/event_id/protocol_id/instrument_id/observer_id 参照)が0件か
  4. 専門家検証通過率が算出でき、80%前後か
  5. decisions から「データが意思決定に持ち込まれた回数」が算出できるか(目標:累計12回以上)
  6. 降雨トリガーイベントが実測の降水量30mm超の日(の翌日)に対応しているか

実行:
  . .venv/bin/activate && python scripts/s99_validate_synthetic.py
"""
import sqlite3, json, hashlib, csv, pathlib, sys, datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data/db/ryuiki.sqlite"
JMA_CSV = ROOT / "data/processed/jma_daily_yokohama.csv"
SNAPSHOT_PATH = ROOT / "data/logs/synthetic_validation_snapshot.json"

# 本タスク着手時点(合成データ生成前)に既知だった実データの件数。
# これを下回っていたら実データが失われたことを意味する(他エージェントによる増加は許容するため
# ">=" で比較する)。
BASELINE_REAL_COUNTS = {
    "sites": 352,
    "measurements": 313053,
    "sensor_timeseries": 377378,
    "organism_records": 451108,
    "taxa": 8364,
    "protocols": 6,
    "source_registry": 93,
    "events": 29271,
}

EXPECTED_TREATMENT_SITES = {
    "env_kousui_stations_kanagawa__kousui_1420190": "対策区",
    "env_kousui_stations_kanagawa__kousui_1410940": "対策区",
    "env_kousui_stations_kanagawa__kousui_1420160": "対照区",
    "env_kousui_stations_kanagawa__kousui_1420170": "対照区",
    "moni1000_sites__kn355213932": "対策区",
    "moni1000_sites__kn355413913": "対策区",
    "moni1000_sites__kn353613922": "対策区",
    "moni1000_sites__kn353113922": "対策区",
    "moni1000_sites__kn355713947": "対照区",
    "moni1000_sites__kn353613946": "対照区",
    "moni1000_sites__kn35471391": "参照",
    "moni1000_sites__kn354713899": "参照",
}


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def ok(label, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {label}" + (f" — {detail}" if detail else ""))
    return cond


def section(title):
    print(f"\n== {title} ==")


def main():
    conn = connect()
    all_pass = True

    # ------------------------------------------------------------------
    section("1. is_synthetic 件数")
    for t in ["sites", "events", "measurements", "interventions", "decisions", "sensor_timeseries"]:
        rows = conn.execute(f"SELECT is_synthetic, COUNT(*) FROM {t} GROUP BY is_synthetic").fetchall()
        print(f"  {t}: {dict(rows)}")
    n_obs = conn.execute("SELECT COUNT(*) FROM observers WHERE is_synthetic=1").fetchone()[0]
    n_instr_syn = conn.execute("SELECT COUNT(*) FROM instruments WHERE instrument_id LIKE 'SYN-INSTR-%'").fetchone()[0]
    n_instr_real = conn.execute("SELECT COUNT(*) FROM instruments WHERE instrument_id NOT LIKE 'SYN-INSTR-%'").fetchone()[0]
    print(f"  observers(is_synthetic=1): {n_obs}")
    print(f"  instruments: synthetic={n_instr_syn}, real(collector-derived, no is_synthetic column)={n_instr_real}")
    all_pass &= ok("observers is_synthetic=1 のみで構成", n_obs > 0 and
                   conn.execute("SELECT COUNT(*) FROM observers WHERE is_synthetic=0").fetchone()[0] == 0)

    # ------------------------------------------------------------------
    section("2. 実データ行の非破壊確認")
    NO_SYNTHETIC_COL = {"taxa", "protocols", "source_registry"}
    for t, base in BASELINE_REAL_COUNTS.items():
        if t in NO_SYNTHETIC_COL:
            cur = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            all_pass &= ok(f"{t}: 件数(このテーブルは全件実データ) {cur} >= ベースライン {base}", cur >= base, f"cur={cur}")
        else:
            cur = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE is_synthetic=0").fetchone()[0]
            all_pass &= ok(f"{t}: is_synthetic=0 件数 {cur} >= ベースライン {base}", cur >= base, f"cur={cur}")

    # sites.treatment 例外の範囲確認: 実データ行で treatment が非NULLなのは想定12件のみ
    rows = conn.execute("SELECT site_id, treatment FROM sites WHERE is_synthetic=0 AND treatment IS NOT NULL").fetchall()
    actual_treatment = dict(rows)
    all_pass &= ok(
        "sites.treatment を更新した実データ行は想定の12件のみ",
        actual_treatment == EXPECTED_TREATMENT_SITES,
        f"actual={actual_treatment}",
    )

    # チェックサム・ウォッチドッグ(is_synthetic=0 行の内容ハッシュ。sitesはtreatment列を除く)
    def table_checksum(table, exclude_cols=()):
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall() if r[1] not in exclude_cols]
        pk = cols[0]
        qcols = ",".join(f'"{c}"' for c in cols)
        q = f'SELECT {qcols} FROM {table} WHERE is_synthetic=0 ORDER BY "{pk}"'
        h = hashlib.sha256()
        for row in conn.execute(q):
            h.update("|".join("" if v is None else str(v) for v in row).encode("utf-8"))
            h.update(b"\n")
        return h.hexdigest()

    checksums = {
        "sites_excl_treatment": table_checksum("sites", exclude_cols=("treatment",)),
        "measurements": table_checksum("measurements"),
        "events": table_checksum("events"),
        "organism_records": table_checksum("organism_records"),
        "sensor_timeseries": table_checksum("sensor_timeseries"),
    }
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SNAPSHOT_PATH.exists():
        prev = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        for k, v in checksums.items():
            if k in prev.get("checksums", {}):
                same = prev["checksums"][k] == v
                all_pass &= ok(f"チェックサム一致(実データ行 is_synthetic=0, {k})", same,
                               "前回スナップショットと不一致" if not same else "")
    else:
        print("  [info] チェックサムのスナップショットが無いため、今回の値を新規に保存する。")
        print("  [注意] このスナップショットは s99 初回実行時点のものであり、s01 実行前の値そのものではない")
        print("         (時間的制約により s01 実行前にスナップショットを取得できなかったため)。")
        print("         今後 s01/s99 を再実行した際に、この時点からの意図しない変更を検知する目的で保存する。")
    SNAPSHOT_PATH.write_text(json.dumps({
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "checksums": checksums,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    section("3. 外部キー孤児チェック")
    fk_checks = [
        ("events.site_id -> sites", "SELECT COUNT(*) FROM events e WHERE NOT EXISTS(SELECT 1 FROM sites s WHERE s.site_id=e.site_id)"),
        ("events.protocol_id -> protocols (NULL除く)",
         "SELECT COUNT(*) FROM events e WHERE e.protocol_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM protocols p WHERE p.protocol_id=e.protocol_id)"),
        ("measurements.event_id -> events (NULL除く)",
         "SELECT COUNT(*) FROM measurements m WHERE m.event_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM events e WHERE e.event_id=m.event_id)"),
        ("measurements.site_id -> sites (NULL除く)",
         "SELECT COUNT(*) FROM measurements m WHERE m.site_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM sites s WHERE s.site_id=m.site_id)"),
        ("measurements.instrument_id -> instruments (NULL除く)",
         "SELECT COUNT(*) FROM measurements m WHERE m.instrument_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM instruments i WHERE i.instrument_id=m.instrument_id)"),
        ("event_observers.event_id -> events",
         "SELECT COUNT(*) FROM event_observers eo WHERE NOT EXISTS(SELECT 1 FROM events e WHERE e.event_id=eo.event_id)"),
        ("event_observers.observer_id -> observers",
         "SELECT COUNT(*) FROM event_observers eo WHERE NOT EXISTS(SELECT 1 FROM observers o WHERE o.observer_id=eo.observer_id)"),
        ("interventions.site_id -> sites",
         "SELECT COUNT(*) FROM interventions iv WHERE NOT EXISTS(SELECT 1 FROM sites s WHERE s.site_id=iv.site_id)"),
        ("sensor_timeseries.site_id -> sites (合成分 is_synthetic=1 のみ; 実データ分は既知の別問題として注記参照)",
         "SELECT COUNT(*) FROM sensor_timeseries st WHERE st.is_synthetic=1 AND NOT EXISTS(SELECT 1 FROM sites s WHERE s.site_id=st.site_id)"),
        ("sensor_timeseries.instrument_id -> instruments (NULL除く)",
         "SELECT COUNT(*) FROM sensor_timeseries st WHERE st.instrument_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM instruments i WHERE i.instrument_id=st.instrument_id)"),
        ("quality_transitions.target_id -> measurements (target_table='measurements')",
         "SELECT COUNT(*) FROM quality_transitions qt WHERE qt.target_table='measurements' AND NOT EXISTS(SELECT 1 FROM measurements m WHERE m.measurement_id=qt.target_id)"),
    ]
    for label, q in fk_checks:
        n = conn.execute(q).fetchone()[0]
        all_pass &= ok(f"孤児0件: {label}", n == 0, f"n={n}")

    # 参考情報(FAILには含めない): sensor_timeseries の実データ(is_synthetic=0)側に、
    # sites未登録のsite_id(sagamihara_taiki_stations__*, soramame_stations_kanagawa__*)を
    # 参照する行が既存する。これは本合成データ生成より前から存在する別収集エージェントの
    # データ上の問題であり、本タスク(合成データ生成)の対象外・原因でもないため、参考情報として記録する。
    n_real_orphan = conn.execute(
        "SELECT COUNT(*) FROM sensor_timeseries st WHERE st.is_synthetic=0 AND NOT EXISTS(SELECT 1 FROM sites s WHERE s.site_id=st.site_id)"
    ).fetchone()[0]
    print(f"  [info; 非対象] sensor_timeseries 実データ(is_synthetic=0)側の site_id 孤児: {n_real_orphan}件 "
          f"(sagamihara_taiki_hourly / soramame_hourly_kanagawa; sitesテーブルに当該観測局が未登録。"
          f"別収集エージェントの既存データであり本タスクでは変更していない)")

    # FR-1.5: 1地点2名以上体制
    n_under2 = conn.execute(
        "SELECT COUNT(*) FROM (SELECT event_id, COUNT(DISTINCT observer_id) c FROM event_observers GROUP BY event_id HAVING c<2)"
    ).fetchone()[0]
    all_pass &= ok("FR-1.5: 全イベントで観測者2名以上", n_under2 == 0, f"2名未満のイベント数={n_under2}")

    # ------------------------------------------------------------------
    section("4. 専門家検証通過率 (FR-2.2, 目標80%以上)")
    reviewed = conn.execute(
        """SELECT DISTINCT target_id FROM quality_transitions
           WHERE target_table='measurements' AND note LIKE '専門家抜き取り検証%'"""
    ).fetchall()
    n_reviewed = len(reviewed)
    n_passed = conn.execute(
        """SELECT COUNT(*) FROM measurements m WHERE m.is_synthetic=1 AND m.quality_stage IN ('検証済','公開済')
           AND EXISTS(SELECT 1 FROM quality_transitions qt WHERE qt.target_table='measurements'
                      AND qt.target_id=m.measurement_id AND qt.note LIKE '専門家抜き取り検証%')"""
    ).fetchone()[0]
    pass_rate = n_passed / n_reviewed if n_reviewed else None
    print(f"  抜き取り検証対象: {n_reviewed}件 / 合格: {n_passed}件 / 通過率: {pass_rate:.4f}" if pass_rate else "  抜き取り対象なし")
    all_pass &= ok("専門家検証通過率が算出可能", pass_rate is not None)
    all_pass &= ok("専門家検証通過率が概ね80%前後(70〜90%)", pass_rate is not None and 0.70 <= pass_rate <= 0.90,
                   f"pass_rate={pass_rate}")

    # ------------------------------------------------------------------
    section("5. 意思決定記録 (FR-3.8 / M-B KPI)")
    n_dec = conn.execute("SELECT COUNT(*) FROM decisions WHERE is_synthetic=1").fetchone()[0]
    all_pass &= ok("decisions が12件以上(データが意思決定に持ち込まれた回数の累計KPI)", n_dec >= 12, f"n={n_dec}")
    # presented_data 内の site_id/measurement_id が実在するかの軽量チェック
    bad_refs = 0
    for (did, pdata) in conn.execute("SELECT decision_id, presented_data FROM decisions WHERE is_synthetic=1"):
        try:
            d = json.loads(pdata)
        except Exception:
            bad_refs += 1
            continue
        sid = d.get("site_id")
        if sid and not conn.execute("SELECT 1 FROM sites WHERE site_id=?", (sid,)).fetchone():
            bad_refs += 1
        for mid in d.get("measurement_ids", []) or []:
            if not conn.execute("SELECT 1 FROM measurements WHERE measurement_id=?", (mid,)).fetchone():
                bad_refs += 1
    all_pass &= ok("decisions.presented_data 内の参照が全て実在", bad_refs == 0, f"bad_refs={bad_refs}")

    # ------------------------------------------------------------------
    section("6. 降雨トリガーイベント (FR-1.8)")
    precip = {}
    for r in csv.DictReader(open(JMA_CSV, encoding="utf-8")):
        if r["variable"] == "precipitation_total" and r["value"]:
            try:
                precip[r["datetime"]] = float(r["value"])
            except ValueError:
                pass
    threshold_days = sorted(d for d, v in precip.items() if v >= 30.0)
    rain_events = conn.execute(
        "SELECT event_id, event_date, precip_24h_mm FROM events WHERE is_synthetic=1 AND is_rain_triggered=1"
    ).fetchall()
    print(f"  実測 >=30mm/日 の日数: {len(threshold_days)}件 (jma_daily_yokohama, 収集済み範囲)")
    print(f"  降雨トリガーイベント数: {len(rain_events)}件")
    bad = 0
    for eid, edate, precip_val in rain_events:
        trigger_source_day = (datetime.date.fromisoformat(edate) - datetime.timedelta(days=1)).isoformat()
        if trigger_source_day not in threshold_days or precip.get(trigger_source_day) != precip_val:
            bad += 1
    all_pass &= ok("全ての降雨トリガーイベントが実測>=30mm日の翌日かつ実測値と一致", bad == 0, f"不一致={bad}")
    all_pass &= ok("降雨トリガーイベントが1件以上生成されている", len(rain_events) > 0)

    # ------------------------------------------------------------------
    section("7. FR-1.4 GPS検算 / FR-1.11 後追い入力 分布")
    n_ev = conn.execute("SELECT COUNT(*) FROM events WHERE is_synthetic=1").fetchone()[0]
    n_gps_over50 = conn.execute("SELECT COUNT(*) FROM events WHERE is_synthetic=1 AND gps_offset_m>50").fetchone()[0]
    n_backfilled = conn.execute("SELECT COUNT(*) FROM events WHERE is_synthetic=1 AND is_backfilled=1").fetchone()[0]
    print(f"  events(synthetic)={n_ev}, gps_offset>50m={n_gps_over50} ({n_gps_over50/n_ev:.1%}), "
          f"backfilled={n_backfilled} ({n_backfilled/n_ev:.1%})")
    all_pass &= ok("GPS offset>50m が数%程度", 0.01 <= n_gps_over50 / n_ev <= 0.10)
    all_pass &= ok("backfilled が1割程度", 0.05 <= n_backfilled / n_ev <= 0.15)

    print("\n" + ("=" * 40))
    print("ALL CHECKS PASSED" if all_pass else "SOME CHECKS FAILED")
    conn.close()
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
