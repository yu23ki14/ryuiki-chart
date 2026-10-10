"""環境省 そらまめ君（大気汚染物質広域監視システム AEROS）神奈川県
実在エンドポイント（SPA の app.js から抽出し、実際に叩いて確認済み）:
  - 測定局マスタ+測定項目有無: GET  /data/sokutei/existence/YYYY/MM/DD/HH.csv  (全国, text/csv)
  - 月別1時間値ZIP:            POST /soramame/download?DL_KBN=3&Target_YM=YYYYMM&TDFKN_CD=14&SKT_CD=...
    ※ Target_YM は直近13ヶ月のみ有効（それ以前は HTTP 400 パラメータ不正）
出力: 縦持ち long
"""
import sys, io, csv, json, zipfile, datetime, pathlib, argparse
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import *
import regions
import pandas as pd
import requests

# 地域依存の定数。jp-14 の値は従来の直書きと同一（scripts/tests/test_c_region_names.py で固定）。
RID = "jp-14"
SID_ST = regions.name("soramame_stations_kanagawa", RID)
SID_TS = regions.name("soramame_hourly_kanagawa", RID)
RAWD = RAW/regions.name("soramame", RID); RAWD.mkdir(parents=True, exist_ok=True)
PREF = regions.get(RID)["pref_code"]   # "14"
LABEL = "神奈川県"
LICENSE = ("環境省 そらまめ君 利用規約（出典明示による利用可 / 速報値・確定値は国立環境研究所 "
           "環境数値データベース）https://soramame.env.go.jp/policy")

# 流域デモ用に選定した測定局。局コード -> 名称は regions.py の soramame_stations
TARGET_STATIONS = dict(regions.get(RID)["soramame_stations"])

def set_region(rid):
    global RID, SID_ST, SID_TS, RAWD, PREF, LABEL, TARGET_STATIONS
    RID = rid
    cfg = regions.get(rid)
    SID_ST = regions.name("soramame_stations_kanagawa", rid)
    SID_TS = regions.name("soramame_hourly_kanagawa", rid)
    RAWD = RAW/regions.name("soramame", rid); RAWD.mkdir(parents=True, exist_ok=True)
    PREF = cfg["pref_code"]
    TARGET_STATIONS = dict(cfg["soramame_stations"])
    if rid != "jp-14":
        LABEL = "奄美大島"
# 縦持ちにする測定項目（列名 -> (variable, unit)）
ITEMS = {
    "SO2(ppm)":     ("so2", "ppm"),
    "NO2(ppm)":     ("no2", "ppm"),
    "Ox(ppm)":      ("photochemical_oxidant", "ppm"),
    "SPM(mg/m3)":   ("spm", "mg/m3"),
    "PM2.5(μg/m3)": ("pm2_5", "ug/m3"),
}   # 気温・風速・湿度は気象庁アメダス側で取得するため大気項目のみに限定

def latest_hour():
    md = get_json("https://soramame.env.go.jp/data/sokutei/noudoAll/metadata.json")
    return datetime.datetime.strptime(md["latest"], "%Y/%m/%d %H:%M:%S"), md

def fetch_station_master(t):
    url = f"https://soramame.env.go.jp/data/sokutei/existence/{t:%Y/%m/%d/%H}.csv"
    r = get(url)
    r.encoding = "utf-8"
    (RAWD/"existence.csv").write_text(r.text, encoding="utf-8")
    df = pd.read_csv(io.StringIO(r.text), dtype=str)
    df = df[df["都道府県コード"] == PREF].copy()
    if RID != "jp-14":      # 県全体の局マスタから、対象局だけ残す（jp-14 は従来どおり県全局）
        df = df[df["測定局コード"].isin(TARGET_STATIONS)].copy()
    rows = []
    for _, x in df.iterrows():
        rows.append({
            "station_id":       "soramame_" + x["測定局コード"],
            "station_code":     x["測定局コード"],
            "station_name_ja":  x["測定局名称"],
            "address_ja":       x["住所"],
            "station_kind_ja":  x["局種別"],          # 一般局 / 自排局
            "municipality_ja":  x["市区町村名"],
            "pref_code":        x["都道府県コード"],
            "area_code":        x["地域コード"],
            "contact_ja":       x["問い合わせ先"],
            "lat": None, "lon": None,   # そらまめ君の公開CSVに緯度経度は含まれない
            **{f"has_{k.replace('測定有無','').lower()}": v
               for k, v in x.items() if str(k).endswith("測定有無")},
            "source_id":  SID_ST,
            "source_ref": url + "#" + x["測定局コード"],
        })
    return rows, url

def month_range(latest, n=13):
    out, y, m = [], latest.year, latest.month
    for _ in range(n):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0: y, m = y-1, 12
    return list(reversed(out))

def download_month(ym, codes):
    dest = RAWD/f"{ym}_{PREF}.zip"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    url = ("https://soramame.env.go.jp/soramame/download"
           f"?DL_KBN=3&Target_YM={ym}&TDFKN_CD={PREF}&SKT_CD={','.join(codes)}")
    import urllib.parse, time
    time.sleep(1.5)
    r = requests.post(url, headers={"User-Agent": UA,
                                    "Referer": "https://soramame.env.go.jp/download"}, timeout=120)
    if r.status_code != 200 or not r.content.startswith(b"PK"):
        raise RuntimeError(f"{ym}: HTTP {r.status_code} {r.content[:120]!r}")
    dest.write_bytes(r.content)
    return dest

def main():
    ap = argparse.ArgumentParser(); regions.add_region_arg(ap)
    set_region(ap.parse_args().region)
    latest, md = latest_hour()
    print(f"  soramame latest={md['latest']} oldest={md['oldest']}")
    stations, murl = fetch_station_master(latest)
    hdr = list(stations[0].keys())
    with open(PROC/f"{SID_ST}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, hdr); w.writeheader(); w.writerows(stations)
    write_jsonl(SID_ST, stations)
    register(SID_ST, f"環境省 そらまめ君 測定局マスタ（{LABEL}）", "環境省",
             "https://soramame.env.go.jp/", "大気", "HTTP GET (CSV)", "CSV/JSONL",
             LICENSE, True, len(stations),
             "existence CSV（測定項目有無つき）。緯度経度は そらまめ君 公開CSVに含まれないため NULL。")
    byname = {s["station_code"]: s for s in stations}

    months = month_range(latest, 13)
    codes = list(TARGET_STATIONS)
    rows, fails = [], []
    for ym in months:
        try:
            z = download_month(ym, codes)
        except Exception as e:
            fails.append(str(e)); print(f"  [warn] {e}"); continue
        with zipfile.ZipFile(z) as zf:
            for nm in zf.namelist():
                df = pd.read_csv(io.BytesIO(zf.read(nm)), encoding="cp932", dtype=str)
                code = nm.split("_")[-1].replace(".csv", "")
                st = byname.get(code, {})
                for _, x in df.iterrows():
                    d = str(x["日付"]).replace("/", "-")
                    hh = int(x["時"])
                    # 「24時」は翌日 00:00 として ISO 表記
                    base = datetime.datetime.strptime(d, "%Y-%m-%d")
                    ts = (base + datetime.timedelta(hours=hh)).strftime("%Y-%m-%dT%H:%M:%S+09:00")
                    for col, (var, unit) in ITEMS.items():
                        if col not in df.columns: continue
                        raw = x[col]
                        if raw is None or str(raw).strip() in ("", "nan"): continue
                        v, kind = to_number(raw)
                        rows.append({
                            "station_id": "soramame_" + code,
                            "station_name_ja": st.get("station_name_ja"),
                            "lat": None, "lon": None,
                            "datetime": ts, "period": "hour",
                            "variable": var, "variable_ja": col,
                            "value": float(v) if kind in ("int", "float") else None,
                            "value_raw": str(raw).strip(), "unit": unit,
                            "source_id": SID_TS,
                            "source_ref": f"{nm}#{d}T{hh:02d}",
                        })
        print(f"  {ym}: cumulative {len(rows)}")
    if rows:
        pd.DataFrame(rows).to_csv(PROC/f"{SID_TS}.csv", index=False, encoding="utf-8")
        write_jsonl(SID_TS, rows)
    register(SID_TS, f"環境省 そらまめ君 1時間値（{LABEL} 流域デモ{len(TARGET_STATIONS)}局）", "環境省",
             "https://soramame.env.go.jp/download", "大気",
             "HTTP POST /soramame/download (ZIP of SJIS CSV)", "CSV/JSONL",
             LICENSE, True, len(rows),
             f"局={'/'.join(TARGET_STATIONS.values())} / 期間={months[0]}-{months[-1]}（API は直近13ヶ月のみ）"
             " / source_ref は ZIP 内 CSV 名#日時。取得元 URL は "
             f"https://soramame.env.go.jp/soramame/download?DL_KBN=3&Target_YM=<YYYYMM>&TDFKN_CD={PREF}&SKT_CD=<局コード>"
             + (f" / 取得失敗={fails}" if fails else "")
             + " / 注記(原文): 「確定値のデータについては、国立環境研究所 環境数値データベースから入手してください。」"
               "→ 本データは速報値であり確定値と一致しない場合がある。")

if __name__ == "__main__":
    main()
