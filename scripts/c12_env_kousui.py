"""環境省 水環境総合情報サイト 公共用水域水質測定結果（神奈川県 prefcode=14）
実在エンドポイント（download.asp の JS と zip_create/Scripts/user.js から特定、実測済み）:
  1) POST /water-pub/mizu-site/zip_create/WebService.asmx/StartCreation
     {"featureClassName": <FC>, "whereClause": "<SQL where>", "extension": "csv"}  -> {"d": "<jobid>"}
  2) POST .../WebService.asmx/GetThreadStatus  {"resultFileName": "<jobid>"} -> Running / Stopped
  3) GET  .../download.aspx?id=<jobid>  -> ZIP(output.csv, CP932)
FeatureClass:
  p_kosui_location 水質測定点マスタ / p_kosui_y01,y02,y03 年間値 / kosui_k01,k02,k03,k08 検体値
"""
import sys, io, csv, json, time, zipfile, pathlib, re
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import *
import pandas as pd
import requests

B = "https://water-pub.env.go.jp/water-pub/mizu-site/zip_create"
PREF = "14"
RAWD = RAW/"env_kousui"; RAWD.mkdir(parents=True, exist_ok=True)
SID_ST = "env_kousui_stations_kanagawa"
SID_Y  = "env_kousui_annual_kanagawa"
SID_K  = "env_kousui_sample_kanagawa"
LICENSE = ("環境省 水環境総合情報サイト（政府標準利用規約準拠 / 出典明示で利用可） "
           "https://water-pub.env.go.jp/water-pub/mizu-site/env.asp")
HDRS = {"User-Agent": UA, "Content-Type": "application/json; charset=utf-8",
        "Referer": f"{B}/dialog.htm"}

def fetch_fc(fc, where, cache):
    dest = RAWD/cache
    if not (dest.exists() and dest.stat().st_size > 0):
        args = json.dumps({"featureClassName": fc, "whereClause": where, "extension": "csv"})
        time.sleep(1.5)
        r = requests.post(f"{B}/WebService.asmx/StartCreation", headers=HDRS, data=args, timeout=120)
        r.raise_for_status()
        d = r.json()["d"]
        if d in ("RecordNotFound", "BadRequest"):
            raise RuntimeError(f"{fc}: {d} ({where})")
        for _ in range(120):
            time.sleep(3)
            s = requests.post(f"{B}/WebService.asmx/GetThreadStatus", headers=HDRS,
                              data=json.dumps({"resultFileName": d}), timeout=120)
            if "Stopped" in s.text: break
        else:
            raise RuntimeError(f"{fc}: timeout ({where})")
        time.sleep(1.5)
        z = requests.get(f"{B}/download.aspx?id={d}", headers={"User-Agent": UA}, timeout=300)
        if not z.content.startswith(b"PK"):
            raise RuntimeError(f"{fc}: not zip HTTP {z.status_code}")
        dest.write_bytes(z.content)
    with zipfile.ZipFile(dest) as zf:
        raw = zf.read(zf.namelist()[0])
    return pd.read_csv(io.BytesIO(raw), encoding="cp932", dtype=str)

# 測定項目: 基本列名 -> (variable_en, variable_ja, unit)
VARS = {
    "ph_min":      ("ph_min", "pH（最小値）", None),
    "ph_max":      ("ph_max", "pH（最大値）", None),
    "ph":          ("ph", "pH", None),
    "do_":         ("dissolved_oxygen", "溶存酸素量 DO", "mg/L"),
    "do":          ("dissolved_oxygen", "溶存酸素量 DO", "mg/L"),
    "bod":         ("bod", "生物化学的酸素要求量 BOD", "mg/L"),
    "bod75":       ("bod_75pct", "BOD 75%値", "mg/L"),
    "cod":         ("cod", "化学的酸素要求量 COD", "mg/L"),
    "cod75":       ("cod_75pct", "COD 75%値", "mg/L"),
    "ss":          ("suspended_solids", "浮遊物質量 SS", "mg/L"),
    "colon":       ("coliform_group", "大腸菌群数", "MPN/100mL"),
    "coli":        ("escherichia_coli", "大腸菌数", "CFU/100mL"),
    "coli90":      ("escherichia_coli_90pct", "大腸菌数 90%値", "CFU/100mL"),
    "hex":         ("n_hexane_extract", "ノルマルヘキサン抽出物質", "mg/L"),
    "allzn":       ("total_zinc", "全亜鉛", "mg/L"),
    "bottomdo":    ("bottom_layer_do", "底層溶存酸素量", "mg/L"),
    "las":         ("las", "直鎖アルキルベンゼンスルホン酸及びその塩 LAS", "mg/L"),
    "nonylphenol": ("nonylphenol", "ノニルフェノール", "mg/L"),
    "tn":          ("total_nitrogen", "全窒素 T-N", "mg/L"),
    "tp":          ("total_phosphorus", "全燐 T-P", "mg/L"),
    "watertemp":   ("water_temp", "水温", "degC"),
    "suion":       ("water_temp", "水温", "degC"),
    "toui":        ("transparency", "透明度", "m"),
    "denki":       ("electric_conductivity", "電気伝導率", "mS/m"),
    "temperature": ("air_temp", "気温", "degC"),
    "wtemp":       ("water_temp", "水温", "degC"),
    "flowrate":    ("river_width_or_flow", "流量関連（公式定義未確認のため原表記のまま）", None),
    "clearness":   ("transparency", "透明度", "m"),
    "deepness":    ("water_depth", "水深", "m"),
    "saishudepth": ("sampling_depth", "採水深度", None),
}
META_COLS = {"x", "y", "zettaicode", "suikeicode", "prefcode", "suiikicode", "chitencode",
             "chitenflag", "nendo", "fiscalyear", "month", "daytime", "recordid",
             "locationname", "rlscode", "kijunflag1", "kijunflag2",
             "water", "latitude", "longitude", "kijunflag3", "scalflag", "ruikei",
             "ruikeisuisei", "ruikeibottomdo", "chitenflag04", "chitenflag05",
             "weather", "flow", "odor", "hue", "all2",
             # depth は年間値/検体値で意味が異なり公式定義を確認できないため除外（推測しない）
             "depth", "depth2"}

STMAP = {}   # zettaicode -> {station_name_ja, water_body_ja, lat, lon}

def s_(v):
    """NaN/float 安全に文字列化して引用符を除去"""
    if v is None: return ""
    s = str(v)
    if s in ("nan", "None"): return ""
    return s.strip().strip('"')

def find_measure_cols(cols_lower):
    """値列 X は X2 または X3 という兄弟列を持つ、という規則で機械的に検出する"""
    st = set(cols_lower)
    return [c for c in cols_lower
            if c not in META_COLS and not c.endswith("2") and not c.endswith("3")
            and ((c + "2") in st or (c + "3") in st)] + \
           [c for c in cols_lower
            if c not in META_COLS and (c.endswith("2") or c.endswith("3"))
            and ((c + "2") in st or (c + "3") in st)]

def melt(df, source_id, fc, where, style):
    """style='y': X=値, X2=フラグ, X3=表示文字列 / style='k': X=値, X2=小数値, X3=フラグ"""
    cols = {c.lower(): c for c in df.columns}
    lower = [c.lower() for c in df.columns]
    mcols = find_measure_cols(lower)
    out = []
    for _, r in df.iterrows():
        lat = to_number(r[cols["latitude"]])[0] if "latitude" in cols else None
        lon = to_number(r[cols["longitude"]])[0] if "longitude" in cols else None
        nendo = to_fiscal_year(s_(r[cols["nendo"]])) if "nendo" in cols else None
        dtr, dt, period = None, (str(nendo) if nendo else None), "fiscal_year"
        if style == "k":
            period = "sample"
            y  = s_(r[cols["fiscalyear"]]); mo = s_(r[cols["month"]]); dtm = s_(r[cols["daytime"]])
            dtr = f"{y}-{mo}-{dtm}"
            m = re.fullmatch(r"(\d{2})(\d{2})(\d{2})", dtm.zfill(6))   # DDHHMM
            if m and y and mo:
                dd, hh, mi = (int(g) for g in m.groups())
                dt = (f"{int(y):04d}-{int(mo):02d}-{dd:02d}T{hh:02d}:{mi:02d}:00+09:00"
                      if 1 <= dd <= 31 and hh <= 23 and mi <= 59 else None)
            else:
                dt = None
        rid = s_(r[cols["recordid"]]) if "recordid" in cols else None
        zc  = s_(r[cols["zettaicode"]]) if "zettaicode" in cols else ""
        ref = STMAP.get(zc, {})
        base = {
            "station_id":      "kousui_" + zc,
            "station_name_ja": ((s_(r[cols["locationname"]]) or None) if "locationname" in cols
                                else ref.get("station_name_ja")),
            "water_body_ja":   ((s_(r[cols["water"]]) or None) if "water" in cols
                                else ref.get("water_body_ja")),
            "lat": lat if lat is not None else ref.get("lat"),
            "lon": lon if lon is not None else ref.get("lon"),
            "fiscal_year": nendo, "datetime": dt, "datetime_raw": dtr, "period": period,
        }
        for lc in mcols:
            c   = cols[lc]
            a   = r[c]
            b   = r[cols[lc + "2"]] if (lc + "2") in cols else None
            c3  = r[cols[lc + "3"]] if (lc + "3") in cols else None
            if style == "y":
                val_src, disp, flag = a, c3, b
            else:
                val_src, disp, flag = (b if s_(b) else a), a, c3
            if not s_(val_src) and not s_(disp):
                continue
            v, kind = to_number(val_src)
            en, ja, unit = VARS.get(lc, (lc, None, None))
            out.append({**base,
                        "variable": en, "variable_ja": ja,
                        "value": float(v) if kind in ("int", "float") else None,
                        "value_raw": s_(disp) or s_(val_src),
                        "unit": unit,
                        "quality_flag": s_(flag) or None,
                        "source_id": source_id,
                        "source_ref": f"{fc}#{rid or (zc + '/' + str(dt))}/{lc}"})
    return out

def dump(name, rows):
    if not rows: return
    pd.DataFrame(rows).to_csv(PROC/f"{name}.csv", index=False, encoding="utf-8")
    write_jsonl(name, rows)

def main():
    Y_FROM = 2005
    # --- 1. 測定点マスタ ---
    try:
        df = fetch_fc("p_kosui_location", f"prefcode='{PREF}'", "location_14.zip")
        df["nendo_i"] = pd.to_numeric(df["nendo"], errors="coerce")
        df["zc"] = df["zettaicode"].map(s_)
        g = df.sort_values("nendo_i").groupby("zc")
        st = []
        for code, sub in g:
            last = sub.iloc[-1]
            st.append({
                "station_id": "kousui_" + code, "zettaicode": code,
                "station_name_ja": s_(last["locationname"]) or None,
                "water_body_ja": s_(last["water"]) or None,
                "pref_code": s_(last["prefcode"]),
                "suikei_code": s_(last["suikeicode"]),
                "suiiki_code": s_(last["suiikicode"]),
                "chiten_code": s_(last["chitencode"]),
                "lat": to_number(last["latitude"])[0], "lon": to_number(last["longitude"])[0],
                "nendo_from": int(sub["nendo_i"].min()), "nendo_to": int(sub["nendo_i"].max()),
                "n_years": int(sub["nendo_i"].nunique()),
                "source_id": SID_ST,
                "source_ref": f"p_kosui_location?prefcode='{PREF}'#{code}",
            })
        with open(PROC/f"{SID_ST}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, list(st[0].keys())); w.writeheader(); w.writerows(st)
        write_jsonl(SID_ST, st)
        STMAP.update({x["zettaicode"]: {"station_name_ja": x["station_name_ja"],
                                        "water_body_ja": x["water_body_ja"],
                                        "lat": x["lat"], "lon": x["lon"]} for x in st})
        register(SID_ST, "環境省 公共用水域 水質測定点マスタ（神奈川県）", "環境省",
                 "https://water-pub.env.go.jp/water-pub/mizu-site/mizu/download/", "水質",
                 "zip_create WebService.asmx (StartCreation/GetThreadStatus/download.aspx)",
                 "CSV/JSONL", LICENSE, True, len(st),
                 "p_kosui_location を年度重複排除。nendo_from/to は測定点マスタに現れた年度範囲。")
    except Exception as e:
        print(f"  [fail] location: {e}")
        register(SID_ST, "環境省 公共用水域 水質測定点マスタ（神奈川県）", "環境省",
                 "https://water-pub.env.go.jp/water-pub/mizu-site/mizu/download/", "水質",
                 "zip_create WebService.asmx", "CSV/JSONL", LICENSE, True, 0, f"取得失敗: {e}")

    # --- 2. 年間値 (健康項目/生活環境項目/全窒素・全燐) ---
    rows, notes = [], []
    for fc, label in (("p_kosui_y02", "生活環境項目"), ("p_kosui_y03", "全窒素・全燐"),
                      ("p_kosui_y01", "健康項目")):
        where = f"nendo>={Y_FROM} and prefcode='{PREF}'"
        try:
            df = fetch_fc(fc, where, f"{fc}_{PREF}_{Y_FROM}.zip")
            r = melt(df, SID_Y, fc, where, "y")
            rows += r; print(f"  {fc} {label}: {len(df)} src rows -> {len(r)} long rows")
        except Exception as e:
            notes.append(f"{fc}({label})取得失敗: {e}"); print(f"  [fail] {fc}: {e}")
    dump(SID_Y, rows)
    register(SID_Y, "環境省 公共用水域水質測定結果 年間値（神奈川県）", "環境省",
             "https://water-pub.env.go.jp/water-pub/mizu-site/mizu/kousui/dataMap.asp", "水質",
             "zip_create WebService.asmx (CSV in ZIP)", "CSV/JSONL", LICENSE, True, len(rows),
             f"nendo>={Y_FROM} / 生活環境項目(BOD,COD,DO,pH,SS,大腸菌群数,全亜鉛 等)・全窒素全燐・健康項目 / "
             f"縦持ち long。value は数値列、value_raw は表示用文字列列(*3)、quality_flag は付帯フラグ列(*2)。"
             + (" / " + "; ".join(notes) if notes else ""))

    # --- 3. 検体値（採水日ごと・時系列として最も細かい） ---
    K_FROM = 2015          # 検体値は行数が多いため直近10年度に限定
    rows2, notes2 = [], []
    for fc, label in (("kosui_k02", "生活環境項目"), ("kosui_k08", "一般項目")):
        where = f"nendo>={K_FROM} and prefcode='{PREF}'"
        try:
            df = fetch_fc(fc, where, f"{fc}_{PREF}_{K_FROM}.zip")
            r = melt(df, SID_K, fc, where, "k")
            rows2 += r; print(f"  {fc} {label}: {len(df)} src rows -> {len(r)} long rows")
        except Exception as e:
            notes2.append(f"{fc}({label})取得失敗: {e}"); print(f"  [fail] {fc}: {e}")
    dump(SID_K, rows2)
    register(SID_K, "環境省 公共用水域水質測定結果 検体値（神奈川県）", "環境省",
             "https://water-pub.env.go.jp/water-pub/mizu-site/mizu/download/", "水質",
             "zip_create WebService.asmx (CSV in ZIP)", "CSV/JSONL", LICENSE, True, len(rows2),
             f"nendo>={K_FROM} / 採水日時単位の検体値（datetime は FISCALYEAR-MONTH-DAYTIME(DDHHMM) より復元, JST）。"
             "縦持ち long。value は小数列(X2)、value_raw は整数列(X)、quality_flag は付帯フラグ列(X3)。"
             "depth 列は年間値/検体値で意味が異なり公式定義を確認できなかったため出力から除外。"
             + (" / " + "; ".join(notes2) if notes2 else ""))

if __name__ == "__main__":
    main()
