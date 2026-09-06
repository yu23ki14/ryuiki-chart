#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流域カルテ デモ: 合成データ生成 (要求定義書に対して公開データには原理的に存在しない要素を埋める)

絶対条件:
  - 生成するレコードは必ず is_synthetic=1。既存の is_synthetic=0 行は一切 UPDATE/DELETE しない
    （唯一の例外: sites.treatment 列。理由は docs/SYNTHETIC_DATA.md §0 参照。この場合も
    書き換えるのは treatment 列のみで、対象は本スクリプトの SITE_ROLES にハードコードした
    12 件の実在 site_id に限定する）。
  - 乱数は random.seed(SEED) で固定。サイト・観測者・日付の走査順序をすべて固定リストに
    しているため、再実行しても同一の結果になる。
  - INSERT のみ（INSERT OR IGNORE で冪等化）。DROP/DELETE は使わない。
  - 各合成レコードの source_ref に「何を土台にどう生成したか」を記す。

このスクリプトが担当する要素の全量・分布・根拠は docs/SYNTHETIC_DATA.md に記載する
（本ファイルの定数・関数はそのドキュメントの一次ソースでもある）。

実行:
  . .venv/bin/activate && python scripts/s01_synthetic.py
"""
import sys, os, random, sqlite3, datetime, csv, statistics, json, math, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data/db/ryuiki.sqlite"
JMA_CSV = ROOT / "data/processed/jma_daily_yokohama.csv"

SEED = 20260829

# ============================================================================
# 0. 接続・共通ヘルパ
# ============================================================================

def connect():
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def already_has_synthetic(conn, table, extra_where=None):
    where = "is_synthetic=1"
    if extra_where:
        where += " AND " + extra_where
    n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]
    return n > 0


def iso_date(d: datetime.date) -> str:
    return d.isoformat()


# ============================================================================
# 1. 実データの取得（分布・回帰の根拠。すべて is_synthetic=0 のみを対象にする）
# ============================================================================

def load_jma_daily():
    """data/processed/jma_daily_yokohama.csv から日別の降水量合計・平均気温・日中天気概況を読む。"""
    rows = list(csv.DictReader(open(JMA_CSV, encoding="utf-8")))
    precip, airtemp, weather_day = {}, {}, {}
    for r in rows:
        v = r.get("value")
        if r["variable"] == "precipitation_total" and v not in (None, ""):
            try:
                precip[r["datetime"]] = float(v)
            except ValueError:
                pass
        elif r["variable"] == "air_temp_mean" and v not in (None, ""):
            try:
                airtemp[r["datetime"]] = float(v)
            except ValueError:
                pass
        elif r["variable"] == "weather_summary_day":
            raw = r.get("value_raw")
            if raw:
                weather_day[r["datetime"]] = raw
    return precip, airtemp, weather_day


def real_stats(conn, variable_en):
    rows = conn.execute(
        "SELECT value FROM measurements WHERE variable_en=? AND is_synthetic=0 AND value IS NOT NULL",
        (variable_en,),
    ).fetchall()
    vals = [r[0] for r in rows]
    n = len(vals)
    mean = statistics.mean(vals)
    std = statistics.pstdev(vals)
    return {"n": n, "mean": mean, "std": std, "min": min(vals), "max": max(vals)}


def real_paired_airtemp_watertemp(conn):
    """同一イベント内で気温・水温が両方記録されている実データから単回帰係数を推定する。"""
    rows = conn.execute(
        """
        SELECT a.value, w.value FROM measurements a JOIN measurements w
          ON a.event_id = w.event_id
        WHERE a.variable_en='air_temp' AND w.variable_en='water_temp'
          AND a.is_synthetic=0 AND w.is_synthetic=0
          AND a.value IS NOT NULL AND w.value IS NOT NULL
        """
    ).fetchall()
    xs = [r[0] for r in rows]
    ys = [r[1] for r in rows]
    n = len(xs)
    mx, my = statistics.mean(xs), statistics.mean(ys)
    varx = sum((x - mx) ** 2 for x in xs) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    b = cov / varx
    a = my - b * mx
    resid = [y - (a + b * x) for x, y in zip(xs, ys)]
    resid_std = statistics.pstdev(resid)
    return {"n": n, "intercept": a, "slope": b, "resid_std": resid_std}


# ============================================================================
# 2. サイト選定（実在 site_id のみ使用。352件のうち、以下の24件をイベント地点、
#    12件を対策区/対照区/参照として採用する。選定根拠は docs/SYNTHETIC_DATA.md §2）
# ============================================================================

# 相模川水系（環境省 公共用水域水質測定点 = env_kousui_stations_kanagawa）
# 座標が重複する測定点コードは、対応する実測 measurements 件数が最大のものを代表点として採用。
SAGAMI_SITES = [
    # site_id, 表示名(参考), zone, role(treatment or None), intervention
    ("env_kousui_stations_kanagawa__kousui_1420190", "道志橋", 3, "対策区", "石積み_1"),
    ("env_kousui_stations_kanagawa__kousui_1410940", "弁天橋", 3, "対策区", "石積み_2"),
    ("env_kousui_stations_kanagawa__kousui_1420160", "沼本ダム", 3, "対照区", None),
    ("env_kousui_stations_kanagawa__kousui_1420170", "名手橋", 3, "対照区", None),
    ("env_kousui_stations_kanagawa__kousui_1420200", "境川橋", 3, None, None),
    ("env_kousui_stations_kanagawa__kousui_1420120", "日連大橋", 3, None, None),
    ("env_kousui_stations_kanagawa__kousui_1420140", "湖央東部", 3, None, None),
    ("env_kousui_stations_kanagawa__kousui_1420150", "相模湖大橋", 3, None, None),
    ("env_kousui_stations_kanagawa__kousui_1410170", "寒川取水堰(上)", 4, None, None),
    ("env_kousui_stations_kanagawa__kousui_1410200", "小倉橋", 4, None, None),
    ("env_kousui_stations_kanagawa__kousui_1410210", "新竹沢橋", 4, None, None),
    ("env_kousui_stations_kanagawa__kousui_1410190", "昭和橋", 4, None, None),
    ("env_kousui_stations_kanagawa__kousui_1410220", "相川水位観測所", 4, None, None),
    ("env_kousui_stations_kanagawa__kousui_1410240", "第一鮎津橋", 4, None, None),
    ("env_kousui_stations_kanagawa__kousui_1410230", "第二鮎津橋", 4, None, None),
    ("env_kousui_stations_kanagawa__kousui_1410250", "馬船橋", 4, None, None),
    ("env_kousui_stations_kanagawa__kousui_1410720", "宮の下橋", 5, None, None),
    ("env_kousui_stations_kanagawa__kousui_1410710", "馬入橋", 5, None, None),
]

# 里地里山（モニタリングサイト1000 サイト一覧 = moni1000_sites）のうち、水田・河川を含む地点
SATOYAMA_SITES = [
    ("moni1000_sites__kn355213932", "尾山耕地・中津川周辺", 4, "対策区", "復田_1"),
    ("moni1000_sites__kn355413913", "青根の水源林・沢・道志川・水田", 2, "対策区", "復田_2"),
    ("moni1000_sites__kn353613922", "いまいずみほたる公園", 3, "対策区", "駆除_1"),
    ("moni1000_sites__kn353113922", "中村川およびその周辺の里山", 5, "対策区", "駆除_2"),
    ("moni1000_sites__kn355713947", "奈良川源流域", 4, "対照区", None),
    ("moni1000_sites__kn353613946", "天神谷戸・石川丸山谷戸とその集水域", 4, "対照区", None),
]

# 参照区（headwater・保護区的な地点。頻繁な現地訪問は前提とせず、イベントは生成しない）
REFERENCE_SITES = [
    ("moni1000_sites__kn35471391", "桧洞丸稜線部", 1, "参照", None),
    ("moni1000_sites__kn354713899", "西丹沢", 1, "参照", None),
]

EVENT_SITES = SAGAMI_SITES + SATOYAMA_SITES  # 24件: イベントを生成する地点
TREATMENT_ROWS = [(s[0], s[3]) for s in (SAGAMI_SITES + SATOYAMA_SITES + REFERENCE_SITES) if s[3]]

INTERVENTION_SITE_OF = {tag: s[0] for s in (SAGAMI_SITES + SATOYAMA_SITES) if s[4] for tag in [s[4]]}

PROTOCOL_ID = "kanagawa_river_citizen_survey__manual"
PROTOCOL_VERSION = "神奈川県環境科学センター 調査マニュアル(公開版)"

EVENT_START = datetime.date(2023, 9, 1)
EVENT_END = datetime.date(2026, 8, 29)
JMA_COVERAGE_START = datetime.date(2024, 1, 1)
JMA_COVERAGE_END = datetime.date(2026, 8, 28)

FALLBACK_WEATHER = ["晴", "曇", "雨", "晴時々曇", "曇時々雨"]  # 2023-09〜2023-12(JMA未収集期間)用

# ============================================================================
# 3. 測定変数: 実データ統計を土台にする変数一覧と、各役割(初級/訓練済/専門)が担当する範囲
# ============================================================================

VARIABLES = ["air_temp", "water_temp", "ph", "dissolved_oxygen", "cod", "bod", "suspended_solids"]
VARIABLE_JA = {
    "air_temp": "気温", "water_temp": "水温", "ph": "pH",
    "dissolved_oxygen": "溶存酸素量 DO", "cod": "化学的酸素要求量 COD",
    "bod": "生物化学的酸素要求量 BOD", "suspended_solids": "浮遊物質量 SS",
}
VARIABLE_UNIT = {
    "air_temp": "degC", "water_temp": "degC", "ph": None,
    "dissolved_oxygen": "mg/L", "cod": "mg/L", "bod": "mg/L", "suspended_solids": "mg/L",
}
ROLE_VARIABLES = {
    "初級": ["air_temp", "water_temp", "ph"],
    "訓練済": ["air_temp", "water_temp", "ph", "dissolved_oxygen", "suspended_solids"],
    "専門": VARIABLES,
}
# 詳細な値域(clip)。実データ min/max のやや外側までを「物理的にありうる範囲」として許容する。
VARIABLE_CLIP = {
    "air_temp": (-10, 42), "water_temp": (0, 36), "ph": (4.0, 12.0),
    "dissolved_oxygen": (0, 25), "cod": (0, 60), "bod": (0, 50), "suspended_solids": (0, 400),
}
# ペア測定(FR-2.4)時のジッタ幅（絶対値 or 相対値）
PAIR_JITTER = {
    "air_temp": ("abs", 0.5), "water_temp": ("abs", 0.5), "ph": ("abs", 0.2),
    "dissolved_oxygen": ("abs", 0.4), "cod": ("rel", 0.15), "bod": ("rel", 0.15),
    "suspended_solids": ("rel", 0.20),
}

OUTLIER_RATE = 0.03      # FR-1.7: 過去分布から外れた値のデモ
PAIR_EVENT_RATE = 0.10   # FR-2.4: ペア測定のデモ
REVIEW_SAMPLE_RATE = 0.35  # FR-2.2: 専門家抜き取り検証の対象割合
REVIEW_PASS_RATE = 0.80    # FR-2.2: 専門家検証通過率の目標(80%以上)
PUBLISH_AFTER_PASS_RATE = 0.55  # 検証済のうち、さらに公開済まで進む割合

TREATMENT_SS_EFFECT = 0.85  # 石積み対策区: 施工後の SS を 15% 低減させる(デモ用の意図的な効果付与)

# ============================================================================
# 4. 観測者 (observers) — 実在の個人名は一切使わない
# ============================================================================

# (role, org, count)
OBSERVER_PLAN = [
    ("初級", "集落住民", 6), ("初級", "農家", 4), ("初級", "小中学生", 6), ("初級", "ボランティア", 4),
    ("訓練済", "関係人口", 4), ("訓練済", "ボランティア", 4), ("訓練済", "現地PM", 2), ("訓練済", "集落住民", 2),
    ("専門", "研究監修", 5), ("専門", "CfJ運営", 3),
]


def build_observers():
    observers = []
    seq = 1
    for role, org, count in OBSERVER_PLAN:
        for i in range(1, count + 1):
            oid = f"OBS-{seq:03d}"
            display = f"{org}-{i:02d}"
            observers.append((oid, display, role, org))
            seq += 1
    return observers


# ============================================================================
# 5. 機器 (instruments) — 校正記録込み。約2割を未校正にする(FR-2.5)
# ============================================================================

INSTRUMENT_PLAN = [
    ("水質計", "多項目水質計(簡易型: pH/DO/濁度)", 8, "WQ"),
    ("雨量計", "転倒ます式雨量計(簡易設置型)", 4, "RAIN"),
    ("水温ロガー", "水温自記記録計(防水型)", 4, "WTLOG"),
    ("土壌水分計TDR", "TDR土壌水分計(可搬型)", 3, "TDR"),
    ("照度計", "デジタル照度計", 3, "LUX"),
    ("簡易透視度計", "透視度計(円筒型)", 2, "TRANS"),
]
# 24台中 5台 (約2割) を未校正にする。決定的に固定。
UNCALIBRATED_IDS = {"SYN-INSTR-WQ-03", "SYN-INSTR-WQ-07", "SYN-INSTR-RAIN-02",
                    "SYN-INSTR-TDR-02", "SYN-INSTR-LUX-01"}


def build_instruments(rng):
    instruments = []
    for kind, model, count, code in INSTRUMENT_PLAN:
        for i in range(1, count + 1):
            iid = f"SYN-INSTR-{code}-{i:02d}"
            if iid in UNCALIBRATED_IDS:
                cal_on = None
                note = ("未校正: 校正記録なし(デモ設計として、全24台中5台(約2割)を未校正として設定し、"
                        "FR-2.5「未校正機器のデータにフラグ」を再現するためのもの。実際の校正未実施を示すものではない)")
                flag = 1
            else:
                cal_date = EVENT_START - datetime.timedelta(days=rng.randint(30, 400))
                cal_on = iso_date(cal_date)
                note = f"現地1点校正(TDR等の基準器との比較校正)実施。校正日={cal_on}(合成)"
                flag = 0
            instruments.append((iid, kind, model, cal_on, note, flag))
    return instruments


def instrument_pool(instruments, kind):
    return [i[0] for i in instruments if i[1] == kind]


REAL_THERMOMETER = "kanagawa_river_citizen_survey__thermometer"
REAL_PH_METER = "kanagawa_river_citizen_survey__ph_meter"


def pick_instrument_for(variable, wq_instruments, rng):
    """気温・水温は実データに実在する機器(温度計)、pHは実在pHメーターか合成水質計、
    DO/COD/BOD/SSは合成の多項目水質計を割り当てる。"""
    if variable in ("air_temp", "water_temp"):
        return REAL_THERMOMETER
    if variable == "ph":
        return rng.choice([REAL_PH_METER] + wq_instruments)
    return rng.choice(wq_instruments)


# ============================================================================
# 6. メイン生成ロジック
# ============================================================================

def gen_events_measurements(conn, rng, observers, instruments, precip, airtemp, weather_day):
    obs_ids = [o[0] for o in observers]
    obs_by_role = {}
    for o in observers:
        obs_by_role.setdefault(o[2], []).append(o[0])
    wq_instruments = instrument_pool(instruments, "水質計")

    # サイトごとにプライマリチーム(測定者+立会者)を固定的に割り当てる(ローテーションあり)
    ordinary = obs_by_role["初級"] + obs_by_role["訓練済"]
    experts = obs_by_role["専門"]

    site_teams = {}
    for i, s in enumerate(EVENT_SITES):
        site_id = s[0]
        measurer = ordinary[i % len(ordinary)]
        witness = ordinary[(i * 7 + 3) % len(ordinary)]
        if witness == measurer:
            witness = ordinary[(i * 7 + 4) % len(ordinary)]
        site_teams[site_id] = (measurer, witness)

    # 地点別の観測者ロール(=その地点で通常担当する観測者のrole)を決める
    def observer_role(oid):
        for o in observers:
            if o[0] == oid:
                return o[2]
        return "初級"

    real_stat = {v: real_stats(conn, v) for v in VARIABLES}
    reg = real_paired_airtemp_watertemp(conn)

    events_rows, ev_obs_rows, meas_rows, qt_rows = [], [], [], []

    ev_counter = 0
    meas_counter = 0

    def new_event_id():
        nonlocal ev_counter
        ev_counter += 1
        return f"SYN-EVT-{ev_counter:06d}"

    def new_meas_id():
        nonlocal meas_counter
        meas_counter += 1
        return f"SYN-MEAS-{meas_counter:06d}"

    def sample_value(var, base_date, is_outlier):
        st = real_stat[var]
        lo, hi = VARIABLE_CLIP[var]
        if var == "water_temp" and base_date.isoformat() in airtemp:
            # 実データ回帰式 water_temp = a + b*air_temp + noise (n=9109, docs参照)
            mean = reg["intercept"] + reg["slope"] * airtemp[base_date.isoformat()]
            std = reg["resid_std"]
        else:
            mean, std = st["mean"], st["std"]
        if is_outlier:
            sign = rng.choice([-1, 1])
            magnitude = rng.uniform(3.2, 4.5)
            val = mean + sign * magnitude * std
        else:
            val = rng.gauss(mean, std)
        val = max(lo, min(hi, val))
        return round(val, 3)

    def apply_treatment_effect(var, value, site_id, event_date):
        if var != "suspended_solids":
            return value
        site_info = {s[0]: s for s in SAGAMI_SITES}.get(site_id)
        if not site_info or site_info[3] != "対策区" or not site_info[4] or "石積み" not in site_info[4]:
            return value
        start = INTERVENTION_START.get(site_info[4])
        if start and event_date >= start:
            return round(value * TREATMENT_SS_EFFECT, 3)
        return value

    # --- 定期観測イベント(基準5〜6週間隔) ---
    for idx, s in enumerate(EVENT_SITES):
        site_id, disp, zone, role, itag = s
        measurer, witness = site_teams[site_id]
        cursor_date = EVENT_START + datetime.timedelta(days=(idx * 5) % 40)
        interval = 42  # 6週間
        while cursor_date <= EVENT_END:
            if rng.random() < 0.10:  # 1割は欠測(スキップ)
                cursor_date += datetime.timedelta(days=interval + rng.randint(-5, 5))
                continue
            event_date = cursor_date
            evt = make_event(
                site_id, event_date, is_rain=False, is_backfilled=(rng.random() < 0.10),
                rng=rng, precip=precip, weather_day=weather_day, new_event_id=new_event_id,
            )
            events_rows.append(evt)
            role_of_measurer = observer_role(measurer)
            ev_obs_rows.append((evt[0], measurer, "測定者"))
            ev_obs_rows.append((evt[0], witness, "立会者"))
            extra_pair_obs = None
            if rng.random() < PAIR_EVENT_RATE:
                candidates = [o for o in (ordinary + experts) if o not in (measurer, witness)]
                extra_pair_obs = rng.choice(candidates)
                ev_obs_rows.append((evt[0], extra_pair_obs, "立会者"))

            variables_today = ROLE_VARIABLES[role_of_measurer]
            pair_variable = rng.choice(variables_today) if extra_pair_obs else None
            for var in variables_today:
                is_outlier = rng.random() < OUTLIER_RATE
                val = sample_value(var, event_date, is_outlier)
                val = apply_treatment_effect(var, val, site_id, event_date)
                inst = pick_instrument_for(var, wq_instruments, rng)
                mid = new_meas_id()
                note = "outlier_by_design(FR-1.7 demo); " if is_outlier else ""
                src_ref = (
                    f"synthetic; seeded from real measurements stats for variable_en={var} "
                    f"(n={real_stat[var]['n']}, mean={real_stat[var]['mean']:.4f}, std={real_stat[var]['std']:.4f}); "
                    f"{note}event={evt[0]}, observer={measurer}"
                )
                if var == "water_temp":
                    src_ref += f"; water_temp = 6.093+0.6324*air_temp regression (n={reg['n']}, real same-event pairs)"
                meas_rows.append((
                    mid, evt[0], site_id, iso_date(event_date), VARIABLE_JA[var], var,
                    val, str(val), VARIABLE_UNIT[var],
                    "現地測定(県民参加型調査マニュアル準拠, 合成デモ)", inst, "0",
                    None, None, None,  # quality_stage/verified_by/verified_on は後で確定
                    None, src_ref, 1,
                ))
                if pair_variable == var:
                    kind, mag = PAIR_JITTER[var]
                    jitter = rng.gauss(0, mag) if kind == "abs" else rng.gauss(0, mag * abs(val if val else 1))
                    val2 = val + jitter
                    lo, hi = VARIABLE_CLIP[var]
                    val2 = round(max(lo, min(hi, val2)), 3)
                    mid2 = new_meas_id()
                    src_ref2 = (
                        f"synthetic; paired independent measurement (FR-2.4 demo) of {mid} by {extra_pair_obs}; "
                        f"jitter={kind}:{mag}"
                    )
                    inst2 = pick_instrument_for(var, wq_instruments, rng)
                    meas_rows.append((
                        mid2, evt[0], site_id, iso_date(event_date), VARIABLE_JA[var], var,
                        val2, str(val2), VARIABLE_UNIT[var],
                        "現地測定(ペア測定; 一致率デモ)", inst2, "0",
                        None, None, None,
                        None, src_ref2, 1,
                    ))
            cursor_date += datetime.timedelta(days=interval + rng.randint(-5, 5))

    # --- 降雨連動臨時観測イベント (FR-1.8) ---
    threshold_days = sorted(d for d, v in precip.items() if v >= 30.0)
    river_site_ids = [s[0] for s in SAGAMI_SITES]
    for di, d in enumerate(threshold_days):
        trigger_date = datetime.date.fromisoformat(d) + datetime.timedelta(days=1)
        if trigger_date > EVENT_END:
            continue
        chosen_sites = [river_site_ids[(di * 3 + k) % len(river_site_ids)] for k in range(3)]
        chosen_sites = list(dict.fromkeys(chosen_sites))  # 重複排除
        for site_id in chosen_sites:
            measurer, witness = site_teams[site_id]
            evt = make_event(
                site_id, trigger_date, is_rain=True, is_backfilled=False, rng=rng,
                precip=precip, weather_day=weather_day, new_event_id=new_event_id,
                precip_value=precip[d],
            )
            events_rows.append(evt)
            ev_obs_rows.append((evt[0], measurer, "測定者"))
            ev_obs_rows.append((evt[0], witness, "立会者"))
            role_of_measurer = observer_role(measurer)
            for var in ROLE_VARIABLES[role_of_measurer]:
                is_outlier = rng.random() < OUTLIER_RATE
                val = sample_value(var, trigger_date, is_outlier)
                val = apply_treatment_effect(var, val, site_id, trigger_date)
                inst = pick_instrument_for(var, wq_instruments, rng)
                mid = new_meas_id()
                src_ref = (
                    f"synthetic; rain-triggered event (FR-1.8 demo) seeded from jma_daily_yokohama "
                    f"precip_total={precip[d]}mm on {d} (real, >=30mm threshold); "
                    f"variable stats: n={real_stat[var]['n']}, mean={real_stat[var]['mean']:.4f}, std={real_stat[var]['std']:.4f}"
                )
                meas_rows.append((
                    mid, evt[0], site_id, iso_date(trigger_date), VARIABLE_JA[var], var,
                    val, str(val), VARIABLE_UNIT[var],
                    "臨時観測(降雨イベント連動, 合成デモ)", inst, "0",
                    None, None, None,
                    None, src_ref, 1,
                ))

    return events_rows, ev_obs_rows, meas_rows


def make_event(site_id, event_date, is_rain, is_backfilled, rng, precip, weather_day, new_event_id, precip_value=None):
    event_id = new_event_id()
    d = event_date.isoformat()
    if d in weather_day:
        weather = weather_day[d]
    else:
        weather = rng.choice(FALLBACK_WEATHER)
    if precip_value is None:
        precip_value = precip.get(d)
        if precip_value is None:
            # 実データが無い期間(2023-09〜2023-12)は近傍日で代用せず、欠測として保持しない方針上、
            # 「0.0mm」を仮定するのではなく、降雨トリガーでない通常観測は precip_24h_mm を
            # 参考値としてのみ 0〜5mm のランダム値(小雨〜無降雨相当)にする。
            precip_value = round(rng.uniform(0, 5), 1)
    if rng.random() < 0.04:
        gps_offset = round(rng.uniform(55, 160), 1)  # 数%: 規定距離(50m)超の警告デモ
    else:
        gps_offset = round(min(abs(rng.gauss(5, 4)), 15.0), 1)  # 大半: 0〜15m
    event_time = f"{rng.choice([9,10,11,13,14,15]):02d}:{rng.choice([0,15,30,45]):02d}:00"
    src_ref = (
        f"synthetic; site={site_id} date={d}"
        + (f"; rain-triggered by jma_daily_yokohama precip_total={precip_value}mm" if is_rain else "")
        + ("; backfilled paper record (FR-1.11 demo)" if is_backfilled else "")
    )
    return (
        event_id, site_id, d, event_time, PROTOCOL_ID, PROTOCOL_VERSION,
        weather, precip_value, None, rng.randint(1, 6), gps_offset,
        1 if is_backfilled else 0, 1 if is_rain else 0,
        None, src_ref, 1,
    )


INTERVENTION_START = {}  # 石積み等の施工開始日。interventions生成時に埋める。


def assign_quality_transitions(rng, meas_rows, observers):
    """暫定→検証済(→公開済) の遷移履歴を作り、measurements の quality_stage/verified_by/verified_on
    を確定する。専門家検証通過率が目標80%前後になるよう REVIEW_PASS_RATE で調整している。"""
    experts = [o[0] for o in observers if o[2] == "専門" and o[3] == "研究監修"]
    cfj_ops = [o[0] for o in observers if o[2] == "専門" and o[3] == "CfJ運営"]

    qt_rows = []
    finalized = []
    n_reviewed = 0
    n_passed = 0

    for row in meas_rows:
        row = list(row)
        mid, event_id, site_id, measured_on = row[0], row[1], row[2], row[3]
        base_date = datetime.date.fromisoformat(measured_on)
        # 誰が提出したかは source_ref に observer= が入っている定期観測のみ拾えるので、
        # 提出者actorはevent_observersと別に管理していないため、一般化して "現地測定者" とする。
        qt_rows.append(("measurements", mid, None, "暫定", "現地測定者", base_date.isoformat(), "現地入力(初期提出)"))
        stage = "暫定"
        verified_by = None
        verified_on = None
        if rng.random() < REVIEW_SAMPLE_RATE:
            n_reviewed += 1
            reviewer = rng.choice(experts)
            review_date = base_date + datetime.timedelta(days=rng.randint(3, 30))
            passed = rng.random() < REVIEW_PASS_RATE
            if passed:
                n_passed += 1
                qt_rows.append(("measurements", mid, "暫定", "検証済", reviewer, review_date.isoformat(),
                                 "専門家抜き取り検証: 合格"))
                stage = "検証済"
                verified_by = reviewer
                verified_on = review_date.isoformat()
                if rng.random() < PUBLISH_AFTER_PASS_RATE:
                    pub_actor = rng.choice(cfj_ops)
                    pub_date = review_date + datetime.timedelta(days=rng.randint(5, 60))
                    qt_rows.append(("measurements", mid, "検証済", "公開済", pub_actor, pub_date.isoformat(),
                                     "CfJ運営による公開処理"))
                    stage = "公開済"
                    verified_by = pub_actor
                    verified_on = pub_date.isoformat()
            else:
                qt_rows.append(("measurements", mid, "暫定", "暫定", reviewer, review_date.isoformat(),
                                 "専門家抜き取り検証: 差し戻し(再測定を推奨)"))
                verified_by = reviewer
                verified_on = review_date.isoformat()
        row[12] = stage
        row[13] = verified_by
        row[14] = verified_on
        finalized.append(tuple(row))

    pass_rate = (n_passed / n_reviewed) if n_reviewed else None
    return finalized, qt_rows, {"n_reviewed": n_reviewed, "n_passed": n_passed, "pass_rate": pass_rate}


# ============================================================================
# 7. 介入記録 (interventions)
# ============================================================================

def build_interventions():
    rows = []

    def add(tag, kind, parcel, qty, unit, start, finish, operator, note):
        site_id = INTERVENTION_SITE_OF[tag]
        iid = f"SYN-INT-{len(rows)+1:04d}"
        src_ref = f"synthetic; {note}"
        rows.append((iid, site_id, kind, parcel, qty, unit, start, finish, operator, None, src_ref, 1))
        INTERVENTION_START.setdefault(tag, datetime.date.fromisoformat(start))

    # 石積み(渓岸浸食対策; 丹沢周辺のシカ食害由来の土砂流入を想定した対策区の設定)
    add("石積み_1", "石積み", "道志橋下流護岸", 85.0, "m", "2024-11-05", "2024-11-24",
        "現地PM班+ボランティア", "対策区として設定した道志川沿い実在地点(道志橋)における渓岸浸食対策(石積み)を仮定。"
        "数量は一般的な渓岸保護工事の施工規模感を参考にした仮定値であり、実際の工事記録ではない。")
    add("石積み_1", "石積み", "道志橋下流護岸", 40.0, "人日", "2024-11-05", "2024-11-24",
        "現地PM班+ボランティア", "上記と同一工事の投入人日(仮定値)。")
    add("石積み_2", "石積み", "弁天橋上流護岸", 60.0, "m", "2025-03-03", "2025-03-19",
        "現地PM班+ボランティア", "対策区として設定した道志川沿い実在地点(弁天橋)における渓岸浸食対策(石積み)を仮定。")
    add("石積み_2", "石積み", "弁天橋上流護岸", 32.0, "人日", "2025-03-03", "2025-03-19",
        "現地PM班+ボランティア", "上記と同一工事の投入人日(仮定値)。")

    # 復田(耕作放棄地の水田復元)
    add("復田_1", "復田", "尾山耕地 A区画", 0.30, "ha", "2024-04-08", "2024-06-20",
        "農家+関係人口", "対策区として設定した実在地点(尾山耕地・中津川周辺)における耕作放棄地の復田を仮定。")
    add("復田_1", "復田", "尾山耕地 A区画", 55.0, "人日", "2024-04-08", "2024-06-20",
        "農家+関係人口", "上記と同一区画の投入人日(仮定値)。")
    add("復田_2", "復田", "青根 水源林際区画", 0.42, "ha", "2025-04-14", "2025-06-25",
        "農家+関係人口+ボランティア", "対策区として設定した実在地点(青根の水源林・沢・道志川・水田)における復田を仮定。")
    add("復田_2", "復田", "青根 水源林際区画", 70.0, "人日", "2025-04-14", "2025-06-25",
        "農家+関係人口+ボランティア", "上記と同一区画の投入人日(仮定値)。")

    # 駆除(ジャンボタニシ=スクミリンゴガイ Pomacea canaliculata; taxaに実在する外来種)
    for i, (start, finish) in enumerate([("2024-06-10", "2024-06-12"), ("2024-08-05", "2024-08-07"),
                                          ("2025-06-15", "2025-06-17")], start=1):
        add("駆除_1", "駆除", "いまいずみほたる公園 水田際", round(rng_static_choice(i, [3.2, 5.8, 4.1]), 1),
            "kg", start, finish, "集落住民+ボランティア",
            "対策区として設定した実在地点(いまいずみほたる公園)における外来種スクミリンゴガイ(Pomacea canaliculata; "
            "taxaテーブルに実在)の手作業駆除を仮定。捕獲重量は同種の一般的な防除活動の規模感を参考にした仮定値。")
        add("駆除_1", "駆除", "いまいずみほたる公園 水田際", [4.0, 5.0, 4.0][i - 1],
            "人日", start, finish, "集落住民+ボランティア", "上記と同一活動の投入人日(仮定値)。")
    for i, (start, finish) in enumerate([("2025-05-20", "2025-05-22"), ("2025-07-10", "2025-07-12"),
                                          ("2026-06-08", "2026-06-10")], start=1):
        add("駆除_2", "駆除", "中村川沿い里山 水田際", round(rng_static_choice(i + 10, [2.5, 6.4, 3.9]), 1),
            "kg", start, finish, "集落住民+ボランティア",
            "対策区として設定した実在地点(中村川およびその周辺の里山)における外来種スクミリンゴガイの手作業駆除を仮定。")
        add("駆除_2", "駆除", "中村川沿い里山 水田際", [5.0, 4.0, 5.0][i - 1],
            "人日", start, finish, "集落住民+ボランティア", "上記と同一活動の投入人日(仮定値)。")

    return rows


def rng_static_choice(i, choices):
    return choices[(i - 1) % len(choices)]


# ============================================================================
# 8. 意思決定記録 (decisions)
# ============================================================================

def build_decisions(conn, rng, meas_rows):
    """presented_data には実在する site_id / measurement_id を埋め込む(FR-3.8デモ)。"""
    meas_by_site = {}
    for row in meas_rows:
        meas_by_site.setdefault(row[2], []).append(row[0])

    def sample_ids(site_id, k=3):
        pool = meas_by_site.get(site_id, [])
        if not pool:
            return []
        rng.shuffle(pool)
        return pool[:k]

    # 実在する organism_record を1件だけ引用する（Pomacea canaliculata の実観察記録）
    real_org = conn.execute(
        "SELECT record_id FROM organism_records WHERE scientific_name='Pomacea canaliculata' ORDER BY record_id LIMIT 1"
    ).fetchone()
    real_org_id = real_org[0] if real_org else None

    meetings = [
        ("（架空）相模川中流域流域協議会 定例会", "2024-06-14",
         "道志橋・弁天橋の水質モニタリング進捗(SS/COD推移)、渓岸浸食対策(石積み)の実施候補地",
         "道志橋・弁天橋を対策区、沼本ダム・名手橋を対照区とする石積み工事の実施方針を決定",
         0, "現地PM, 研究監修, 集落住民代表"),
        ("（架空）相模原市 環境審議会 令和6年度第2回", "2024-09-10",
         "尾山耕地地区の復田候補区画とモニタリング体制案",
         "復田の投入人日・面積の見込みを了承し、次年度モニタリング体制(測定者2名/週)を決定",
         1, "現地PM, 農家代表, CfJ運営"),
        ("（架空）道志川地区 寄合", "2024-11-30",
         "石積み(道志橋)施工前後のSS測定値比較(暫定値)",
         "施工後モニタリングの継続と、下流の対照区(沼本ダム)での並行観測を確認",
         0, "集落住民, 現地PM"),
        ("（架空）流域自然再生検討委員会 第1回", "2025-02-18",
         "3対策区(石積み2/復田1)の初期モニタリング結果まとめ",
         "対策区/対照区のペア比較図をY2ダッシュボードの標準出力とすることを決定(停滞していたBACI比較設計が実行段階へ)",
         1, "研究監修, CfJ運営, 現地PM"),
        ("（架空）秦野市 環境審議会 令和7年度第1回", "2025-04-22",
         "いまいずみほたる公園におけるスクミリンゴガイ駆除計画",
         "駆除の実施(捕獲重量記録含む)と、水田際の水質モニタリング追加を承認",
         0, "現地PM, 集落住民代表, 研究監修"),
        ("（架空）青根地区 寄合", "2025-05-30",
         "復田(青根)の施工状況、投入人日の実績",
         "追加のボランティア人日確保について合意(具体的な割当は次回持ち越し)",
         0, "農家, 関係人口, 現地PM"),
        ("（架空）流域自然再生検討委員会 第2回", "2025-07-05",
         "石積み2地点(道志橋・弁天橋)のSS低減傾向、専門家検証通過率の四半期報告",
         "専門家検証通過率(暫定集計)が目標(80%)付近であることを確認し、抜き取り検証の対象範囲を維持することを決定",
         1, "研究監修, CfJ運営"),
        ("（架空）中村川流域 寄合", "2025-08-20",
         "中村川沿い里山におけるスクミリンゴガイ駆除の初回実施結果",
         "秋の追加駆除セッションの実施日程を決定",
         0, "集落住民, ボランティア, 現地PM"),
        ("（架空）相模川中流域流域協議会 令和7年度第2回", "2025-11-12",
         "GPS検算で許容距離を超えた地点の再確認結果、機器校正状況の四半期報告",
         "未校正機器(約2割)の校正スケジュールを来四半期に前倒しすることを決定(長らく停滞していた校正対応が実行に移った)",
         1, "現地PM, CfJ運営, 研究監修"),
        ("（架空）神奈川県 自然再生協議会 合同会議", "2026-01-16",
         "3か年分の対策区/対照区比較(石積み・復田・駆除)の中間報告、GBIF公開に向けた品質段階の整理",
         "四半期報告書(日英)への統合と、限定共有から全公開への段階的な公開範囲拡大方針を決定",
         0, "研究監修, CfJ運営, U5想定閲覧者(外部有識者)"),
        ("（架空）尾山耕地地区 寄合", "2026-02-28",
         "復田(尾山耕地)2年目の水質モニタリング推移",
         "次年度も同一区画でのモニタリングを継続することで合意",
         0, "農家, 現地PM"),
        ("（架空）道志川地区 寄合(年次報告会)", "2026-04-18",
         "石積み施工から約1年半のSS推移、対照区との比較図",
         "対策区のSS低減傾向を寄合資料として確定し、町への報告書に反映することを決定",
         1, "集落住民, 現地PM, 研究監修"),
        ("（架空）流域自然再生検討委員会 第3回", "2026-06-09",
         "駆除2地点の捕獲重量推移、専門家検証通過率の年次報告",
         "駆除継続の可否を次シーズン開始前に再評価することを決定",
         0, "研究監修, CfJ運営, 現地PM"),
        ("（架空）相模川中流域流域協議会 令和8年度第1回", "2026-07-21",
         "Y3拡張候補地点の選定基準(既存3対策区の効果検証を踏まえて)",
         "拡張候補地点のロングリストを次回までに現地PMが作成することを決定",
         0, "現地PM, 研究監修, CfJ運営"),
    ]

    rows = []
    for i, (name, date, presented_desc, decided, stalled, participants) in enumerate(meetings, start=1):
        # このミーティングに関連する対策区サイトのmeasurement_idを2〜3件添える
        related_site = None
        for tag, sid in INTERVENTION_SITE_OF.items():
            if any(k in presented_desc for k in ["道志橋", "尾山耕地", "青根", "いまいずみ", "中村川", "弁天橋"]):
                if ("道志橋" in presented_desc and tag == "石積み_1") or \
                   ("弁天橋" in presented_desc and tag == "石積み_2") or \
                   ("尾山耕地" in presented_desc and tag == "復田_1") or \
                   ("青根" in presented_desc and tag == "復田_2") or \
                   ("いまいずみ" in presented_desc and tag == "駆除_1") or \
                   ("中村川" in presented_desc and tag == "駆除_2"):
                    related_site = sid
                    break
        if related_site is None:
            # 特定の対策区に言及しない全体会合等は、代表地点(定期観測イベント地点)を参照させる
            related_site = EVENT_SITES[(i - 1) % len(EVENT_SITES)][0]
        ids = sample_ids(related_site)
        presented = {
            "summary": presented_desc,
            "site_id": related_site,
            "measurement_ids": ids,
        }
        if real_org_id and i == 5:
            presented["organism_record_id_ref"] = real_org_id
        did = f"SYN-DEC-{i:04d}"
        src_ref = ("synthetic; 会議名・出席区分はいずれも架空(is_synthetic=1)。実在の会議・実在の決定を記録したものではない。"
                    "presented_dataのsite_id/measurement_idは本DB内に実在するID。")
        rows.append((did, name, date, json.dumps(presented, ensure_ascii=False), decided,
                     stalled, participants, None, None, src_ref, 1))
    return rows


# ============================================================================
# 9. センサー時系列 (sensor_timeseries) — OGC SensorThings 形式デモ
# ============================================================================

def build_sensor_timeseries(conn, rng, instruments, airtemp, precip):
    wtlog = instrument_pool(instruments, "水温ロガー")
    tdr = instrument_pool(instruments, "土壌水分計TDR")
    reg = real_paired_airtemp_watertemp(conn)

    wt_sites = [SAGAMI_SITES[0][0], SAGAMI_SITES[1][0], SAGAMI_SITES[8][0]]  # 道志橋・弁天橋・寒川取水堰(上)
    sm_sites = [SATOYAMA_SITES[0][0], SATOYAMA_SITES[1][0]]  # 尾山耕地・青根(復田区画=水田の土壌水分相当)

    rows = []
    day = JMA_COVERAGE_START
    soil_state = {sid: 0.30 for sid in sm_sites}  # 初期含水率(体積比, 仮定初期値)
    while day <= JMA_COVERAGE_END:
        d = day.isoformat()
        at = airtemp.get(d)
        pr = precip.get(d, 0.0)
        for h in (0, 6, 12, 18):
            ts = f"{d}T{h:02d}:00:00+09:00"
            if at is not None:
                day_mean_wt = reg["intercept"] + reg["slope"] * at
                for i, sid in enumerate(wt_sites):
                    inst = wtlog[i % len(wtlog)]
                    diurnal = 0.6 * math.sin((h / 24) * 2 * math.pi)
                    val = round(day_mean_wt + diurnal + rng.gauss(0, reg["resid_std"] * 0.4), 3)
                    val = max(0.0, min(35.0, val))
                    rows.append((sid, "water_temperature", ts, val, "degC", inst, "synthetic_sensor", 1))
            for sid in sm_sites:
                inst = tdr[sm_sites.index(sid) % len(tdr)]
                decay = 0.94
                gain = 0.01
                new_val = soil_state[sid] * decay + gain * pr + rng.gauss(0, 0.005)
                new_val = max(0.10, min(0.55, new_val))
                soil_state[sid] = new_val
                rows.append((sid, "soil_moisture", ts, round(new_val, 4), "m3/m3", inst, "synthetic_sensor", 1))
        day += datetime.timedelta(days=1)
    return rows, {"water_temp_sites": wt_sites, "soil_moisture_sites": sm_sites,
                  "n_rows": len(rows), "regression": reg}


# ============================================================================
# 10. 実行
# ============================================================================

def main():
    rng = random.Random(SEED)
    conn = connect()

    report = {}

    # --- observers ---
    if already_has_synthetic(conn, "observers"):
        print("[skip] observers already generated")
    else:
        observers = build_observers()
        conn.executemany(
            "INSERT OR IGNORE INTO observers (observer_id, display_name, role, org, is_synthetic) VALUES (?,?,?,?,1)",
            observers,
        )
        conn.commit()
        print(f"[ok] observers: {len(observers)} rows")
    observers = conn.execute("SELECT observer_id, display_name, role, org FROM observers WHERE is_synthetic=1").fetchall()
    report["observers"] = len(observers)

    # --- instruments ---
    existing_instr = conn.execute("SELECT instrument_id FROM instruments").fetchall()
    existing_instr_ids = {r[0] for r in existing_instr}
    if any(i.startswith("SYN-INSTR-") for i in existing_instr_ids):
        print("[skip] instruments already generated")
    else:
        rng_i = random.Random(SEED)  # 独立した決定的シード列
        instruments = build_instruments(rng_i)
        conn.executemany(
            "INSERT OR IGNORE INTO instruments (instrument_id, kind, model, calibrated_on, calibration_note, uncalibrated_flag) VALUES (?,?,?,?,?,?)",
            instruments,
        )
        conn.commit()
        print(f"[ok] instruments: {len(instruments)} rows "
              f"(uncalibrated={sum(1 for i in instruments if i[5]==1)})")
    instruments = conn.execute(
        "SELECT instrument_id, kind, model, calibrated_on, calibration_note, uncalibrated_flag FROM instruments WHERE instrument_id LIKE 'SYN-INSTR-%'"
    ).fetchall()
    report["instruments"] = len(instruments)

    # --- sites.treatment (実在サイトへの UPDATE。唯一の例外的操作) ---
    n_updated = 0
    for site_id, role in TREATMENT_ROWS:
        cur = conn.execute("SELECT treatment FROM sites WHERE site_id=?", (site_id,)).fetchone()
        if cur is None:
            print(f"[warn] site_id not found, skip treatment update: {site_id}")
            continue
        if cur[0] == role:
            continue
        conn.execute("UPDATE sites SET treatment=? WHERE site_id=?", (role, site_id))
        n_updated += 1
    conn.commit()
    print(f"[ok] sites.treatment updated: {n_updated} rows (target {len(TREATMENT_ROWS)})")
    report["sites_treatment_updated"] = len(TREATMENT_ROWS)

    # interventions は measurements 生成時の対策区効果付与(TREATMENT_SS_EFFECT)に
    # INTERVENTION_START の日付を必要とするため、DB挿入より前に必ず計算しておく
    # (この関数呼び出し自体は副作用として INTERVENTION_START を埋めるだけで、DBへは書き込まない)
    interventions = build_interventions()

    # --- events / measurements / quality_transitions ---
    if already_has_synthetic(conn, "events"):
        print("[skip] events/measurements already generated")
        report["events"] = conn.execute("SELECT COUNT(*) FROM events WHERE is_synthetic=1").fetchone()[0]
        report["measurements"] = conn.execute("SELECT COUNT(*) FROM measurements WHERE is_synthetic=1").fetchone()[0]
    else:
        precip, airtemp, weather_day = load_jma_daily()
        events_rows, ev_obs_rows, meas_rows = gen_events_measurements(
            conn, rng, observers, instruments, precip, airtemp, weather_day
        )
        meas_rows, qt_rows, qa_report = assign_quality_transitions(rng, meas_rows, observers)

        conn.executemany(
            """INSERT OR IGNORE INTO events (event_id, site_id, event_date, event_time, protocol_id,
               protocol_version, weather, precip_24h_mm, water_temp_c, photo_count, gps_offset_m,
               is_backfilled, is_rain_triggered, source_id, source_ref, is_synthetic)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            events_rows,
        )
        conn.executemany(
            "INSERT OR IGNORE INTO event_observers (event_id, observer_id, part) VALUES (?,?,?)",
            ev_obs_rows,
        )
        conn.executemany(
            """INSERT OR IGNORE INTO measurements (measurement_id, event_id, site_id, measured_on,
               variable, variable_en, value, value_raw, unit, method, instrument_id, detection_flag,
               quality_stage, verified_by, verified_on, source_id, source_ref, is_synthetic)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            meas_rows,
        )
        conn.executemany(
            "INSERT INTO quality_transitions (target_table, target_id, from_stage, to_stage, actor, occurred_at, note) VALUES (?,?,?,?,?,?,?)",
            qt_rows,
        )
        conn.commit()
        print(f"[ok] events: {len(events_rows)} rows (rain-triggered={sum(1 for e in events_rows if e[12]==1)}, "
              f"backfilled={sum(1 for e in events_rows if e[11]==1)})")
        print(f"[ok] event_observers: {len(ev_obs_rows)} rows")
        print(f"[ok] measurements: {len(meas_rows)} rows")
        print(f"[ok] quality_transitions: {len(qt_rows)} rows; review pass rate = {qa_report['pass_rate']}")
        report["events"] = len(events_rows)
        report["measurements"] = len(meas_rows)
        report["event_observers"] = len(ev_obs_rows)
        report["quality_transitions"] = len(qt_rows)
        report["qa_pass_rate"] = qa_report

    # --- interventions ---
    if already_has_synthetic(conn, "interventions"):
        print("[skip] interventions already generated")
    else:
        conn.executemany(
            """INSERT OR IGNORE INTO interventions (intervention_id, site_id, kind, parcel, quantity,
               quantity_unit, started_on, finished_on, operator, source_id, source_ref, is_synthetic)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            interventions,
        )
        conn.commit()
        print(f"[ok] interventions: {len(interventions)} rows")
        report["interventions"] = len(interventions)

    # --- decisions ---
    if already_has_synthetic(conn, "decisions"):
        print("[skip] decisions already generated")
    else:
        meas_rows_for_decisions = conn.execute(
            "SELECT measurement_id, event_id, site_id FROM measurements WHERE is_synthetic=1"
        ).fetchall()
        meas_rows_padded = [(m[0], m[1], m[2]) + (None,) * 15 for m in meas_rows_for_decisions]
        decisions = build_decisions(conn, rng, meas_rows_padded)
        conn.executemany(
            """INSERT OR IGNORE INTO decisions (decision_id, meeting_name, meeting_date, presented_data,
               decided, stalled_item_resolved, participants, url, source_id, source_ref, is_synthetic)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            decisions,
        )
        conn.commit()
        n_stalled = sum(1 for d in decisions if d[5] == 1)
        print(f"[ok] decisions: {len(decisions)} rows (stalled_item_resolved=1: {n_stalled})")
        report["decisions"] = len(decisions)

    # --- sensor_timeseries ---
    if already_has_synthetic(conn, "sensor_timeseries"):
        print("[skip] sensor_timeseries already generated")
    else:
        precip, airtemp, weather_day = load_jma_daily()
        ts_rows, ts_meta = build_sensor_timeseries(conn, rng, instruments, airtemp, precip)
        conn.executemany(
            "INSERT INTO sensor_timeseries (site_id, datastream, phenomenon_time, result, unit, instrument_id, source_id, is_synthetic) VALUES (?,?,?,?,?,?,?,?)",
            ts_rows,
        )
        conn.commit()
        print(f"[ok] sensor_timeseries: {len(ts_rows)} rows "
              f"(water_temp sites={ts_meta['water_temp_sites']}, soil_moisture sites={ts_meta['soil_moisture_sites']})")
        report["sensor_timeseries"] = len(ts_rows)

    conn.close()
    print("\n=== SUMMARY ===")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
