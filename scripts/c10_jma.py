"""気象庁 過去の気象データ（神奈川県 prec_no=46）
 - 地点マスタ: amedastable.json + etrn 都道府県ページ(block_no) をマージ
 - 月別値: 主要5地点 x 直近6年 (monthly_a1/monthly_s1)
 - 日別値: 横浜(47670) 直近2年 (daily_s1)  ← FR-1.8 降雨イベントトリガー用
出力は縦持ち(long): station_id, station_name_ja, lat, lon, datetime, variable, value, unit, ...
"""
import sys, re, io, json, pathlib, csv
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import *
import pandas as pd

SID_ST   = "jma_stations_kanagawa"
SID_MON  = "jma_monthly_kanagawa"
SID_DAY  = "jma_daily_yokohama"
BASE = "https://www.data.jma.go.jp/stats/etrn"
PREC = 46
RAWD = RAW/"jma"; RAWD.mkdir(parents=True, exist_ok=True)

LICENSE = ("気象庁ホームページ利用規約（政府標準利用規約 2.0 準拠 / CC BY 4.0 互換）"
           " https://www.jma.go.jp/jma/kishou/info/coment.html")

# ---------------------------------------------------------------- 1. 地点マスタ
def dm(deg, mi):
    return round(float(deg) + float(mi)/60.0, 6)

def fetch_stations():
    # (a) etrn 都道府県ページ: block_no と観測要素フラグ
    url = f"{BASE}/select/prefecture.php?prec_no={PREC}&block_no=&year=&month=&day=&view="
    r = get(url); r.encoding = "utf-8"
    (RAWD/"prefecture_46.html").write_text(r.text, encoding="utf-8")
    pat = re.compile(r"viewPoint\('(?P<type>[as])','(?P<block>\d+)','(?P<name>[^']*)','(?P<kana>[^']*)',"
                     r"'(?P<latd>[^']*)','(?P<latm>[^']*)','(?P<lond>[^']*)','(?P<lonm>[^']*)','(?P<alt>[^']*)',"
                     r"'(?P<rain>[^']*)','(?P<wind>[^']*)','(?P<temp>[^']*)','(?P<sun>[^']*)','(?P<snow>[^']*)',"
                     r"'(?P<hum>[^']*)','(?P<f1>[^']*)','(?P<f2>[^']*)','(?P<f3>[^']*)','(?P<note>[^']*)'")
    etrn = {}
    for m in pat.finditer(r.text):
        d = m.groupdict()
        etrn[d["name"]] = d
    print(f"  etrn prefecture page: {len(etrn)} stations")

    # (b) amedastable.json（全国）から神奈川(=46xxx)を抽出
    tbl = get_json("https://www.jma.go.jp/bosai/amedas/const/amedastable.json")
    (RAWD/"amedastable.json").write_text(json.dumps(tbl, ensure_ascii=False), encoding="utf-8")
    rows = []
    for amedas_id, v in tbl.items():
        if not amedas_id.startswith("46"):
            continue
        name = v.get("kjName")
        e = etrn.get(name, {})
        rows.append({
            "station_id":       f"jma_{e['block']}" if e else f"jma_amd{amedas_id}",
            "amedas_id":        amedas_id,
            "block_no":         e.get("block"),
            "prec_no":          str(PREC),
            "station_type":     {"s": "官署", "a": "アメダス"}.get(e.get("type"), "アメダス"),
            "station_name_ja":  name,
            "station_kana_ja":  v.get("knName"),
            "station_name_en":  v.get("enName"),
            "prefecture_ja":    "神奈川県",
            "lat":              dm(*v["lat"]),
            "lon":              dm(*v["lon"]),
            "elevation_m":      v.get("alt"),
            "obs_rain":         e.get("rain"), "obs_temp": e.get("temp"),
            "obs_wind":         e.get("wind"), "obs_sun": e.get("sun"),
            "obs_snow":         e.get("snow"), "obs_humidity": e.get("hum"),
            "elems_raw":        v.get("elems"),
            "note_ja":          e.get("note") or None,
            "source_id":        SID_ST,
            "source_ref":       url if e else "https://www.jma.go.jp/bosai/amedas/const/amedastable.json",
        })
    # (c) etrn にあって amedastable.json に無い地点（例: 江ノ島）を JS 引数から補完
    have = {r["station_name_ja"] for r in rows}
    for name, e in etrn.items():
        if name in have:
            continue
        rows.append({
            "station_id": f"jma_{e['block']}", "amedas_id": None, "block_no": e["block"],
            "prec_no": str(PREC),
            "station_type": {"s": "官署", "a": "アメダス"}.get(e["type"], "アメダス"),
            "station_name_ja": name, "station_kana_ja": e["kana"], "station_name_en": None,
            "prefecture_ja": "神奈川県",
            "lat": dm(e["latd"], e["latm"]), "lon": dm(e["lond"], e["lonm"]),
            "elevation_m": to_number(e["alt"])[0],
            "obs_rain": e["rain"], "obs_temp": e["temp"], "obs_wind": e["wind"],
            "obs_sun": e["sun"], "obs_snow": e["snow"], "obs_humidity": e["hum"],
            "elems_raw": None, "note_ja": e.get("note") or None,
            "source_id": SID_ST, "source_ref": url,
        })
    rows.sort(key=lambda x: (x["amedas_id"] or "zz", x["block_no"] or ""))
    return rows

# ---------------------------------------------------------------- 2. 表の正規化
def flat(col):
    seen = []
    for x in col if isinstance(col, tuple) else (col,):
        x = str(x).strip()
        if not seen or seen[-1] != x:
            seen.append(x)
    return "_".join(seen)

UNIT_RE = re.compile(r"\s*[（(]\s*(?:mm|℃|％|%|m/s|h|cm|hPa|MJ/㎡)\s*[)）]")

# 日本語ラベル(単位除去・空白除去) -> (variable_en, unit)
VARMAP = {
    "降水量_合計":                   ("precipitation_total", "mm"),
    "降水量_最大_日":                ("precipitation_max_daily", "mm"),
    "降水量_最大_1時間":             ("precipitation_max_1h", "mm"),
    "降水量_最大_10分間":            ("precipitation_max_10min", "mm"),
    "気温_平均_日平均":              ("air_temp_mean", "degC"),
    "気温_平均_日最高":              ("air_temp_mean_of_daily_max", "degC"),
    "気温_平均_日最低":              ("air_temp_mean_of_daily_min", "degC"),
    "気温_最高":                     ("air_temp_max", "degC"),
    "気温_最低":                     ("air_temp_min", "degC"),
    "気温_平均":                     ("air_temp_mean", "degC"),
    "湿度_平均":                     ("relative_humidity_mean", "percent"),
    "湿度_最小":                     ("relative_humidity_min", "percent"),
    "気圧_現地_平均":                ("station_pressure_mean", "hPa"),
    "気圧_海面_平均":                ("sea_level_pressure_mean", "hPa"),
    "風向・風速_平均 風速":          ("wind_speed_mean", "m/s"),
    "風向・風速_最大風速_風速":      ("wind_speed_max", "m/s"),
    "風向・風速_最大風速_風向":      ("wind_direction_at_max", None),
    "風向・風速_最大瞬間風速_風速":  ("wind_gust_max", "m/s"),
    "風向・風速_最大瞬間風速_風向":  ("wind_direction_at_gust", None),
    "風向・風速_平均風速":           ("wind_speed_mean", "m/s"),
    "日照 時間":                     ("sunshine_duration", "h"),
    "全天日射量_平均":               ("global_solar_radiation_mean", "MJ/m2"),
    "雪_降雪の深さ_合計":            ("snowfall_depth_total", "cm"),
    "雪_降雪の深さ_日合計の最大":    ("snowfall_depth_max_daily", "cm"),
    "雪_最深 積雪":                  ("snow_depth_max", "cm"),
    "雪_降雪_合計":                  ("snowfall_depth_total", "cm"),
    "雪_降雪_日合計の最大":          ("snowfall_depth_max_daily", "cm"),
    "雪_最深積雪":                   ("snow_depth_max", "cm"),
    "雪_最深積雪_値":                ("snow_depth_max", "cm"),
    "雪_最深 積雪_値":               ("snow_depth_max", "cm"),
    "雲量_平均":                     ("cloud_cover_mean", "tenths"),
    "大気現象_雪日数":               ("days_with_snow", "days"),
    "大気現象_霧日数":               ("days_with_fog", "days"),
    "大気現象_雷日数":               ("days_with_thunder", "days"),
    "天気概況_昼 (06:00-18:00)":     ("weather_summary_day", None),
    "天気概況_夜 (18:00-翌日06:00)": ("weather_summary_night", None),
}

def norm_label(lbl):
    s = UNIT_RE.sub("", lbl)
    s = s.replace("()", "").replace("（）", "")
    s = re.sub(r"\s+_", "_", s).strip().rstrip("_")
    s = re.sub(r"_+", "_", s)
    return s.strip()

# JMA 値の記号（気象庁「統計値の表示方法」より原文）
FLAG_DOC = {
    ")":  "準正常値。統計を行う対象資料の一部が欠けているが、許容範囲内であるもの。",
    "]":  "資料不足値。統計を行う対象資料が許容範囲を超えて欠けているもの。",
    "///": "欠測。",
    "#":  "値が正常な範囲にあるかどうか疑わしい値。",
    "*":  "統計期間内での最大値・最小値等について、同期間内の観測値が許容範囲を超えて欠けているもの。",
    "--": "現象がなかったことを示す。",
    "×":  "観測を行っていないことを示す。",
}

def parse_cell(raw):
    """-> (value, value_raw, quality_flag, no_phenomenon)"""
    s = "" if raw is None else str(raw).strip()
    if s in ("", "nan", "None"):
        return None, None, None, 0
    if s in ("--", "―", "－"):
        return None, s, "--", 1
    if s in ("×", "x", "X"):
        return None, s, "×", 0
    if s == "///":
        return None, s, "///", 0
    flag = None
    for f in (")", "]", "#", "*"):
        if f in s:
            flag = f
    body = s.replace(")", "").replace("]", "").replace("#", "").replace("*", "").replace("(", "").strip()
    v, kind = to_number(body)
    if kind in ("int", "float"):
        return float(v), s, flag, 0
    return None, s, flag, 0

def melt_table(df, station, when_fn, source_ref, period):
    cols = [flat(c) for c in df.columns]
    df = df.copy(); df.columns = cols
    key = cols[0]                      # '月' or '日'
    out = []
    for _, row in df.iterrows():
        idx, _k = to_number(row[key])
        if not isinstance(idx, int):
            continue
        dt = when_fn(idx)
        if dt is None:
            continue
        for c in cols[1:]:
            lbl = norm_label(c)
            en, unit = VARMAP.get(lbl, (None, None))
            if en is None:
                en = "unmapped:" + lbl
            v, vraw, flag, nophen = parse_cell(row[c])
            if vraw is None:
                continue
            if unit is None and v is None and vraw not in ("--", "×", "///"):
                pass  # 風向・天気概況などの文字列値
            out.append({
                "station_id":      station["station_id"],
                "station_name_ja": station["station_name_ja"],
                "lat": station["lat"], "lon": station["lon"],
                "datetime": dt,
                "period": period,
                "variable": en,
                "variable_ja": lbl,
                "value": v,
                "value_raw": vraw,
                "unit": unit,
                "quality_flag": flag,
                "quality_flag_note_ja": FLAG_DOC.get(flag or "", None),
                "no_phenomenon": nophen,
                "source_id": None,
                "source_ref": source_ref,
            })
    return out

def read_first_table(url, cache):
    p = RAWD/cache
    if p.exists() and p.stat().st_size > 0:
        html = p.read_text(encoding="utf-8")
    else:
        r = get(url); r.encoding = "utf-8"; html = r.text
        p.write_text(html, encoding="utf-8")
    return pd.read_html(io.StringIO(html))[0]

# ---------------------------------------------------------------- main
def main():
    stations = fetch_stations()
    hdr = list(stations[0].keys())
    with open(PROC/f"{SID_ST}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, hdr); w.writeheader(); w.writerows(stations)
    write_jsonl(SID_ST, stations)
    register(SID_ST, "気象庁 神奈川県 観測地点一覧（アメダス+官署）", "気象庁",
             "https://www.jma.go.jp/bosai/amedas/const/amedastable.json",
             "気象", "JSON API + HTML(etrn 都道府県ページ)", "CSV/JSONL",
             LICENSE, True, len(stations),
             "amedastable.json(緯度経度・標高) と etrn prefecture.php(block_no・観測要素) をマージ")
    byname = {s["station_name_ja"]: s for s in stations}

    # --- 月別値: 主要地点 x 直近6年 ---
    TARGETS = ["横浜", "海老名", "辻堂", "小田原", "丹沢湖", "相模湖", "三浦"]
    YEARS = list(range(2019, 2027))
    mon = []
    for nm in TARGETS:
        st = byname.get(nm)
        if not st or not st["block_no"]:
            print(f"  [skip] {nm}: block_no なし"); continue
        page = "monthly_s1.php" if st["station_type"] == "官署" else "monthly_a1.php"
        for y in YEARS:
            url = (f"{BASE}/view/{page}?prec_no={PREC}&block_no={st['block_no']}"
                   f"&year={y}&month=&day=&view=")
            try:
                df = read_first_table(url, f"monthly_{st['block_no']}_{y}.html")
            except Exception as e:
                print(f"  [warn] {nm} {y}: {e}"); continue
            rows = melt_table(df, st, lambda m, y=y: f"{y}-{m:02d}", url, "month")
            for r in rows: r["source_id"] = SID_MON
            mon += rows
        print(f"  monthly {nm}({st['block_no']}): cumulative {len(mon)}")
    if mon:
        pd.DataFrame(mon).to_csv(PROC/f"{SID_MON}.csv", index=False, encoding="utf-8")
        write_jsonl(SID_MON, mon)
    register(SID_MON, "気象庁 過去の気象データ 月別値（神奈川県 主要地点）", "気象庁",
             f"{BASE}/index.php", "気象", "HTML テーブル (pandas.read_html)", "CSV/JSONL",
             LICENSE, True, len(mon),
             f"地点={','.join(TARGETS)} / 年={YEARS[0]}-{YEARS[-1]} / 縦持ち long 形式")

    # --- 日別値: 横浜 直近2年 ---
    st = byname["横浜"]
    day = []
    import datetime as _dt
    today = _dt.date.today()
    for y in (2024, 2025, 2026):
        for m in range(1, 13):
            if (y, m) > (today.year, today.month):
                continue
            url = (f"{BASE}/view/daily_s1.php?prec_no={PREC}&block_no={st['block_no']}"
                   f"&year={y}&month={m}&day=&view=")
            try:
                df = read_first_table(url, f"daily_{st['block_no']}_{y}{m:02d}.html")
            except Exception as e:
                print(f"  [warn] daily {y}-{m}: {e}"); continue
            import calendar
            nd = calendar.monthrange(y, m)[1]
            rows = melt_table(df, st,
                              lambda d, y=y, m=m, nd=nd: (f"{y}-{m:02d}-{d:02d}" if 1 <= d <= nd else None),
                              url, "day")
            for r in rows: r["source_id"] = SID_DAY
            day += rows
        print(f"  daily 横浜 {y}: cumulative {len(day)}")
    if day:
        pd.DataFrame(day).to_csv(PROC/f"{SID_DAY}.csv", index=False, encoding="utf-8")
        write_jsonl(SID_DAY, day)
    register(SID_DAY, "気象庁 過去の気象データ 日別値（横浜 47670）", "気象庁",
             f"{BASE}/view/daily_s1.php?prec_no=46&block_no=47670", "気象",
             "HTML テーブル (pandas.read_html)", "CSV/JSONL", LICENSE, True, len(day),
             "2024-01〜直近月の日別値。降水量合計=precipitation_total は FR-1.8 降雨イベントトリガー用。"
             "「--」は気象庁凡例「現象がなかったことを示す」→ value は NULL のまま no_phenomenon=1 で保持（推測補完しない）")

if __name__ == "__main__":
    main()
