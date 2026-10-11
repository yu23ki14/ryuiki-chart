"""奄美の水道の水源種別（令和5年度水道統計。上水道・簡易水道）とダムの容量（流域治水10頁版）を、行政文書の cells・notes にする。

設計: docs/plans/AMAMI_STEP3C.md §3・§4・§5。**数値という事実だけ**を入れる（原本の PDF は再配布しない）。

流れ:
1. SPEC（表 × 行 × 列の値・印字・単位）から cells の行を作る。
2. 検算（run_checks）: 上水道は 7 種別の和 = 合計、簡易水道は 表流水＋地下水＋その他 = 計、
   大和ダムは 517＋125＝642 と割合3つ（割り算）。食い違いは IdentityError で止める。
3. PDF が手元にあれば（pdfplumber が要る。無ければ警告して飛ばす。書き込みには必須）、sha256・ページ数・表の値・
   見出し・本文の文字列を SPEC と突き合わせ、表のセル座標を source_bbox にする。
4. verified_by: 検算が通り、PDF の検査も済んだセルは `auto:xtext+arith`（1.0）。検算を取れない列（箇所数）と
   大川ダムの本文の値は `claude(text)`（0.9）。

fiscal_year は全セル NULL（1年だけ・一時点の値。DOC_SERIES_WHERE に入れない）。era_raw は PDF に印字のあるものだけ
（水道は「令和６年３月」＝刷り込みの時点。ダムは無し）。
使い方: python3 scripts/c104b_amami_water_dam_cells.py [--dry-run] [--no-register]
"""
import argparse
import json
import pathlib
import re
import sys
import unicodedata
from decimal import ROUND_HALF_UP, Decimal

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import c104a_amami_water_dam_fetch as fetch
import common
import doccells

ROOT = common.ROOT
SCRIPT_ID = "c104b_amami_water_dam_cells"

JORYO, KANI, DAM = "kagoshima_suido_r5_joryo", "kagoshima_suido_r5_kani", "kagoshima_amami_ryuiki_chisui_10p_2023"
T_X1, T_X2, T_P5, T_P6 = "x1", "x2", "p5_t1", "p6_text"
ERA_SUIDO = "令和６年３月"   # PDF の刷り込み（データの年度ではない）

F_JORYO, F_KANI, F_DAM = "121966_20250627104846-1.pdf", "121966_20250627105147-1.pdf", "88914_20230208131603-1.pdf"
DOCS = {
    JORYO: dict(title="令和5年度水道統計調査 （2）年間取水量，浄水量，給水量（上水道）", publisher="鹿児島県", file=F_JORYO,
                n_pages=1, page=1, source_id="kagoshima_suido_amami", era=ERA_SUIDO,
                needles=["（2）年間取水量，浄水量，給水量（上水道）", ERA_SUIDO]),
    KANI: dict(title="令和5年度水道統計調査 （1）実績，原水種別，浄水方法（簡易水道）", publisher="鹿児島県", file=F_KANI,
               n_pages=1, page=1, source_id="kagoshima_suido_amami", era=ERA_SUIDO,
               needles=["（1）実績，原水種別，浄水方法（簡易水道）", ERA_SUIDO]),
    DAM: dict(title="奄美大島地域流域治水プロジェクト（10頁版）", publisher="鹿児島県", file=F_DAM, n_pages=10, page=None,
              source_id="kagoshima_dam_capacity_amami", era=None, needles=[]),
}
for _m in DOCS.values():   # 保存先・取得先 URL・期待する sha256 は c104a の FILES が正
    _d, _m["url"], _m["sha256"] = fetch.FILES[_m["file"]]
    _m["path"] = _d / _m["file"]
    _m["local_path"] = str(_m["path"].relative_to(ROOT))

SOURCES = {
    "kagoshima_suido_amami": dict(
        name="鹿児島県 令和5年度水道統計調査（上水道・簡易水道の取水の種別）", url="https://www.pref.kagoshima.jp/ae09/suidou/suidoutoukei/r5toukei.html",
        category="水道", notes=f"doc_id={JORYO}（上水道。千m3）・{KANI}（簡易水道。m3）。奄美の市町村の行だけを cells に入れた。"
        "fiscal_year は NULL（1年だけ）。PDF は data/raw に置き再配布しない。", docs=[JORYO, KANI]),
    "kagoshima_dam_capacity_amami": dict(
        name="鹿児島県 大和・大川ダムの有効貯水容量（奄美大島地域流域治水プロジェクト10頁版）", url=DOCS[DAM]["url"],
        category="ダム", notes=f"doc_id={DAM}（p5 大和ダムの表、p6 大川ダムの図中の文字）。PDF は data/raw に置き再配布しない。", docs=[DAM]),
}

# ---------------------------------------------------------------- SPEC
JORYO_COLS = ["ダム", "湖水", "自流", "伏流水", "浅井戸", "深井戸", "湧水"]
JORYO_ROWS = {   # 市町村 -> 7 種別 + 合計（千m3/年）
    "奄美市": [932, 0, 3291, 0, 126, 1483, 0, 5832],
    "瀬戸内町": [0, 0, 1403, 0, 0, 1, 0, 1404],
    "龍郷町": [0, 0, 714, 0, 0, 515, 0, 1229],
}
KANI_ROWS = {   # 市町村 -> (簡易水道の箇所数, 表流水箇所, 表流水量, 地下水箇所, 地下水量, その他箇所, その他量, 計)
    "大和村": [1, 8, 152442, 0, 0, 0, 0, 152442],
    "宇検村": [1, 1, 337260, 0, 0, 0, 0, 337260],
    "瀬戸内町": [10, 16, 108627, 3, 32250, 0, 0, 140877],
}
KANI_COLS = [("簡易水道の箇所数", "箇所", 0), ("表流水（取水箇所）", "箇所", 0), ("表流水（取水量）", "m3", 0),
             ("地下水（取水箇所）", "箇所", 0), ("地下水（取水量）", "m3", 0), ("その他（取水箇所）", "箇所", 0),
             ("その他（取水量）", "m3", 0), ("計（取水量）", "m3", 1)]
KANI_AMOUNT_COLS = ["表流水（取水量）", "地下水（取水量）", "その他（取水量）"]
KANI_TOTAL = "計（取水量）"

PCT = "有効貯水容量に対する割合"
DAM_ROWS = [   # (表, 頁, 行, 列, 印字, 単位)
    (T_P5, 5, "大和ダム", "有効貯水容量", "721", "千m3"),
    (T_P5, 5, "大和ダム", "洪水調節容量", "517", "千m3"),
    (T_P5, 5, "大和ダム", "洪水調節容量の" + PCT, "71.7", "%"),
    (T_P5, 5, "大和ダム", "洪水調節可能容量", "125", "千m3"),
    (T_P5, 5, "大和ダム", "洪水調節可能容量の" + PCT, "17.3", "%"),
    (T_P5, 5, "大和ダム", "水害対策に使える容量", "642", "千m3"),
    (T_P5, 5, "大和ダム", "水害対策に使える容量の" + PCT, "89.0", "%"),
    (T_P6, 6, "大川ダム", "有効貯水量", "2,180", "千m3"),
    (T_P6, 6, "大川ダム", "うち洪水調節可能容量", "106", "千m3"),
]


def cell_row(doc, table, page, row_key, col_key, raw, unit, source_text, is_total=0):
    return dict(doc=doc, table_id=table, page_no=page, row_key=row_key, col_key=col_key, value_raw=raw, unit=unit,
                source_text=source_text, is_total=is_total)


def fmt(v):
    return f"{v:,}"


def make_spec():
    spec = []
    for muni, vals in JORYO_ROWS.items():
        line = f"{muni} " + " ".join(fmt(v) for v in vals)
        for i, v in enumerate(vals):
            last = i == len(vals) - 1
            spec.append(cell_row(JORYO, T_X1, 1, muni, "合計" if last else JORYO_COLS[i], fmt(v), "千m3", line, int(last)))
    for muni, vals in KANI_ROWS.items():
        line = f"{muni} " + " ".join(fmt(v) for v in vals)
        for (ck, unit, tot), v in zip(KANI_COLS, vals):
            spec.append(cell_row(KANI, T_X2, 1, muni, ck, fmt(v), unit, line, tot))
    for table, page, rk, ck, raw, unit in DAM_ROWS:
        spec.append(cell_row(DAM, table, page, rk, ck, raw, unit, f"{rk} {ck} {raw}{unit}"))
    return spec


SPEC = make_spec()


def _key(c):
    return (c["doc"], c["table_id"], c["row_key"], c["col_key"])


# ---------------------------------------------------------------- 検算
def _int(raw):
    if not re.fullmatch(r"\d{1,3}(,\d{3})*|\d+", raw or ""):
        raise ValueError(f"値の形が不正: {raw!r}")
    if "," in raw and raw != fmt(int(raw.replace(",", ""))):
        raise ValueError(f"値の形が不正（カンマ）: {raw!r}")
    return int(raw.replace(",", ""))


def _pct_of(part, whole):
    return (Decimal(part) / Decimal(whole) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def run_checks(spec):
    """行内の和 = 合計、ダムの足し算と割り算を検算する。通らなければ IdentityError。-> 検算で裏付けたセルの key の集合"""
    by = {_key(c): c for c in spec}
    backed = set()

    def val(doc, t, r, k):
        return _int(by[(doc, t, r, k)]["value_raw"])

    obs = {}
    for muni in JORYO_ROWS:
        obs[muni] = (sum(val(JORYO, T_X1, muni, k) for k in JORYO_COLS), val(JORYO, T_X1, muni, "合計"))
        backed |= {(JORYO, T_X1, muni, k) for k in [*JORYO_COLS, "合計"]}
    doccells.check_identity("上水道 種別の和 = 合計", obs)
    obs = {}
    for muni in KANI_ROWS:
        obs[muni] = (sum(val(KANI, T_X2, muni, k) for k in KANI_AMOUNT_COLS), val(KANI, T_X2, muni, KANI_TOTAL))
        backed |= {(KANI, T_X2, muni, k) for k in [*KANI_AMOUNT_COLS, KANI_TOTAL]}
        for k in ("簡易水道の箇所数", "表流水（取水箇所）", "地下水（取水箇所）", "その他（取水箇所）"):
            _int(by[(KANI, T_X2, muni, k)]["value_raw"])   # 値の形だけ
    doccells.check_identity("簡易水道 取水量の和 = 計", obs)

    def d(k):
        return val(DAM, T_P5, "大和ダム", k)

    def dp(k):
        return Decimal(by[(DAM, T_P5, "大和ダム", k)]["value_raw"])

    parts = ("洪水調節容量", "洪水調節可能容量", "水害対策に使える容量")
    obs = {"洪水調節＋可能＝使える": (d(parts[0]) + d(parts[1]), d(parts[2]))}
    for part in parts:
        obs[f"割合 {part}"] = (_pct_of(d(part), d("有効貯水容量")), dp(f"{part}の{PCT}"))
    doccells.check_identity("大和ダム 容量", obs)
    backed |= {(DAM, T_P5, "大和ダム", k) for k in ("有効貯水容量", *parts, *(f"{p}の{PCT}" for p in parts))}
    for k in ("有効貯水量", "うち洪水調節可能容量"):
        _int(by[(DAM, T_P6, "大川ダム", k)]["value_raw"])
    return backed


# ---------------------------------------------------------------- PDF の検査（任意）
JORYO_PDF_COLS = [(k, i + 1) for i, k in enumerate([*JORYO_COLS, "合計"])]       # (col_key, 表の列番号)
KANI_PDF_COLS = [(ck, j) for (ck, _u, _t), j in zip(KANI_COLS, [1, 8, 9, 10, 11, 12, 13, 14])]


def _squash(s):
    return "".join((s or "").split())


def _best_table(tables, pred):
    for t in tables:
        rows = t.extract()
        if any(pred(r) for r in rows):
            return t, rows
    raise ValueError("期待する表が見つからない")


def _find_row(rows, pred, label):
    """pred を満たす行がちょうど1つであることを確かめて、その行番号を返す（0個・2個以上は ValueError）。"""
    idx = [i for i, r in enumerate(rows) if r and pred(r[0])]
    if len(idx) != 1:
        raise ValueError(f"{label}: 行が{len(idx)}個（1個のはず）")
    return idx[0]


def _cell_text(cell, where):
    """表のセルの数値の印字（カンマ付き）。None・空・'-'・数字でないものは、文書・行の文脈つきの ValueError。"""
    if cell is None or not re.fullmatch(r"\d{1,3}(,\d{3})*|\d+", cell.strip()):
        raise ValueError(f"{where}: 表が SPEC と違う（数値として読めない {cell!r}）")
    return cell.strip()


def _bbox(t, i, j):
    try:
        cell = t.rows[i].cells[j]
    except IndexError:
        return None
    return [round(x, 1) for x in cell] if cell else None


def _shas(root=ROOT):
    return {d: common.sha256(root / m["local_path"]) if (root / m["local_path"]).exists() else None for d, m in DOCS.items()}


def _check_text(doc, text, needles):
    for n in needles:
        if _squash(n) not in text:
            raise ValueError(f"{doc}: 本文に現れない断片 {n!r}")


def _verify_rows(doc, table_id, t, rows, row_keys, colmap, by, bbox):
    """行ごとに、表の値が SPEC の value_raw と一致すること、行が一意なことを検査し、セル座標を bbox に入れる。"""
    for rk in row_keys:
        i = _find_row(rows, lambda c0, rk=rk: c0 == rk, f"{doc} {rk}")
        want = [by[(doc, table_id, rk, ck)]["value_raw"] for ck, _ in colmap]
        got = [_cell_text(rows[i][j], f"{doc} {rk}") for _, j in colmap]
        if got != want:
            raise ValueError(f"{doc} {rk}: 表が SPEC と違う: {got}")
        for ck, j in colmap:
            bbox[(doc, table_id, rk, ck)] = _bbox(t, i, j)


def _verify_joryo(pdf, by, bbox):
    page = pdf.pages[0]
    text = _squash(page.extract_text())
    _check_text(JORYO, text, DOCS[JORYO]["needles"])
    if _squash("ダム湖水自流伏流水浅井戸深井戸") not in text:
        raise ValueError(f"{JORYO}: 見出し（種別の並び）が違う")
    t, rows = _best_table(page.find_tables(), lambda r: r[0] == "奄美市")
    _verify_rows(JORYO, T_X1, t, rows, JORYO_ROWS, JORYO_PDF_COLS, by, bbox)


def _verify_kani(pdf, by, bbox):
    page = pdf.pages[0]
    _check_text(KANI, _squash(page.extract_text()), DOCS[KANI]["needles"])
    t, rows = _best_table(page.find_tables(), lambda r: r[0] == "大和村")
    hdr = rows[1]
    if [hdr[8], hdr[10], hdr[12], hdr[14]] != ["表流水", "地下水", "その他", "計"]:
        raise ValueError(f"{KANI}: 見出しが違う: {hdr}")
    _verify_rows(KANI, T_X2, t, rows, KANI_ROWS, KANI_PDF_COLS, by, bbox)


def _verify_dam(pdf, by, bbox):
    dam_cols = [(r[3], r[4]) for r in DAM_ROWS if r[2] == "大和ダム"]   # (col_key, 印字)
    want = [by[(DAM, T_P5, "大和ダム", ck)]["value_raw"] for ck, _ in dam_cols]
    page5 = pdf.pages[4]
    squashed = _squash(page5.extract_text())
    if "大和ダム" + "".join(w + ("%" if "." in w else "") for w in want) not in squashed:
        raise ValueError("p5: 本文に大和ダムの行が現れない")
    # 表: 先頭の「大」が欠ける（'和ダム'）ことがあるので 2文字目以降で見る
    exp = [w + ("%" if "." in w else "") for w in want]
    is_row = lambda c0: c0 in ("和ダム", "大和ダム")   # noqa: E731
    t, rows = _best_table(page5.find_tables(), lambda r: is_row(r[0]))
    i = _find_row(rows, is_row, "p5 大和ダム")
    if rows[i][1:] != exp:
        raise ValueError(f"p5 大和ダム: 表が SPEC と違う: {rows[i][1:]}")
    for j, (ck, _) in enumerate(dam_cols, 1):
        bbox[(DAM, T_P5, "大和ダム", ck)] = _bbox(t, i, j)
    text6 = _squash(unicodedata.normalize("NFKC", pdf.pages[5].extract_text() or ""))
    if "大川ダム" not in text6:
        raise ValueError("p6: 大川ダムが現れない")
    for ck in ("有効貯水量", "うち洪水調節可能容量"):
        needle = f"V={by[(DAM, T_P6, '大川ダム', ck)]['value_raw']}千m3"   # NFKC・空白除去後の本文
        if needle not in text6:
            raise ValueError(f"p6: 本文に現れない断片 {needle!r}")


_VERIFY = {JORYO: _verify_joryo, KANI: _verify_kani, DAM: _verify_dam}


def verify_pdfs(spec, root=ROOT, sha=None):
    """sha256・ページ数・表の値・見出し・本文の文字列を検査する。-> (bbox {key: [x0,y0,x1,y1]}, 警告, checked)。
    PDF・pdfplumber が無ければ ({}, [警告], False)。PDF があって sha256 が c104a の FILES と違えば止める。
    sha: _shas(root) の結果（渡せば二重に計算しない）。"""
    sha = sha if sha is not None else _shas(root)
    missing = [DOCS[d]["file"] for d, s in sha.items() if s is None]
    if missing:
        return {}, [f"PDF が無い（{', '.join(missing)}）ので表・本文の検査を飛ばした"], False
    for d, s in sha.items():
        if s != DOCS[d]["sha256"]:
            raise SystemExit(f"{DOCS[d]['file']}: sha256 が c104a_amami_water_dam_fetch.FILES と違う。資料が更新された？ 人が確認する")
    try:
        import pdfplumber
    except ImportError:
        return {}, ["pdfplumber が無いので表・本文の検査を飛ばした"], False
    by = {_key(c): c for c in spec}
    bbox = {}
    for doc, m in DOCS.items():
        with pdfplumber.open(str(root / m["local_path"])) as pdf:
            if len(pdf.pages) != m["n_pages"]:
                raise ValueError(f"{doc}: ページ数が {len(pdf.pages)}（DOCS は {m['n_pages']}）")
            _VERIFY[doc](pdf, by, bbox)
    return {k: v for k, v in bbox.items() if v}, [], True



# ---------------------------------------------------------------- 組み立て
def to_rows(spec, backed, bbox, checked, sha_by_doc):
    out = {d: [] for d in DOCS}
    for c in spec:
        k = _key(c)
        if c["table_id"] == T_P6:
            extractor, by, conf = "manual:pdftext", "claude(text)", 0.9
        else:
            extractor = "pdfplumber"
            by, conf = ("auto:xtext+arith", 1.0) if (checked and k in backed) else ("claude(text)", 0.9)
        box = bbox.get(k)
        row = dict(page_no=c["page_no"], table_id=c["table_id"], row_key=c["row_key"], col_key=c["col_key"],
                   unit=c["unit"], fiscal_year=None, era_raw=DOCS[c["doc"]]["era"],
                   source_text=c["source_text"], source_bbox=json.dumps(box) if box else None, notes_ref=None,
                   is_total=c["is_total"], merged=0, extractor=extractor, doc_sha256=sha_by_doc.get(c["doc"]),
                   unreadable_reason=None, confidence=conf, verified_by=by, value_raw=c["value_raw"])
        row["value"], row["value_type"] = doccells.number_value(c["value_raw"])
        out[c["doc"]].append(row)
    return out


def notes():
    """doc_id -> notes（事実だけ。blocks_timeseries は 0）。"""
    return {
        JORYO: [
            dict(kind="survey_scope", table_ids=[T_X1], page=1, blocks_timeseries=0, text=(
                "鹿児島県の令和5年度水道統計調査（刷り込みは「令和６年３月」）の上水道の表。年間取水量は千m3。奄美の上水道は奄美市・瀬戸内町・"
                "龍郷町の3つで、大和村・宇検村は簡易水道のみ（上水道の行が無い）。奄美市・龍郷町は簡易水道の行が無い。"
                "瀬戸内町は上水道と簡易水道の両方に行があるが別の水道で、足し合わせていない。")),
            dict(kind="definition_change", table_ids=[T_X1, T_X2], page=1, blocks_timeseries=0, text=(
                "水源の種別の分類が上水道と簡易水道で違う。上水道はダム・湖水・自流・伏流水・浅井戸・深井戸・湧水（単位 千m3）、"
                "簡易水道は表流水・地下水・その他の取水箇所数と取水量（単位 m3）。種別どうしを対応づけていない。")),
        ],
        KANI: [
            dict(kind="survey_scope", table_ids=[T_X2], page=1, blocks_timeseries=0, text=(
                "鹿児島県の令和5年度水道統計調査（刷り込みは「令和６年３月」）の簡易水道の表。奄美は大和村・宇検村・瀬戸内町の3つ。"
                "「簡易水道の箇所数」は水道の数、「取水箇所」は種別ごとの取水の箇所数で、一致しない（大和村は水道1、表流水の取水8箇所）。"
                "取水量の単位は m3。")),
            dict(kind="footnote", table_ids=[T_X2], page=1, blocks_timeseries=0, text=(
                "宇検村の取水量 337,260 m3 は同じ行の実績年間給水量 225,524 m3 より多い（浄水量 337,000 とは合う）。"
                "原表の印字のまま入れ、値は直していない。")),
            dict(kind="footnote", table_ids=[T_X2], page=1, blocks_timeseries=0, text=(
                "表流水・地下水・その他の取水量の和が計に一致することを検算した（3行とも）。箇所数は検算できないので確信度を下げてある。")),
        ],
        DAM: [
            dict(kind="survey_scope", table_ids=[T_P5, T_P6], page=5, blocks_timeseries=0, text=(
                "鹿児島県の「奄美大島地域流域治水プロジェクト」の10頁版（ファイル名の日付は 2023-02-08。PDF に基準日の記載は無い）。"
                "BODIK に載っている同じ題名の4頁版には容量が無い。大和ダムは p5 の表（有効貯水容量・洪水調節容量・洪水調節可能容量・水害対策に使える容量と"
                "割合）、大川ダムは p6 の図中の文字（全角）から読んだ。")),
            dict(kind="footnote", table_ids=[T_P5, T_P6], page=6, blocks_timeseries=0, text=(
                "大川ダムは利水ダムで、管理者は奄美市、所有者・河川管理者は鹿児島県。令和2年度に台風10号で事前放流を実施した"
                "（大川は9月3日〜5日、大和ダムは9月4日〜5日）。大和ダムの「水害対策に使える容量」の割合は治水協定の締結前71.7%、締結後89.0%。")),
        ],
    }


def build(root=ROOT, spec=None, check_pdfs=True, require_pdfs=False):
    """-> dict(docs={doc_id: dict(document, rows, notes)}, stats, warnings)。DB には触れない。"""
    spec = spec if spec is not None else SPEC
    backed = run_checks(spec)
    sha = _shas(root)
    bbox, warnings, checked = {}, [], False
    if check_pdfs:
        bbox, warnings, checked = verify_pdfs(spec, root, sha)
        if not checked and require_pdfs:
            raise SystemExit(warnings[0] + "（書き込みには必須）")
    by_doc = to_rows(spec, backed, bbox, checked, sha)
    ns = notes()
    docs = {d: dict(document=dict(title=m["title"], publisher=m["publisher"], url=m["url"], local_path=m["local_path"],
                                  doc_sha256=sha[d], n_pages=m["n_pages"], fiscal_year=None, license=doccells.LICENSE_PREF_KAGOSHIMA),
                    rows=by_doc[d], notes=ns[d]) for d, m in DOCS.items()}
    return dict(docs=docs, stats=dict(n_cells=sum(len(v["rows"]) for v in docs.values()), backed=len(backed), pdf_checked=checked),
                warnings=warnings)


# ---------------------------------------------------------------- DB
def write(built, register=True):
    """3文書を書く（自分の doc_id の行だけを入れ替える）。出典は文書ごとの合計ではなく出典単位の件数で登録。"""
    out = {}
    for d, b in built["docs"].items():
        out[d] = doccells.commit_doc(
            d, document=b["document"], cells=b["rows"], notes=b["notes"],
            log=[dict(verdict="pass", note=f"{SCRIPT_ID}: cells {len(b['rows'])} 件、検算で裏付け {sum(r['verified_by'] == 'auto:xtext+arith' for r in b['rows'])} セル",
                      failures={"warnings": built["warnings"]} if built["warnings"] else None)])
    if register:
        for sid, s in SOURCES.items():
            common.register(source_id=sid, name=s["name"], publisher="鹿児島県", url=s["url"], category=s["category"],
                            access_method="PDF（表・図中の文字）→ 文字情報＋検算 → cells.sqlite", fmt="PDF",
                            license_=doccells.LICENSE_PREF_KAGOSHIMA, redistributable=False,
                            record_count=sum(out[d] for d in s["docs"]), notes=s["notes"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="DB に書かない（PDF が無ければ検査なしで進む）")
    ap.add_argument("--no-register", action="store_true", help="source_registry に登録しない")
    a = ap.parse_args()
    b = build(require_pdfs=not a.dry_run)
    st = b["stats"]
    print(f"cells {st['n_cells']}（" + "・".join(f"{d} {len(x['rows'])}" for d, x in b["docs"].items()) +
          f"）、検算で裏付けたセル {st['backed']}、PDF の検査 {'済' if st['pdf_checked'] else '飛ばした'}")
    for w in b["warnings"]:
        print("  警告:", w)
    if a.dry_run:
        return
    print(write(b, register=not a.no_register))


if __name__ == "__main__":
    main()
