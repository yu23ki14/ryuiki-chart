"""平塚市の大気環境状況 確定値1時間値（download-kakutei.php）。

フォーム送信・同意操作は一切しない。download-kakutei.php への素の初回GETの
レスポンスに、選択中年度（既定 = 最新年度）の局別CSV直リンクが
`download/{year}_{station}.csv` の形で埋め込まれており、この URL パターンに
局番・年度を差し込んだ直GETだけで全ファイルが取得できることを実機で確認済み
（例: https://hiratsukataiki.sakura.ne.jp/download/2013_101.csv も無条件で200）。

局番・年度は download-kakutei.php のHTMLから動的に取得する（ハードコードしない）:
  - 年度: <select name="year"> の <option value="YYYY">
  - 局番・局名: 表内の <a href=./download/{year}_{code}.csv> と対応する <th>局名</th>
項目CD→項目名/単位の対応表は同ページからリンクされる「ファイル説明」PDF
（images/1hour_description.pdf）から pdfplumber で抽出する（推測で埋めない）。

## 出力の粒度
1時間値をそのまま展開すると 5局×13年度×15項目×365日×24時間 ≒ 850万レコードになり
デモ用D1には載らない。そのため **日別集計を主出力** とする
(source_id="hiratsuka_taiki")。1時間値の原本65ファイルは
data/raw/hiratsuka_taiki/ にそのまま保存する（捨てない）。

## 欠測センチネル値の判定根拠（実測 + 公式PDFの記述で確認）
images/1hour_description.pdf に:
  「測定データは４桁で構成されています。なお、測定データが欠測の場合は「9999」、
    未測定の場合は「9998」という数値で表しています。」
とあり、実際に 2025_101.csv 等でも 9999 が出現し（9998 は今回DLした範囲では未出現）、
他の値域とは明確に分離している（多くの項目で最大値=9999、それ以外は3桁以下）。
よって **9999 と 9998 を欠測として扱い、daily_mean/max/min の計算対象から除外** する。

0 を欠測扱いにしない根拠: 例えば雨量(RAIN, 016)は 8760時間中 8198時間が0で、
これは「降雨なしの実測」であり欠測ではない（雨量計は無降雨時に0を記録するのが正常動作）。
SO2/NOx/SPM等でも0は多数出現するがサイト側の欠測表記は9999/9998のみと明記されているため、
0はそのまま有効値として扱う。

PM2.5(011) は負値（実測で最小 -5 相当）が出現するが、koumoku.php（項目別日報ページ）の
注記に「自動測定機の測定原理における誤差要因等により、微小粒子状物質濃度が非常に低い場合に
１時間値がマイナス値となることがありますが、１日平均値を算出する際を含め、マイナス値を
そのままの値として扱うこととしています。」と明記されており、負値は欠測ではなく実測値として
そのまま daily_mean 等の計算に含める。

また、公式PDFには記載が無いが、65ファイル全数を走査したところ "-999" が
2015_101.csv（2015年度・大野公民館）の 2016-03-01 12時 の 項目004(NOx) と 項目009(THC) の
2セルにのみ出現した。他の負値はすべて項目014(TEMP, 単位0.1℃)で -76〜-45（=-7.6〜-4.5℃相当）と
なっており、複数局・同日（冬季早朝）で相関して出現する実測の低温と整合するため欠測扱いにしないが、
同一時刻に無関係な2項目が揃って同じ丸い負数(-999)になるのは実測としてあり得ないため、
旧システム由来のエラーコードと判断し -999 も欠測として扱う（SENTINEL_STRSに追加）。

項目CD 012（風向 WD）は N/NNE/NE/.../Calm という方位の文字列であり数値ではないため、
daily_mean/daily_max/daily_min は算出せず null にする。n_valid/n_missing は
「9999/9998でない（=方位が記録されている）」を有効として集計する（平均できない旨はここに明記）。

想定外の非数値トークン（上記いずれにも当たらないもの）が numeric な項目に出現した場合は
欠測として扱った上で warnings に記録し、報告時に握り潰さず列挙する（docs/nextstep.md F-1 対策）。
"""
import sys, re, pathlib, warnings, itertools
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import *
import numpy as np
import pandas as pd

BASE = "https://hiratsukataiki.sakura.ne.jp"
PAGE = f"{BASE}/download-kakutei.php"
KOUMOKU_PAGE = f"{BASE}/koumoku.php"
PDF_URL = f"{BASE}/images/1hour_description.pdf"
RAWD = RAW / "hiratsuka_taiki"
RAWD.mkdir(parents=True, exist_ok=True)

SID_DAILY = "hiratsuka_taiki"
SID_ST = "hiratsuka_taiki_stations"

SENTINEL_STRS = {"9999", "9998", "-999"}
# 9999=欠測 / 9998=未測定 は images/1hour_description.pdf に明記（実測でも9999を確認、9998は今回範囲では未出現）。
# -999 はPDFに記載が無いが、65ファイル全数走査で "-999" は
#   2015_101.csv（2015年度=大野公民館）の 2016-03-01 12時 の 項目004(NOx) と 項目009(THC) の
#   2セルにのみ出現（他の負値はすべて項目014=TEMP(0.1℃)で、-76〜-45 =-7.6〜-4.5℃相当。
#   複数局・同日で相関して出現する冬季早朝の実測低温と整合し、これらは欠測ではない）。
# 同一時刻に無関係な2項目（NOx・THC）が揃って同じ丸い負数になるのは実測としてあり得ず、
# 旧システム由来のエラーコードと判断し欠測として扱う（判断根拠として本コメントに残す）。

LICENSE = ("サイト上に利用規約・ライセンス表記は見当たらず。download-kakutei.php に"
           "「このサイトに掲載している測定値以外の測定値の入手については、環境保全課へ"
           "お問い合わせください。」とあるのみ。明示的な二次配布許諾なしと判断し"
           "redistributable=0 とする（内部デモとしては取得する）。")


def detect_encoding(data: bytes) -> str:
    if all(b < 128 for b in data):
        return "utf-8"   # 純ASCIIならどの候補でも同じ結果になる
    for enc in ("cp932", "utf-8-sig", "utf-8"):
        try:
            data.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "cp932"


def fetch_stations_and_years():
    """download-kakutei.php の素のGETから 年度<select> と 局番/局名テーブルを動的取得。"""
    r = get(PAGE)
    html = r.content.decode(detect_encoding(r.content), errors="replace")
    years = sorted(set(int(y) for y in re.findall(r'<option value="(\d{4})"[^>]*>\d{4}年度', html)))
    stations = {}
    for m in re.finditer(
        r'<tr><th>([^<]+)</th><td>[^<]*</td>'
        r'<td><strong><a href=\./download/\d{4}_(\d{3})\.csv>',
        html,
    ):
        name, code = m.group(1), m.group(2)
        stations.setdefault(code, name)
    caveats = re.findall(r'<p>(※[^<]+)</p>', html)
    return years, sorted(stations.items()), caveats, html


def fetch_koumoku_caveats():
    r = get(KOUMOKU_PAGE)
    html = r.content.decode(detect_encoding(r.content), errors="replace")
    notes = re.findall(r"<li>([^<]+)</li>", html) + re.findall(r"<p>(※[^<]+)</p>", html)
    return [n.strip() for n in notes if n.strip()]


def fetch_item_table():
    """download-kakutei.php からリンクされる「ファイル説明」PDF から項目CD対応表を抽出。"""
    dest = RAWD / "_1hour_description.pdf"
    download(PDF_URL, dest)
    import pdfplumber
    with pdfplumber.open(dest) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    items = {}
    for line in text.splitlines():
        m = re.match(r"^(\d{3})\s+(\S+（[^）]+）)\s+(\S+)\s*$", line.strip())
        if m:
            code, name, unit = m.groups()
            items[code] = (name, unit)
    stations_doc = {}
    for line in text.splitlines():
        m = re.match(r"^(\d{3})\s+(\S+)\s*$", line.strip())
        if m and m.group(1) not in items:
            stations_doc[m.group(1)] = m.group(2)
    sentinel_note = None
    m = re.search(r"測定データが欠測の場合は「(\d+)」、未測定の場合は「(\d+)」という数値で表しています。", text)
    if m:
        sentinel_note = m.group(0)
    return items, stations_doc, sentinel_note, text


def process_file(path: pathlib.Path, year: int, station_code: str, items_table, warn):
    data = path.read_bytes()
    enc = detect_encoding(data)
    df = pd.read_csv(path, header=None, dtype=str, encoding=enc, na_filter=False)
    if df.shape[1] != 27:
        warn.append(f"{year}_{station_code}: 想定27列に対し{df.shape[1]}列 (skip)")
        return []
    hour_cols = list(range(3, 27))
    item_arr = df[2].to_numpy()
    station_arr = df[1].to_numpy()
    mismatch = station_arr != station_code
    if mismatch.any():
        warn.append(f"{year}_{station_code}: ファイル内局番が不一致な行が{int(mismatch.sum())}件")

    raw_df = df[hour_cols]
    num_df = raw_df.apply(pd.to_numeric, errors="coerce")
    num_arr = num_df.to_numpy(dtype=float)
    raw_arr = raw_df.to_numpy(dtype=str)

    sentinel = np.isin(raw_arr, list(SENTINEL_STRS))
    is_wd = (item_arr == "012")[:, None]
    nonparseable = np.isnan(num_arr)
    unexpected_nonnumeric = nonparseable & ~is_wd & ~sentinel
    if unexpected_nonnumeric.any():
        idxs = np.argwhere(unexpected_nonnumeric)[:5]
        samples = [(item_arr[i], raw_arr[i, j]) for i, j in idxs]
        warn.append(f"{year}_{station_code}: 想定外の非数値トークン {int(unexpected_nonnumeric.sum())}件 例={samples}")

    valid_mask = (~sentinel) & (~unexpected_nonnumeric)
    missing_mask = ~valid_mask
    n_valid = valid_mask.sum(axis=1)
    n_missing = missing_mask.sum(axis=1)

    numeric_valid = np.where(valid_mask & ~is_wd, num_arr, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        daily_mean = np.nanmean(numeric_valid, axis=1)
        daily_max = np.nanmax(numeric_valid, axis=1)
        daily_min = np.nanmin(numeric_valid, axis=1)

    obs_date = pd.to_datetime(df[0], format="%Y%m%d").dt.strftime("%Y-%m-%d").to_numpy()

    rows = []
    for i in range(len(df)):
        code = item_arr[i]
        name_ja, unit_ja = items_table.get(code, (None, None))
        if code not in items_table:
            warn.append(f"項目CD {code} が説明PDFの対応表に無い（name/unit=null）")
        dm = daily_mean[i]
        dmax = daily_max[i]
        dmin = daily_min[i]
        rows.append({
            "station_code": station_code,
            "station_name_ja": None,   # main() で埋める
            "obs_date": obs_date[i],
            "item_code": code,
            "item_name_ja": name_ja,
            "unit_ja": unit_ja,
            "daily_mean": None if np.isnan(dm) else float(dm),
            "daily_max": None if np.isnan(dmax) else float(dmax),
            "daily_min": None if np.isnan(dmin) else float(dmin),
            "n_valid": int(n_valid[i]),
            "n_missing": int(n_missing[i]),
            "source_id": SID_DAILY,
            "source_ref": f"{BASE}/download/{year}_{station_code}.csv#{code}/{obs_date[i]}",
        })
    return rows


def main():
    years, stations, dl_caveats, _ = fetch_stations_and_years()
    print(f"  years: {years} ({len(years)})")
    print(f"  stations: {stations}")
    items_table, stations_doc, sentinel_note, _ = fetch_item_table()
    print(f"  items from PDF: {sorted(items_table)} ({len(items_table)})")
    print(f"  sentinel note (PDF): {sentinel_note}")
    koumoku_notes = fetch_koumoku_caveats()

    if stations_doc and set(stations_doc) != set(dict(stations)):
        print(f"  [warn] station codes differ HTML={sorted(dict(stations))} vs PDF={sorted(stations_doc)}")

    station_names = dict(stations)
    fails = []
    warn = []
    all_rows = []

    combos = list(itertools.product(years, [c for c, _ in stations]))
    print(f"  total combos: {len(combos)}")
    for year, code in combos:
        dest = RAWD / f"{year}_{code}.csv"
        url = f"{BASE}/download/{year}_{code}.csv"
        try:
            download(url, dest)
        except Exception as e:
            fails.append(f"{year}_{code}: download failed ({e})")
            print(f"  [fail] {year}_{code}: {e}")
            continue
        try:
            rows = process_file(dest, year, code, items_table, warn)
        except Exception as e:
            fails.append(f"{year}_{code}: parse failed ({e})")
            print(f"  [fail] {year}_{code}: parse {e}")
            continue
        for r in rows:
            r["station_name_ja"] = station_names.get(code)
        all_rows.extend(rows)
        print(f"  {year}_{code}: +{len(rows)} rows (cumulative {len(all_rows)})")

    cols = ["station_code", "station_name_ja", "obs_date", "item_code", "item_name_ja",
            "unit_ja", "daily_mean", "daily_max", "daily_min", "n_valid", "n_missing",
            "source_id", "source_ref"]
    if all_rows:
        pd.DataFrame(all_rows, columns=cols).to_csv(PROC / f"{SID_DAILY}.csv", index=False, encoding="utf-8")
        write_jsonl(SID_DAILY, all_rows)

    st_rows = [{
        "station_code": c,
        "station_name_ja": n,
        "address_ja": None,   # サイト内に局ごとの住所記載なし（環境保全課の代表住所のみ）。推測で埋めない。
        "lat": None,
        "lon": None,
        "source_id": SID_ST,
        "source_ref": PAGE,
    } for c, n in stations]
    st_cols = ["station_code", "station_name_ja", "address_ja", "lat", "lon", "source_id", "source_ref"]
    if st_rows:
        pd.DataFrame(st_rows, columns=st_cols).to_csv(PROC / f"{SID_ST}.csv", index=False, encoding="utf-8")
        write_jsonl(SID_ST, st_rows)

    notes_daily = (
        "1行=1局×1日×1項目、24時間値を集計。欠測センチネル: PDF記載「" + str(sentinel_note) +
        "」を実測でも確認（9999が全項目の最大値として出現、9998は今回の取得範囲では未出現だが仕様通り欠測扱い）。"
        " 0は欠測扱いにしない(例: 雨量016は8760時間中8198時間が0=無降雨の実測)。"
        " PM2.5(011)の負値は koumoku.php 注記により実測値としてそのまま平均に含める。"
        " 追加で発見した非公式センチネル: '-999' が65ファイル中2セルのみ出現"
        "（2015_101.csv 2016-03-01 12時 の item004=NOx と item009=THC、同一時刻に無関係2項目が揃って"
        "同じ丸い負数になるのは実測としてあり得ないため欠測扱いに追加。"
        "他の負値(item014=TEMP, -76〜-45=-7.6〜-4.5℃相当)は複数局・同日の冬季早朝実測と整合するため欠測扱いにしていない)。"
        " 項目012(風向WD)はN/NNE/.../Calm等の文字列でありdaily_mean/max/minは算出せずnull"
        "（n_valid/n_missingのみ9999/9998判定で集計）。"
        f" download-kakutei.php 上の注記: {dl_caveats}."
        f" koumoku.php の注記: {koumoku_notes}."
        + (f" 警告: {warn}" if warn else "")
        + (f" 取得失敗: {fails}" if fails else "")
    )
    register(SID_DAILY, "平塚市 大気環境状況 確定値1時間値（日別集計）", "平塚市環境保全課", PAGE,
              "大気", "GET直リンク download/{year}_{station}.csv（フォーム送信なし、局番/年度はHTMLから動的取得）",
              "CSV/JSONL", LICENSE, False, len(all_rows), notes_daily)

    register(SID_ST, "平塚市 大気環境状況 測定局一覧", "平塚市環境保全課", PAGE,
              "大気", "download-kakutei.php HTML + ファイル説明PDF", "CSV/JSONL", LICENSE, False,
              len(st_rows),
              "緯度経度・住所はサイト内に局別の記載が無いため null（ジオコーディング等での推測はしていない）。"
              f" PDF記載の局番/局名: {stations_doc}")

    print(f"\n  DONE. daily rows={len(all_rows)}  stations={len(st_rows)}")
    print(f"  fails ({len(fails)}): {fails}")
    print(f"  warnings ({len(warn)}): {warn[:20]}{'...' if len(warn) > 20 else ''}")


if __name__ == "__main__":
    main()
