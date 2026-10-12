"""モニタリングサイト1000 サンゴ礁調査（SAN01）の奄美分（moni1000_coral_amami、region jp-46）を xlsx から抽出する。

入力（手元のみ。**これ以上の取得はしない**）: data/raw/moni1000/extracted/SAN01/
  SAN01_調査地点基礎情報.xlsx（地点の緯度経度〔度分秒〕・地形・底質）
  SAN01_2003-2017_サンゴ礁調査結果.xlsx（年度 × 地点の観測。33 列）
2026-10-12 にオーナーの明示の承認のもと、責任者がフォームを送信して取得した（申告内容は docs/COLLECTOR_CONTRACT.md）。

対象: 中ブロック＝奄美群島で、座標が奄美大島とその周辺（加計呂麻島・請島・与路島を含む）に入る地点。
他の島（徳之島・沖永良部・与論など）の地点が混ざっていれば外し、外したものを標準出力に出す。
出力: data/processed/moni1000_coral_amami.csv（m11_moni1000_coral.py が表に入れる）と source_registry への register。
値は原文のまま *_raw に持ち、数値に直せるものだけ数値列に入れる（'<5'・'-'・'20-30' 等は NULL）。import だけでは何も実行しない。
"""
import csv
import datetime
import re
import sys

sys.path.insert(0, "scripts")

SOURCE_ID = "moni1000_coral_amami"
SOURCE_REF = "https://www.biodic.go.jp/moni1000/findings/data/index.html (SAN01.zip)"
BLOCK = "奄美群島"
# 奄美大島とその周辺（加計呂麻島・請島・与路島）。徳之島（27.7N）・沖永良部（27.4N）・与論（27.0N）は外れる
BBOX = {"lat": (27.9, 28.7), "lon": (128.9, 129.9)}
SRC_DIR = "moni1000/extracted/SAN01"
BASE_XLSX = "SAN01_調査地点基礎情報.xlsx"
RESULT_XLSX = "SAN01_2003-2017_サンゴ礁調査結果.xlsx"

# 結果ファイルの列の位置（0 始まり。33 列）。数値列は (名前, 位置)。名前_raw に原文、名前に数値
PAIR_COLS = [
    ("observe_minutes", 9), ("cover_pct", 10), ("bleach_all_pct", 11), ("bleach_acropora_pct", 12),
    ("dead_all_pct", 13), ("dead_acropora_pct", 14), ("recruits_per_m2", 17), ("table_acropora_size_cm", 18),
    ("cots_per_15min", 19), ("cots_dominant_size_cm", 21), ("cots_predation_pct", 23), ("snail_predation_pct", 25),
    ("spss_kg_m3", 26), ("grouper_n", 28), ("wrasse_n", 29), ("parrotfish_n", 30),
]
TEXT_COLS = [
    ("growth_class", 15), ("growth_type_ja", 16), ("cots_class", 20), ("cots_size_range_cm", 22),
    ("snail_class", 24), ("spss_class", 27), ("disease", 31), ("note_ja", 32),
]
FIELDS = (
    ["record_id", "source_id", "source_ref", "fiscal_year", "block_ja", "site_no", "site_name_ja", "spot_no",
     "spot_name_ja", "prefecture_ja", "lat", "lon", "lat_dms_raw", "lon_dms_raw", "landform_ja", "substrate_ja",
     "area_m_raw", "depth_range_m_raw", "observed_on", "investigator_ja", "method"]
    + [x for n, _ in PAIR_COLS for x in (n + "_raw", n)] + [n for n, _ in TEXT_COLS]
)


class CoralError(RuntimeError):
    pass


def clean(v):
    """セルの値 → 前後の空白（全角含む）を除いた文字列。空は None。数は整数ならば整数の表記。"""
    if v is None:
        return None
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float) and v == int(v):
        v = int(v)
    s = str(v).strip().strip("　").strip()
    return s or None


def to_number(raw):
    """原文 → 数値。'20'・'0.5' のような素直な数だけ。'<5'・'-'・'20-30'・'20<' などは None（代入しない）。"""
    if raw is None or not re.fullmatch(r"-?\d+(\.\d+)?", raw):
        return None
    return float(raw)


def dms_to_deg(deg, minute, sec):
    """度分秒 → 十進の度（7 桁に丸める）。どれかが無ければ None（全国分には座標の無い行がある。奄美の行では build_rows が止める）。"""
    if deg is None or minute is None or sec is None:
        return None
    d, m, s = float(deg), float(minute), float(sec)
    if not (0 <= m < 60 and 0 <= s < 60):
        raise CoralError(f"度分秒が範囲外: {deg} {minute} {sec}")
    return round(d + m / 60 + s / 3600, 7)


def dms_text(deg, minute, sec):
    if deg is None or minute is None or sec is None:
        return None
    return f"{clean(deg)}°{clean(minute)}′{clean(sec)}″"


def in_scope(lat, lon):
    return BBOX["lat"][0] <= lat <= BBOX["lat"][1] and BBOX["lon"][0] <= lon <= BBOX["lon"][1]


def load_base(rows):
    """地点基礎情報の行 → {(サイトNo, スポットNo): 地点}。中ブロック＝奄美群島の行だけ。"""
    out = {}
    for r in rows:
        if clean(r[0]) != BLOCK or r[1] is None or r[4] is None:     # 全国分には書式の崩れた行もあるので、奄美群島の行だけ読む
            continue
        key = (int(r[1]), int(r[4]))
        if key in out:
            raise CoralError(f"地点基礎情報に重複: {key}")
        out[key] = {
            "block_ja": clean(r[0]), "site_name_ja": clean(r[2]), "prefecture_ja": clean(r[3]), "spot_name_ja": clean(r[5]),
            "lat": dms_to_deg(r[6], r[7], r[8]), "lon": dms_to_deg(r[9], r[10], r[11]),
            "lat_dms_raw": dms_text(r[6], r[7], r[8]), "lon_dms_raw": dms_text(r[9], r[10], r[11]),
            "landform_ja": clean(r[12]), "substrate_ja": clean(r[13]), "area_m_raw": clean(r[14]),
            "depth_range_m_raw": clean(r[15]),
        }
    return out


def build_rows(base_rows, result_rows):
    """(地点基礎情報の行, 結果の行) → (出力の行, 外した行の説明)。奄美大島とその周辺だけ。行数は保存する（落とすのは範囲外だけ）。"""
    base = load_base(base_rows)
    out, dropped, ids = [], [], set()
    for r in result_rows:
        if r[0] is None or clean(r[1]) != BLOCK:
            continue
        site_no, spot_no, year = int(r[2]), int(r[4]), int(r[0])
        b = base.get((site_no, spot_no))
        if b is None:
            raise CoralError(f"地点基礎情報に無い地点: サイト{site_no} スポット{spot_no}")
        if b["lat"] is None or b["lon"] is None:
            raise CoralError(f"奄美のスポットに座標が無い: サイト{site_no} スポット{spot_no}")
        if not in_scope(b["lat"], b["lon"]):
            dropped.append(f"{year} サイト{site_no} {clean(r[3])} スポット{spot_no} {clean(r[5])} ({b['lat']}, {b['lon']})")
            continue
        rid = f"{SOURCE_ID}:{year}:{site_no}:{spot_no}"
        if rid in ids:
            raise CoralError(f"record_id が重複: {rid}")
        ids.add(rid)
        d = r[6]
        if not isinstance(d, (datetime.date, datetime.datetime)):
            raise CoralError(f"調査日が日付でない: {rid} {d!r}")
        row = {k: None for k in FIELDS} | b | {
            "record_id": rid, "source_id": SOURCE_ID, "source_ref": SOURCE_REF, "fiscal_year": year,
            "site_no": site_no, "spot_no": spot_no, "site_name_ja": clean(r[3]) or b["site_name_ja"],
            "spot_name_ja": clean(r[5]) or b["spot_name_ja"], "observed_on": d.strftime("%Y-%m-%d"),
            "investigator_ja": clean(r[7]), "method": clean(r[8]),
        }
        for name, i in PAIR_COLS:
            raw = clean(r[i])
            row[name + "_raw"], row[name] = raw, to_number(raw)
        for name, i in TEXT_COLS:
            row[name] = clean(r[i])
        out.append(row)
    return out, dropped


def read_sheet(path):
    import openpyxl
    ws = openpyxl.load_workbook(path, data_only=True).worksheets[0]
    return [r for r in ws.iter_rows(min_row=2, values_only=True)]


def main():
    from common import PROC, RAW, register
    rows, dropped = build_rows(read_sheet(RAW / SRC_DIR / BASE_XLSX),
                               read_sheet(RAW / SRC_DIR / RESULT_XLSX))
    if not rows:
        raise CoralError("奄美の行が 0 件")
    path = PROC / "moni1000_coral_amami.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"[write] {path} {len(rows)} rows / 地点 {len({(r['site_no'], r['spot_no']) for r in rows})} / 範囲外で外した {len(dropped)} 行")
    for x in dropped:
        print("  外した:", x)
    register(
        source_id=SOURCE_ID,
        name="モニタリングサイト1000 サンゴ礁調査（奄美大島とその周辺のスポットのみ抽出）",
        publisher="環境省生物多様性センター",
        url="https://www.biodic.go.jp/moni1000/findings/data/index.html",
        category="生態系モニタリング(サンゴ礁)",
        access_method="2026-10-12 オーナー承認のもとフォーム送信で取得した SAN01.zip（申告内容は docs/COLLECTOR_CONTRACT.md）。中ブロック=奄美群島の座標が奄美大島周辺のスポットを抽出",
        fmt="XLSX->CSV(UTF-8)",
        license_="生物多様性センターウェブサイト利用規約(要事前アンケート回答)",
        redistributable=1,
        record_count=len(rows),
        notes=("2026-10-12 オーナー承認のもとフォーム送信で取得（申告内容は docs/COLLECTOR_CONTRACT.md）。これ以上の取得はしない。"
               "地点×年度（2004〜2017年度）の観測値で、種の出現ではない。被度などは原文の文字列を *_raw に残し、数値に直せるものだけ数値列に入れる。"
               "データ出典の明示例: 「環境省・モニタリングサイト1000プロジェクトにより松本毅、興克樹、長田智史、岩尾研二、梶原健次、吉田稔、木村匡、上野光弘、"
               "佐々木哲朗、清本正人、須之部友基、平林勲、目崎拓真、出羽真一、出羽尚子、野島哲が2020年に提供した"
               "（SAN01.zip, http://www.biodic.go.jp/moni1000/findings/data/index.html よりダウンロード）。」"),
    )


if __name__ == "__main__":
    main()
