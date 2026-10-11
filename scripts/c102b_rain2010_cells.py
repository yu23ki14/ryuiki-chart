"""2010年奄美豪雨（京大防災研の速報・鹿大の報告書）の雨量・被害の数値を、行政文書の cells・notes にする。

設計: docs/plans/AMAMI_STEP3B.md。**数値という事実だけ**を入れる（原本の PDF は再配布しない）。OCR は使わない:
本文と鹿大 p38 の表-2 は文字情報から、鹿大 p2（文字層が壊れた序文）と p17（画像の被害状況）は目で読んだ値を SPEC に置く。

流れ:
1. SPEC（下の `SPEC`。表 × 行 × 列の値・印字・単位・原文の文）から cells の行を作る。
2. PDF が手元にあれば（pdfplumber が要る。無ければ警告して飛ばす。書き込みには必須）、本文の数値の文が PDF に現れること、
   p38 の表-2 が SPEC と一致することを検査する。p38 の bbox は pdfplumber のセル座標。
3. 検算（§5）: p17 の市町村の和 = 合計、表-2 の値の形、気象庁（名瀬・古仁屋）との突き合わせ、出典間の突き合わせ。
   出典間の食い違いは**宣言した差**（DECLARED_DIFFS）として列挙し、過不足なく一致しなければ止める。
4. verified_by: 本文・p38（extractor=manual:pdftext）は、検算の突き合わせが通ったセルが `auto:xtext+arith`（1.0）、
   突き合わせ先が無いものは `claude(text)`（0.9）。p2・p17（extractor=manual:vision）は `claude(vision)`（0.9。人の見直し前）。

fiscal_year は全セル NULL（単発の事象。DOC_SERIES_WHERE に入れない。era_raw に期間の原文）。
使い方: python3 scripts/c102b_rain2010_cells.py [--dry-run] [--no-register]
"""
import argparse
import csv
import datetime
import json
import pathlib
import sqlite3
import sys
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import common
import doccells

ROOT = common.ROOT
RAW_DIR = "data/raw/amami_rain2010"
SCRIPT_ID = "c102b_rain2010_cells"
JMA_CSV = ROOT / "scripts/tests/fixtures/amami_rain2010/jma_check.csv"
JMA_DIR = ROOT / RAW_DIR / "jma_check"
LICENSE = doccells.LICENSE_NOTE_UNSTATED

DPRI, KAGO = "dpri_amami_gouu_sokuho_2011", "kagoshima_univ_amami_gouu_2012"
DOCS = {
    DPRI: dict(
        title="2010年10月奄美大島豪雨災害調査速報",
        publisher="京都大学防災研究所（自然災害研究協議会災害調査団。竹林洋史）",
        url="https://www.dpri.kyoto-u.ac.jp/web_j/contents/event_text/20110221.pdf",
        file="20110221.pdf", n_pages=5, fiscal_year=2010,
        source_id="dpri_gouu2010_amami", source_name="京都大学防災研究所 2010年奄美豪雨の調査速報（本文の雨量・被害）"),
    KAGO: dict(
        title="「2010年奄美豪雨災害の総合的調査研究」報告書",
        publisher="鹿児島大学奄美豪雨災害調査委員会",
        url="https://bousai.kagoshima-u.ac.jp/wpo/wp-content/uploads/2024/03/2010_gouu.pdf",
        file="2010_gouu.pdf", n_pages=191, fiscal_year=2011,
        source_id="kagoshima_univ_gouu2010_amami", source_name="鹿児島大学 2010年奄美豪雨災害の総合的調査研究報告書（雨量・被害）"),
}
SOURCE_PAGE = {DPRI: "https://www.dpri.kyoto-u.ac.jp/web_j/contents/event_text/20110221.pdf", KAGO: DOCS[KAGO]["url"]}

T_RAIN, T_DMG, T_FLOOD = "p1_text_rain", "p1_text_damage", "p2_text_flood"   # 京大
T_K2, T_K6, T_K16, T_K17, T_K38 = "p2_text", "p6_text", "p16_text", "p17_t1", "p38_t1"   # 鹿大
VISION_TABLES = {T_K2, T_K17}   # 目で読んだ表（文字層が壊れた序文・画像）

# ------------------------------------------------------------------ SPEC
# 本文の数値: (doc, table, page, row_key, 値の印字, 単位, 原文の文, PDF に現れるはずの断片〔空白除去後。None なら検査しない〕)
TEXT_SPEC = [
    (DPRI, T_RAIN, 1, "最大1時間雨量（名瀬）", "78", "mm/h", "1時間雨量は，最大で名瀬で78mm，住用で131mm", "最大で名瀬で78mm，住用で131mm"),
    (DPRI, T_RAIN, 1, "24時間雨量（名瀬）", "648", "mm", "24時間雨量は，名瀬で648mm，住用で703mm", "名瀬で648mm，住用で703mm"),
    (DPRI, T_RAIN, 1, "総雨量（名瀬）", "766", "mm", "総雨量は，名瀬で766mm，住用で894mmとなっており", "名瀬で766mm，住用で894mm"),
    (DPRI, T_RAIN, 1, "最大1時間雨量（住用）", "131", "mm/h", "1時間雨量は，最大で名瀬で78mm，住用で131mm", "最大で名瀬で78mm，住用で131mm"),
    (DPRI, T_RAIN, 1, "24時間雨量（住用）", "703", "mm", "24時間雨量は，名瀬で648mm，住用で703mm", "名瀬で648mm，住用で703mm"),
    (DPRI, T_RAIN, 1, "総雨量（住用）", "894", "mm", "総雨量は，名瀬で766mm，住用で894mmとなっており", "名瀬で766mm，住用で894mm"),
    (DPRI, T_DMG, 1, "死者", "3", "人", "3名の死者と485棟の全壊・半壊住家という大きな被害", "3名の死者と485棟の全壊・半壊住家"),
    (DPRI, T_DMG, 1, "全壊・半壊の住家", "485", "棟", "3名の死者と485棟の全壊・半壊住家という大きな被害", "3名の死者と485棟の全壊・半壊住家"),
    (DPRI, T_FLOOD, 2, "二級河川の数（奄美大島）", "33", "河川", "奄美大島を流れる二級河川33河川中30河川で外水氾濫及び内水氾濫が発生", "二級河川33"),
    (DPRI, T_FLOOD, 2, "氾濫した二級河川", "30", "河川", "奄美大島を流れる二級河川33河川中30河川で外水氾濫及び内水氾濫が発生", "30河川"),
    (DPRI, T_FLOOD, 2, "床上浸水", "576", "件", "床上浸水が576件，床下浸水が736件となっている", "床上浸水が576件，床下浸水が736件"),
    (DPRI, T_FLOOD, 2, "床下浸水", "736", "件", "床上浸水が576件，床下浸水が736件となっている", "床上浸水が576件，床下浸水が736件"),
    # 鹿大 p2（序文。文字層が壊れているので目で読む）
    (KAGO, T_K2, 2, "総雨量（住用町）", "891", "mm", "総雨量 住用町891mm・龍郷町881mm（はじめに。目で読んだ）", None),
    (KAGO, T_K2, 2, "総雨量（龍郷町）", "881", "mm", "総雨量 住用町891mm・龍郷町881mm（はじめに。目で読んだ）", None),
    (KAGO, T_K2, 2, "最大1時間雨量（住用町）", "131", "mm/h", "住用町の最大1時間雨量131mm（20日12〜13時）（目で読んだ）", None),
    (KAGO, T_K2, 2, "最大3時間雨量（住用町）", "354", "mm", "住用町の最大3時間雨量354mm（20日10〜13時）（目で読んだ）", None),
    # 鹿大 p6（第1章 安達・齋田）
    (KAGO, T_K6, 6, "20日の日積算雨量（住用町）", "691", "mm", "10月20日の日積算雨量は奄美市住用町で691mm", "住用町で691mm，奄美市名瀬で622mm，瀬戸内町古仁屋286.5mm"),
    (KAGO, T_K6, 6, "20日の日積算雨量（名瀬）", "622", "mm", "奄美市名瀬で622mm", "住用町で691mm，奄美市名瀬で622mm，瀬戸内町古仁屋286.5mm"),
    (KAGO, T_K6, 6, "20日の日積算雨量（古仁屋）", "286.5", "mm", "瀬戸内町古仁屋286.5mmを記録", "住用町で691mm，奄美市名瀬で622mm，瀬戸内町古仁屋286.5mm"),
    (KAGO, T_K6, 6, "全半壊の建物", "565", "棟", "建物の全半壊565棟，床上浸水130棟，床下浸水762棟等の甚大な被害", "建物の全半壊565棟，床上浸水130棟，床下浸水762棟"),
    (KAGO, T_K6, 6, "床上浸水", "130", "棟", "建物の全半壊565棟，床上浸水130棟，床下浸水762棟等の甚大な被害", "建物の全半壊565棟，床上浸水130棟，床下浸水762棟"),
    (KAGO, T_K6, 6, "床下浸水", "762", "棟", "建物の全半壊565棟，床上浸水130棟，床下浸水762棟等の甚大な被害", "建物の全半壊565棟，床上浸水130棟，床下浸水762棟"),
    (KAGO, T_K6, 6, "浸水による死者", "2", "人", "浸水で2名，裏山の崖崩れで1名の死者が出た", "浸水で2名，裏山の崖崩れで1名の死者"),
    (KAGO, T_K6, 6, "崖崩れによる死者", "1", "人", "浸水で2名，裏山の崖崩れで1名の死者が出た", "浸水で2名，裏山の崖崩れで1名の死者"),
    # 鹿大 p16（第2章 地頭薗ほか）
    (KAGO, T_K16, 16, "24時間雨量（名瀬）", "648", "mm", "24時間雨量は，奄美市名瀬で20日23時20分までに648mmとなり", "名瀬で20日23時20分までに648mm"),
    (KAGO, T_K16, 16, "20日の日雨量（名瀬）", "622", "mm", "20日の日雨量は，名瀬で622mmとなり", "20日の日雨量は，名瀬で622mm"),
    (KAGO, T_K16, 16, "最大1時間雨量（古仁屋）", "89.5", "mm/h", "1時間雨量は，瀬戸内町古仁屋で20日13時05分までに89.5mm", "瀬戸内町古仁屋で20日13時05分までに89.5mm"),
    (KAGO, T_K16, 16, "最大1時間雨量（名瀬）", "78.5", "mm/h", "奄美市名瀬で20日16時41分までに78.5mmを記録", "奄美市名瀬で20日16時41分までに78.5mm"),
    (KAGO, T_K16, 16, "被害総額（判明分）", "11,568,106", "千円", "被害総額は11,568,106千円（被害額判明分）にのぼった", "被害総額は11,568,106千円"),
    (KAGO, T_K16, 16, "土砂災害の死者", "1", "人", "土砂災害による被害は，死者1名，負傷者3名，全壊6戸，半壊1戸，一部損壊5戸", "死者1名，負傷者3名，全壊6戸，半壊1戸，一部損壊5戸"),
    (KAGO, T_K16, 16, "土砂災害の負傷者", "3", "人", "土砂災害による被害は，死者1名，負傷者3名，全壊6戸，半壊1戸，一部損壊5戸", "死者1名，負傷者3名，全壊6戸，半壊1戸，一部損壊5戸"),
    (KAGO, T_K16, 16, "土砂災害の全壊", "6", "戸", "土砂災害による被害は，死者1名，負傷者3名，全壊6戸，半壊1戸，一部損壊5戸", "死者1名，負傷者3名，全壊6戸，半壊1戸，一部損壊5戸"),
    (KAGO, T_K16, 16, "土砂災害の半壊", "1", "戸", "土砂災害による被害は，死者1名，負傷者3名，全壊6戸，半壊1戸，一部損壊5戸", "死者1名，負傷者3名，全壊6戸，半壊1戸，一部損壊5戸"),
    (KAGO, T_K16, 16, "土砂災害の一部損壊", "5", "戸", "土砂災害による被害は，死者1名，負傷者3名，全壊6戸，半壊1戸，一部損壊5戸", "死者1名，負傷者3名，全壊6戸，半壊1戸，一部損壊5戸"),
]

# 鹿大 p17 表-1 被害状況（県 2010-11-26 現在。画像を目で読んだ）。行: (row_key, 単位, [奄美市, 龍郷町, 大和村, 宇検村, 瀬戸内町, 徳之島町], 合計)。
# None は「括弧に載っていない（空欄）」。0 とは書いていない。
P17_COLS = ["奄美市", "龍郷町", "大和村", "宇検村", "瀬戸内町", "徳之島町"]
P17_ROWS = [
    ("死者", "人", [2, 1, None, None, None, None], 3),
    ("軽傷", "人", [1, 1, None, None, None, None], 2),
    ("住家全壊", "棟", [6, 3, 1, None, None, None], 10),
    ("住家半壊", "棟", [339, 125, 15, None, None, None], 479),
    ("床上浸水", "棟", [62, 24, 14, 5, 14, None], 119),
    ("床下浸水", "棟", [351, 221, 97, 4, 93, 1], 767),
    ("住家一部損壊", "棟", [11, None, None, None, None, None], 11),
    ("非住家全壊", "棟", [8, None, 4, None, None, None], 12),
    ("非住家半壊", "棟", [101, None, 1, None, None, None], 102),
]
TOTAL_COL = "合計"

# 鹿大 p38 表-2（最大時間雨量・日雨量・連続雨量）。行: (観測場所, [時間雨量, 日雨量, 連続雨量])
P38_COLS = [("時間雨量", "mm/h"), ("日雨量", "mm"), ("連続雨量", "mm")]
P38_ROWS = [
    ("奄美市住用町", ["131", "703", "893"]),
    ("奄美市名瀬", ["78.5", "648", "766.5"]),
    ("瀬戸内町古仁屋", ["89.5", "291.5", "380.5"]),
]
P38_PAGE = 38

# 序文の「浸水886棟」（床上＋床下。目で読んだ。cells ではなく検算にだけ使う）
PREFACE_FLOOD_TOTAL = 886

# ------------------------------------------------------------------ 宣言する差（出典・時点・定義が違う）
D = Decimal
DECLARED_DIFFS = {
    "住用の総雨量 京大/鹿大序文": (D(894), D(891)),
    "住用の総雨量 京大/鹿大表-2": (D(894), D(893)),
    "住用の総雨量 鹿大序文/鹿大表-2": (D(891), D(893)),
    "全壊・半壊 京大/県11-26": (D(485), D(489)),
    "全壊・半壊 京大/安達ほか": (D(485), D(565)),
    "全壊・半壊 県11-26/安達ほか": (D(489), D(565)),
    "床上浸水 京大/県11-26": (D(576), D(119)),
    "床上浸水 京大/安達ほか": (D(576), D(130)),
    "床上浸水 県11-26/安達ほか": (D(119), D(130)),
    "床下浸水 京大/県11-26": (D(736), D(767)),
    "床下浸水 京大/安達ほか": (D(736), D(762)),
    "床下浸水 県11-26/安達ほか": (D(767), D(762)),
}


# ------------------------------------------------------------------ 値・期間
def num(raw):
    return D(raw.replace(",", ""))


def era_for(table, row_key, col_key):
    if table == T_K17:
        return "2010年11月26日現在"
    if "総雨量" in row_key or col_key == "連続雨量":
        return "2010年10月18〜21日"
    if table in (T_RAIN, T_K2, T_K6, T_K16, T_K38) and any(w in row_key + col_key for w in ("雨量", "時間", "日雨量")):
        return "2010年10月20日"
    return "2010年10月豪雨"


def cell_row(doc, table, page, row_key, col_key, raw, unit, source_text, needle=None, is_total=0, bbox=None):
    return dict(doc=doc, table_id=table, page_no=page, row_key=row_key, col_key=col_key, value_raw=raw, unit=unit,
                source_text=source_text, needle=needle, is_total=is_total, bbox=bbox)


def make_spec():
    """SPEC（cells の元になる dict の列）。本文 + p17 + p38。"""
    spec = [cell_row(d, t, p, r, "値", raw, u, s, n) for d, t, p, r, raw, u, s, n in TEXT_SPEC]
    for rk, unit, vals, total in P17_ROWS:
        for ck, v in zip(P17_COLS, vals):
            spec.append(cell_row(KAGO, T_K17, 17, rk, ck, None if v is None else str(v), unit,
                                 "(内訳に記載なし)" if v is None else f"{rk} {ck} {v}{unit}"))
        spec.append(cell_row(KAGO, T_K17, 17, rk, TOTAL_COL, str(total), unit, f"{rk} 合計 {total}{unit}", is_total=1))
    for place, vals in P38_ROWS:
        for (ck, unit), v in zip(P38_COLS, vals):
            spec.append(cell_row(KAGO, T_K38, P38_PAGE, place, ck, v, unit, f"{place} " + " ".join(vals)))
    return spec


SPEC = make_spec()


def val(spec, table, row, col="値"):
    for c in spec:
        if (c["table_id"], c["row_key"], c["col_key"]) == (table, row, col):
            return None if c["value_raw"] is None else num(c["value_raw"])
    raise KeyError((table, row, col))


# ------------------------------------------------------------------ 気象庁
def jma_from_csv(path=JMA_CSV):
    """{(地点, 日付): (降水量合計, 最大1時間)}"""
    with open(path, encoding="utf-8") as f:
        return {(r["station"], r["date"]): (D(r["precip_sum_mm"]), D(r["precip_max_1h_mm"])) for r in csv.DictReader(f)}


def jma_nase_db(db_path):
    """名瀬の日別（原本 ryuiki.sqlite を mode=ro で）。"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT phenomenon_time, datastream, result FROM sensor_timeseries WHERE source_id='jma_daily_nase' "
            "AND phenomenon_time BETWEEN '2010-10-18' AND '2010-10-21' AND datastream IN ('降水量_合計','降水量_最大_1時間')").fetchall()
    finally:
        con.close()
    out = {}
    for d, ds, v in rows:
        s, m = out.get(d, (None, None))
        out[d] = (D(str(v)), m) if ds == "降水量_合計" else (s, D(str(v)))
    return {("名瀬", d): sm for d, sm in out.items() if None not in sm}


def jma_kokuya_html(path):
    """古仁屋の日別 etrn の保存 HTML（pandas が要る）。"""
    import io
    import pandas as pd
    df = pd.read_html(io.StringIO(pathlib.Path(path).read_text(encoding="utf-8")))[0]
    out = {}
    for _, r in df.iterrows():
        try:
            day = int(r.iloc[0])
        except (TypeError, ValueError):
            continue
        if 18 <= day <= 21:
            out[("古仁屋", f"2010-10-{day:02d}")] = (D(str(r.iloc[1])), D(str(r.iloc[2])))
    return out


def load_jma(root=ROOT):
    """-> (jma, 警告のリスト)。名瀬は原本 DB、古仁屋は保存 HTML から読む。どちらかが無ければ csv に落とす。"""
    try:
        db = root / "data/db/ryuiki.sqlite"
        html = root / RAW_DIR / "jma_check/daily_a1_0980.html"
        if not (db.exists() and html.exists()):
            raise FileNotFoundError("原本 DB か保存 HTML が無い")
        jma = {**jma_nase_db(db), **jma_kokuya_html(html)}
        if len(jma) != 8:
            raise ValueError(f"気象庁の日別が8行にならない: {len(jma)}")
        return jma, []
    except (FileNotFoundError, ImportError, sqlite3.Error, ValueError) as e:
        return jma_from_csv(), [f"気象庁を原本・保存 HTML から読めない（{e}）ので jma_check.csv を使った"]


# ------------------------------------------------------------------ 検算
def sum_jma(jma, station, key):
    days = [f"2010-10-{d}" for d in (18, 19, 20, 21)]
    missing = [(station, d) for d in days if (station, d) not in jma]
    if missing:
        raise doccells.IdentityError(f"気象庁の日別が足りない: {missing}")
    return sum(jma[(station, d)][key] for d in days)


def run_checks(spec, jma):
    """検算を全部通す。通らなければ doccells.IdentityError / ValueError。-> (backed {(table,row,col)}, 宣言した差の実際)。"""
    V = lambda t, r, c="値": val(spec, t, r, c)   # noqa: E731
    k = lambda t, r, c="値": (t, r, c)            # noqa: E731
    backed = set()

    # (1) 被害状況（p17）: 全行で 市町村の和 = 合計
    doccells.check_identity("p17 の市町村の和と合計", {
        rk: (sum(V(T_K17, rk, ck) or 0 for ck in P17_COLS), V(T_K17, rk, TOTAL_COL)) for rk, *_ in P17_ROWS})
    flood = V(T_K17, "床上浸水", TOTAL_COL) + V(T_K17, "床下浸水", TOTAL_COL)
    wreck = V(T_K17, "住家全壊", TOTAL_COL) + V(T_K17, "住家半壊", TOTAL_COL)
    doccells.check_identity("p17 の浸水の合計と序文の浸水886棟", {"床上＋床下": (flood, D(PREFACE_FLOOD_TOTAL))})

    # (2) 表-2 の値の形: 連続雨量は .5 刻み、時間雨量・日雨量は小数1桁以内
    for place, _ in P38_ROWS:
        for ck, _u in P38_COLS:
            v = V(T_K38, place, ck)
            ok = (v * 2 == (v * 2).to_integral_value()) if ck == "連続雨量" else (v * 10 == (v * 10).to_integral_value())
            if not ok:
                raise ValueError(f"表-2 の値の形が想定外: {place} {ck} {v}")

    # (3) 気象庁との突き合わせ（label, 気象庁の値, 報告書の値, 裏付けるセル）
    N, K = "名瀬", "古仁屋"
    j20 = lambda s, i: jma[(s, "2010-10-20")][i]   # noqa: E731
    pairs = [
        ("名瀬 18〜21日の和 = 表-2 連続雨量", sum_jma(jma, N, 0), V(T_K38, "奄美市名瀬", "連続雨量"), [k(T_K38, "奄美市名瀬", "連続雨量")]),
        ("名瀬 20日 = 安達ほか", j20(N, 0), V(T_K6, "20日の日積算雨量（名瀬）"), [k(T_K6, "20日の日積算雨量（名瀬）")]),
        ("名瀬 20日 = 地頭薗ほか", j20(N, 0), V(T_K16, "20日の日雨量（名瀬）"), [k(T_K16, "20日の日雨量（名瀬）")]),
        ("名瀬 最大1時間 = 表-2", j20(N, 1), V(T_K38, "奄美市名瀬", "時間雨量"), [k(T_K38, "奄美市名瀬", "時間雨量")]),
        ("名瀬 最大1時間 = 地頭薗ほか", j20(N, 1), V(T_K16, "最大1時間雨量（名瀬）"), [k(T_K16, "最大1時間雨量（名瀬）")]),
        ("古仁屋 18〜21日の和 = 表-2 連続雨量", sum_jma(jma, K, 0), V(T_K38, "瀬戸内町古仁屋", "連続雨量"), [k(T_K38, "瀬戸内町古仁屋", "連続雨量")]),
        ("古仁屋 20日 = 安達ほか", j20(K, 0), V(T_K6, "20日の日積算雨量（古仁屋）"), [k(T_K6, "20日の日積算雨量（古仁屋）")]),
        ("古仁屋 最大1時間 = 表-2", j20(K, 1), V(T_K38, "瀬戸内町古仁屋", "時間雨量"), [k(T_K38, "瀬戸内町古仁屋", "時間雨量")]),
        ("古仁屋 最大1時間 = 地頭薗ほか", j20(K, 1), V(T_K16, "最大1時間雨量（古仁屋）"), [k(T_K16, "最大1時間雨量（古仁屋）")]),
    ]
    # (4) 出典間の突き合わせ（一致するもの）
    pairs += [
        ("住用 最大1時間 京大 = 鹿大表-2", V(T_RAIN, "最大1時間雨量（住用）"), V(T_K38, "奄美市住用町", "時間雨量"),
         [k(T_RAIN, "最大1時間雨量（住用）"), k(T_K38, "奄美市住用町", "時間雨量")]),
        ("住用 最大1時間 京大 = 鹿大序文", V(T_RAIN, "最大1時間雨量（住用）"), V(T_K2, "最大1時間雨量（住用町）"),
         [k(T_K2, "最大1時間雨量（住用町）")]),
        ("住用 24時間 京大 = 鹿大表-2 日雨量", V(T_RAIN, "24時間雨量（住用）"), V(T_K38, "奄美市住用町", "日雨量"),
         [k(T_RAIN, "24時間雨量（住用）"), k(T_K38, "奄美市住用町", "日雨量")]),
        ("名瀬 24時間 京大 = 鹿大表-2 日雨量", V(T_RAIN, "24時間雨量（名瀬）"), V(T_K38, "奄美市名瀬", "日雨量"),
         [k(T_RAIN, "24時間雨量（名瀬）"), k(T_K38, "奄美市名瀬", "日雨量")]),
        ("名瀬 24時間 京大 = 地頭薗ほか", V(T_RAIN, "24時間雨量（名瀬）"), V(T_K16, "24時間雨量（名瀬）"), [k(T_K16, "24時間雨量（名瀬）")]),
        ("死者 京大 = p17 合計", V(T_DMG, "死者"), V(T_K17, "死者", TOTAL_COL), [k(T_DMG, "死者")]),
        ("死者 安達ほか 2+1 = p17 合計", V(T_K6, "浸水による死者") + V(T_K6, "崖崩れによる死者"), V(T_K17, "死者", TOTAL_COL),
         [k(T_K6, "浸水による死者"), k(T_K6, "崖崩れによる死者")]),
    ]
    # 丸めの範囲で一致（京大の整数。気象庁・鹿大は .5）
    for label, a, b, cell in [("名瀬 最大1時間 京大78 ≈ 78.5", V(T_RAIN, "最大1時間雨量（名瀬）"), V(T_K38, "奄美市名瀬", "時間雨量"),
                               k(T_RAIN, "最大1時間雨量（名瀬）")),
                              ("名瀬 総雨量 京大766 ≈ 766.5", V(T_RAIN, "総雨量（名瀬）"), V(T_K38, "奄美市名瀬", "連続雨量"),
                               k(T_RAIN, "総雨量（名瀬）"))]:
        pairs.append((label, a, a if abs(a - b) < 1 else b, [cell]))

    # (5) 宣言する差
    flood_u, flood_d = V(T_K17, "床上浸水", TOTAL_COL), V(T_K17, "床下浸水", TOTAL_COL)
    declared_in = {
        "住用の総雨量 京大/鹿大序文": (V(T_RAIN, "総雨量（住用）"), V(T_K2, "総雨量（住用町）")),
        "住用の総雨量 京大/鹿大表-2": (V(T_RAIN, "総雨量（住用）"), V(T_K38, "奄美市住用町", "連続雨量")),
        "住用の総雨量 鹿大序文/鹿大表-2": (V(T_K2, "総雨量（住用町）"), V(T_K38, "奄美市住用町", "連続雨量")),
        "全壊・半壊 京大/県11-26": (V(T_DMG, "全壊・半壊の住家"), wreck),
        "全壊・半壊 京大/安達ほか": (V(T_DMG, "全壊・半壊の住家"), V(T_K6, "全半壊の建物")),
        "全壊・半壊 県11-26/安達ほか": (wreck, V(T_K6, "全半壊の建物")),
        "床上浸水 京大/県11-26": (V(T_FLOOD, "床上浸水"), flood_u),
        "床上浸水 京大/安達ほか": (V(T_FLOOD, "床上浸水"), V(T_K6, "床上浸水")),
        "床上浸水 県11-26/安達ほか": (flood_u, V(T_K6, "床上浸水")),
        "床下浸水 京大/県11-26": (V(T_FLOOD, "床下浸水"), flood_d),
        "床下浸水 京大/安達ほか": (V(T_FLOOD, "床下浸水"), V(T_K6, "床下浸水")),
        "床下浸水 県11-26/安達ほか": (flood_d, V(T_K6, "床下浸水")),
    }
    observed = {label: (a, b) for label, a, b, _ in pairs}
    observed.update(declared_in)
    actual = doccells.check_identity("気象庁・出典間の突き合わせ", observed, DECLARED_DIFFS)
    for label, _a, _b, cells in pairs:
        if label not in actual:
            backed.update(cells)
    return backed, actual


# ------------------------------------------------------------------ PDF の検査（任意）
def _squash(s):
    return "".join((s or "").split())


def verify_pdfs(spec, root=ROOT):
    """本文の数値の文が PDF に現れること、p38 の表-2 が SPEC と一致することを検査する。
    -> (p38 のセル bbox {(行, 列): [x0, y0, x1, y1]}, 警告のリスト)。PDF・pdfplumber が無ければ ({}, [警告])。"""
    paths = {d: root / RAW_DIR / DOCS[d]["file"] for d in DOCS}
    missing = [p.name for p in paths.values() if not p.exists()]
    if missing:
        return {}, [f"PDF が無い（{', '.join(missing)}）ので本文・表-2 の検査を飛ばした"]
    try:
        import pdfplumber
    except ImportError:
        return {}, ["pdfplumber が無いので本文・表-2 の検査を飛ばした"]
    bbox = {}
    for doc, path in paths.items():
        with pdfplumber.open(str(path)) as pdf:
            need = {}
            for c in spec:
                if c["doc"] == doc and c["needle"]:
                    need.setdefault(c["page_no"], set()).add(c["needle"])
            for page, needles in need.items():
                text = _squash(pdf.pages[page - 1].extract_text())
                for n in sorted(needles):
                    if _squash(n) not in text:
                        raise ValueError(f"{doc} p{page}: 本文に現れない断片 {n!r}")
            if doc == KAGO:
                tables = pdf.pages[P38_PAGE - 1].find_tables()
                if len(tables) != 1:
                    raise ValueError(f"p{P38_PAGE}: 表が1つでない（{len(tables)}）")
                t = tables[0]
                body = t.extract()[1:]
                want = [[place, *vals] for place, vals in P38_ROWS]
                if [[_squash(x) for x in r] for r in body] != want:
                    raise ValueError(f"p{P38_PAGE} の表-2 が SPEC と違う: {body}")
                for i, (place, _) in enumerate(P38_ROWS):
                    for j, (ck, _u) in enumerate(P38_COLS):
                        x0, y0, x1, y1 = t.rows[i + 1].cells[j + 1]
                        bbox[(place, ck)] = [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)]
    return bbox, []


# ------------------------------------------------------------------ 組み立て
def to_rows(spec, backed, bbox, sha_by_doc):
    out = {d: [] for d in DOCS}
    now = datetime.datetime.now().isoformat(timespec="seconds")
    for c in spec:
        vision = c["table_id"] in VISION_TABLES
        if vision:
            extractor, by, conf = "manual:vision", "claude(vision)", 0.9
        else:
            extractor = "manual:pdftext"
            ok = (c["table_id"], c["row_key"], c["col_key"]) in backed
            by, conf = ("auto:xtext+arith", 1.0) if ok else ("claude(text)", 0.9)
        raw = c["value_raw"]
        row = dict(page_no=c["page_no"], table_id=c["table_id"], row_key=c["row_key"], col_key=c["col_key"],
                   unit=c["unit"], fiscal_year=None, era_raw=era_for(c["table_id"], c["row_key"], c["col_key"]),
                   source_text=c["source_text"], source_bbox=json.dumps(bbox[(c["row_key"], c["col_key"])])
                   if c["table_id"] == T_K38 and (c["row_key"], c["col_key"]) in bbox else None,
                   notes_ref=None, is_total=c["is_total"], merged=0, extractor=extractor, extracted_at=now,
                   doc_sha256=sha_by_doc.get(c["doc"]), unreadable_reason=None, confidence=conf, verified_by=by)
        if raw is None:
            row.update(value_raw=None, value=None, value_type=None)
        else:
            v = num(raw)
            is_float = "." in raw
            row.update(value_raw=raw, value=str(float(v)) if is_float else str(int(v)), value_type="float" if is_float else "int")
        out[c["doc"]].append(row)
    return out


def notes():
    """doc_id -> notes（事実だけ。blocks_timeseries は 0）。"""
    return {
        DPRI: [
            dict(kind="survey_scope", table_ids=[T_RAIN, T_DMG, T_FLOOD], page=1, blocks_timeseries=0, text=(
                "自然災害研究協議会災害調査団が 2010年12月と2011年1月に行った現地調査の速報（2011-02-21）。雨量は本文の記述、"
                "被害（死者・住家・河川・浸水）も本文の記述で、表ではない。浸水と河川の数は鹿児島県大島支庁（2010）の引用。")),
            dict(kind="footnote", table_ids=[T_RAIN], page=1, blocks_timeseries=0, text=(
                "総雨量は名瀬766・住用894 mm。鹿大の報告書は住用を891 mm（序文）・893 mm（第5章表-2）としており一致しない。"
                "どちらにも寄せずに載せる。期間は速報に書かれていない（鹿大の表-2 の連続雨量は気象庁の18〜21日の和と一致）。")),
            dict(kind="footnote", table_ids=[T_RAIN], page=1, blocks_timeseries=0, text=(
                "名瀬の最大1時間雨量78は整数に丸めた値（気象庁・鹿大は78.5）。名瀬の総雨量766も丸め（気象庁の18〜21日の和は766.5）。")),
            dict(kind="footnote", table_ids=[T_DMG, T_FLOOD], page=1, blocks_timeseries=0, text=(
                "全壊・半壊485棟、床上浸水576件・床下浸水736件は、鹿大の報告書が引く県の11/26報告（全壊10＋半壊479＝489棟、"
                "床上119・床下767棟）とも、安達ほかの数（全半壊565棟、床上130・床下762棟）とも一致しない。"
                "出典の資料・時点が違い、どれが確定値かは確認できていない。")),
        ],
        KAGO: [
            dict(kind="survey_scope", table_ids=[T_K2, T_K6, T_K16, T_K17, T_K38], page=2, blocks_timeseries=0, text=(
                "報告書は鹿児島大学の教員28名の調査チームによる2年度の調査の成果（2012-03-01）。章ごとに著者が違う。"
                "表と本文の位置（報告書の印刷ページ）: p2_text＝はじめに（-1-）、p6_text＝第1章 安達ほか（p.1）、"
                "p16_text＝第2章 地頭薗ほか（p.11）、p17_t1＝同 表-1（p.12）、p38_t1＝第5章 北村 表-2（p.33）。")),
            dict(kind="footnote", table_ids=[T_K2, T_K38], page=2, blocks_timeseries=0, text=(
                "住用の総雨量は、序文891 mm（住用町）、表-2 の連続雨量893 mm（奄美市住用町）、京大の速報894 mm と3通りある。"
                "龍郷町は序文の881 mm のみ。")),
            dict(kind="definition_change", table_ids=[T_K38, T_K6, T_K16], page=38, blocks_timeseries=0, text=(
                "「日雨量」が2つの意味で使われている。表-2 の日雨量（住用703・名瀬648・古仁屋291.5）は24時間雨量"
                "（京大の24時間雨量703・648と一致、第2章の本文は名瀬648を「20日23時20分までの24時間雨量」とする）。"
                "安達ほか・第2章本文の「20日の（日積算）雨量」（名瀬622・古仁屋286.5）は暦日で、気象庁の名瀬・古仁屋の"
                "10月20日の日降水量と一致する。")),
            dict(kind="footnote", table_ids=[T_K38, T_K6], page=38, blocks_timeseries=0, text=(
                "住用の雨量は鹿児島県の観測所（住用村）の値で、気象庁のアメダスではない（奄美の気象庁の局は名瀬・笠利・古仁屋・"
                "喜界島・天城）。名瀬・古仁屋の値は気象庁の値と一致する（連続雨量は18〜21日の日降水量の和）。")),
            dict(kind="footnote", table_ids=[T_K17], page=17, blocks_timeseries=0, text=(
                "県（鹿児島県危機管理防災課・現地対策合同本部）の2010年11月26日現在の報告。元は画像で、市町村の内訳は括弧書きの"
                "列挙にあるものだけ。載っていない市町村は空欄で、0 とは書かれていない。死者3名は「奄美市住用町わだつみ苑入所者2名、"
                "龍郷町で行方不明捜索中だった1名」、軽傷2名は「龍郷町1名、奄美市1名」。")),
            dict(kind="footnote", table_ids=[T_K6], page=6, blocks_timeseries=0, text=(
                "全半壊565棟・床上130棟・床下762棟は文献3（鹿児島県現地対策合同本部の被害状況、日付なし）の値で、"
                "p17_t1（11/26現在。全壊＋半壊489、床上119、床下767）と一致しない。")),
            dict(kind="footnote", table_ids=[T_K16], page=16, blocks_timeseries=0, text=(
                "土砂災害の被害（死者1・負傷3・全壊6・半壊1・一部損壊5）は県土木部砂防課・大島支庁建設課の報告で、p17 の被害の内数。"
                "被害総額11,568,106千円は土木・農業・環境林務・保健福祉・商工観光・文教などの合計（被害額判明分）。")),
        ],
    }


def build(root=ROOT, spec=None, jma=None, check_pdfs=True, require_pdfs=False):
    """-> dict(docs={doc_id: dict(document, rows, notes)}, stats, warnings)。DB には触れない。
    jma: {(地点, 日付): (合計, 最大1時間)}。None なら load_jma（原本・保存 HTML、無ければ csv）。
    check_pdfs: PDF があれば本文・表-2 を検査する。require_pdfs: PDF が無い・検査できないと止める（書き込みでは必須）。"""
    spec = spec if spec is not None else SPEC
    warnings = []
    if jma is None:
        jma, w = load_jma(root)
        warnings += w
    backed, declared = run_checks(spec, jma)
    bbox, sha = {}, {}
    if check_pdfs:
        bbox, w = verify_pdfs(spec, root)
        warnings += w
        if w and require_pdfs:
            raise SystemExit(w[0] + "（書き込みには必須）")
    for d, meta in DOCS.items():
        p = root / RAW_DIR / meta["file"]
        sha[d] = common.sha256(p) if p.exists() else None
    by_doc = to_rows(spec, backed, bbox, sha)
    ns = notes()
    docs = {}
    for d, meta in DOCS.items():
        docs[d] = dict(document=dict(title=meta["title"], publisher=meta["publisher"], url=meta["url"],
                                     local_path=f"{RAW_DIR}/{meta['file']}", doc_sha256=sha[d], n_pages=meta["n_pages"],
                                     fiscal_year=meta["fiscal_year"], license=LICENSE),
                       rows=by_doc[d], notes=ns[d])
    stats = dict(n_cells=sum(len(v["rows"]) for v in docs.values()), backed=len(backed), declared_diffs=sorted(declared),
                 pdf_checked=check_pdfs and not any("飛ばした" in w for w in warnings))
    return dict(docs=docs, stats=stats, warnings=warnings)


# ------------------------------------------------------------------ DB
def source_args(doc_id):
    meta = DOCS[doc_id]
    if doc_id == DPRI:
        notes_ = f"doc_id={DPRI}（速報の本文の雨量・被害を cells に入れた）。fiscal_year は NULL の単発の事象。PDF は data/raw に置き再配布しない。"
    else:
        notes_ = (f"doc_id={KAGO}（報告書の本文・画像・表-2 の雨量・被害を cells に入れた。2012年。fiscal_year は NULL の単発の事象）。"
                  "p17 は画像を目で読んだもので人の見直しが済んでいない。PDF は data/raw に置き再配布しない。")
    return dict(source_id=meta["source_id"], name=meta["source_name"], publisher=meta["publisher"], url=SOURCE_PAGE[doc_id],
                category="災害(2010年奄美豪雨)", access_method="PDF（本文・画像・表）→ 目視・文字情報＋検算 → cells.sqlite",
                fmt="PDF", license_=LICENSE, redistributable=False, notes=notes_)


def write(built, register=True):
    """2文書を書く（自分の doc_id の行だけを入れ替える）。-> {doc_id: 挿入した cells の行数}"""
    out = {}
    for d, b in built["docs"].items():
        out[d] = doccells.commit_doc(
            d, document=b["document"], cells=b["rows"], notes=b["notes"],
            log=[dict(verdict="pass", page_no=None, table_id=None,
                      failures={"warnings": built["warnings"]} if built["warnings"] else None,
                      note=f"{SCRIPT_ID}: cells {len(b['rows'])} 件、宣言した差 {len(built['stats']['declared_diffs'])} 件、"
                           f"検算で裏付け {built['stats']['backed']} セル（全体）")],
            source=source_args(d) if register else None)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="DB に書かない")
    ap.add_argument("--no-register", action="store_true", help="source_registry に登録しない")
    a = ap.parse_args()
    b = build(require_pdfs=not a.dry_run)
    st = b["stats"]
    print(f"cells {st['n_cells']}（京大 {len(b['docs'][DPRI]['rows'])}・鹿大 {len(b['docs'][KAGO]['rows'])}）、"
          f"検算で裏付けたセル {st['backed']}、宣言した差 {len(st['declared_diffs'])} 件、PDF の検査 {'済' if st['pdf_checked'] else '飛ばした'}")
    for w in b["warnings"]:
        print("  警告:", w)
    if a.dry_run:
        return
    print(write(b, register=not a.no_register))


if __name__ == "__main__":
    main()
