"""相模原市オープンデータ「大気の状況」大気汚染常時監視測定結果（1時間値）
平成27年度〜令和6年度の年度別 CSV（横持ち: 1行 = 局×項目×日、列 = 1時〜24時）を
縦持ち long に変換する。CKAN の package_show からリソース一覧を動的に取得。
単位は公開元に記載がないため換算せず原表記のまま出力する（推測変換しない）。
"""
import sys, io, csv, re, datetime, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import *
import pandas as pd

SID_ST = "sagamihara_taiki_stations"
SID_TS = "sagamihara_taiki_hourly"
PKG = "f35dfc4d-cdd9-4b85-81c0-55503b2cfeb6"
API = "https://opendata.city.sagamihara.kanagawa.jp/api/3/action/package_show"
RAWD = RAW/"sagamihara_taiki"; RAWD.mkdir(parents=True, exist_ok=True)
LICENSE = ("クリエイティブ・コモンズ 表示 (CC BY) "
           "https://opendata.city.sagamihara.kanagawa.jp/dataset/taiki")

# 行数を抑えるため流域デモに必要な (局CD, 項目名) に限定
TARGETS = {("105", "OX"), ("101", "RAIN")}   # 出力サイズ抑制のため2系列に限定
# （同一CSVに SPM/PM25-1h/NO2/TEMP 等も含まれるので TARGETS を広げれば再抽出可能）

UNIT_NOTE = ("単位は公開元（相模原市オープンデータ）に記載がないため換算していない。"
             "令和6年度データの値域は TEMP 最大398 / HUM 最大997 / WS 最大115 / OX 最大149 / "
             "SPM 最大131 / PM25-1h 最大70 / RAIN 最大330 であり、気温・湿度・風速は1/10、"
             "OX・SPM は 1/1000（それぞれ ppm・mg/m3）の整数表現と推測されるが、"
             "公式定義を確認できないため value は原表記のままとし unit は NULL とする。")

# 年度によりヘッダ行の列数(31)と データ行の列数(55) が食い違う（末尾に無名のフラグ列が24列ある）ため
# ヘッダを使わず位置で列名を割り当てる。また 平成27年度分のみ UTF-8(BOM)。
BASE_COLS = ["局CD", "局名", "項目CD", "項目名", "年", "月", "日"] + [f"{h}時" for h in range(1, 25)]

def read_wide(path):
    last = None
    for enc in ("cp932", "utf-8-sig"):
        try:
            raw = pd.read_csv(path, encoding=enc, dtype=str, header=None, skiprows=1)
            break
        except Exception as e:
            last = e; raw = None
    if raw is None:
        raise last
    n = raw.shape[1]
    names = BASE_COLS[:n] + [f"extra_{i}" for i in range(len(BASE_COLS), n)]
    raw.columns = names
    return raw

def resources():
    j = get_json(API, params={"id": PKG})
    out = []
    for r in j["result"]["resources"]:
        nm = r.get("name") or ""
        if "1時間値" not in nm: continue
        fy = to_fiscal_year(nm)
        out.append((fy, nm, r["url"]))
    return sorted(out)

def main():
    res = resources()
    print(f"  resources: {len(res)}  years={[y for y, _, _ in res]}")
    rows, stations, fails = [], {}, []
    for fy, nm, url in res:
        dest = RAWD/f"{fy}.csv"
        try:
            download(url, dest)
            df = read_wide(dest)
        except Exception as e:
            fails.append(f"{fy}: {e}"); print(f"  [warn] {fy}: {e}"); continue
        hours = [c for c in df.columns if re.fullmatch(r"(\d+)時", str(c))]
        for _, r in df.iterrows():
            code = str(r["局CD"]).strip()
            item = str(r["項目名"]).strip()
            stations.setdefault(code, str(r["局名"]).strip())
            if (code, item) not in TARGETS: continue
            y, mo, d = (to_number(r[k])[0] for k in ("年", "月", "日"))
            if not all(isinstance(v, int) for v in (y, mo, d)): continue
            try:
                base = datetime.datetime(y, mo, d)
            except ValueError:
                continue
            for hc in hours:
                hh = int(re.fullmatch(r"(\d+)時", hc).group(1))
                raw = r[hc]
                if raw is None or str(raw).strip() in ("", "nan"): continue
                v, kind = to_number(raw)
                # 「1時」= 00:00〜01:00 の値。JMA/そらまめ君同様、時刻ラベルをそのまま採用
                ts = (base + datetime.timedelta(hours=hh)).strftime("%Y-%m-%dT%H:%M:%S+09:00")
                rows.append({
                    "station_id": "sagamihara_" + code,
                    "station_name_ja": stations[code],
                    "lat": None, "lon": None,
                    "datetime": ts, "period": "hour",
                    "variable": item.lower().replace("-", "_").replace(".", "_"),
                    "variable_ja": item,
                    "value": float(v) if kind in ("int", "float") else None,
                    "value_raw": str(raw).strip(),
                    "unit": None,
                    "fiscal_year": fy,
                    "source_id": SID_TS,
                    "source_ref": f"{fy}.csv#{code}/{item}/{y}-{mo:02d}-{d:02d}T{hh:02d}",
                })
        print(f"  {fy} ({nm}): cumulative {len(rows)}")

    st = [{"station_id": "sagamihara_" + c, "station_code": c, "station_name_ja": n,
           "municipality_ja": "相模原市", "lat": None, "lon": None,
           "source_id": SID_ST, "source_ref": f"{PKG}#{c}"} for c, n in sorted(stations.items())]
    if st:
        with open(PROC/f"{SID_ST}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, list(st[0].keys())); w.writeheader(); w.writerows(st)
        write_jsonl(SID_ST, st)
    register(SID_ST, "相模原市 大気汚染常時監視 測定局一覧", "相模原市",
             "https://opendata.city.sagamihara.kanagawa.jp/dataset/taiki", "大気",
             "CKAN package_show + 年度別CSV", "CSV/JSONL", LICENSE, True, len(st),
             "年度別1時間値CSVの局CD/局名から抽出。緯度経度は公開データに含まれないため NULL。")

    if rows:
        pd.DataFrame(rows).to_csv(PROC/f"{SID_TS}.csv", index=False, encoding="utf-8")
        write_jsonl(SID_TS, rows)
    register(SID_TS, "相模原市 大気汚染常時監視測定結果 1時間値（流域デモ抽出）", "相模原市",
             "https://opendata.city.sagamihara.kanagawa.jp/dataset/taiki", "大気",
             "CKAN 経由 年度別CSV ダウンロード", "CSV/JSONL", LICENSE, True, len(rows),
             f"抽出条件: {sorted(TARGETS)} / 年度={res[0][0]}-{res[-1][0]} / 縦持ち long。" + UNIT_NOTE
             + (" / 取得失敗=" + "; ".join(fails) if fails else ""))

if __name__ == "__main__":
    main()
