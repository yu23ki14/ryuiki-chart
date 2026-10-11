"""ハブ統計（咬傷者・買上）の OCR 結果の JSON から、行政文書の cells を作る。**OCR のライブラリは使わない**（JSON だけ読む。
CI の pytest が JSON のフィクスチャから回す）。OCR 本体は c98_habu_ocr_run.py（別の venv）。

設計: docs/plans/AMAMI_STEP2C.md §3d。

流れ（1資料ごと。2つの OCR を並べて、一致したセルだけを検算つきで採用する）:
1. JSON の文字を、c98 が画像の罫線から取った格子（行帯・列帯）に割り当てる（中心点で判定。1セルの文字は x 順につなぐ）。
2. 文字を正規化（NFKC・空白とカンマを除く）。**整数の列の「.」は桁区切りカンマの誤読として除く**。書式を検査する
   （整数の列は `12` か `5(1)`、構成比は `12.9%`、空欄は可）。
3. 2つの OCR が一致し書式も正しいセルだけを「確定」にする。食い違い・書式不正は「未確定」。
4. data/ocr/habu/<doc_id>/reviewed.csv（人の確認）を未確定のセルに当てる。
5. 検算: 行の和＝合計（3月末）、市町村の和＝保健所の計、2つの計の和＝保健所計・合計、買上は全体計＝保健所計＋業者計、
   構成比＝合計（3月末）÷全体計。死亡数（括弧の中）も同じ形で検算する。空欄は 0 として足す。
   失敗した検算に対し、「そのセルが入る検算がすべて失敗」するセルを疑い、最小の組（貪欲法）に絞る。絞れなければ
   その検算の全セルを疑う。疑われたセルは確定を取り消す。
6. 未確定・疑われたセルは `unreadable_reason="ocr_disagree: …"`、`value_raw=NULL` で入れ、**採用しない**（推測しない）。
   0 と空欄の区別がつかない（一方が空欄、他方が 0）セルも同じ扱い。
7. verified_by: 一致＋検算が通った = `auto:xocr+arith`（confidence 1.0）／人の確認 = `human:<名前>`（1.0。reviewer は
   `human:` で始まる名前だけが人。claude・gpt・gemini で始まる AI の名前はそのまま書き confidence 0.9。それ以外は止める）／
   一致したが検算で確かめられない（入る検算が1つも評価できない）= `auto:xocr`（0.8）／未採用 = NULL。
   人・AI の確認した値が検算に合わないときも未採用にする。
   2つの JSON の格子の大きさ・pdf_sha256 の一致、ローカルに PDF があればその sha との一致を確かめ、違えば止める。
   データ領域で列を決められない（どの列にも入らない・2列にまたがる）OCR の箱があれば、近いセルを未採用にして警告する。
cells の形は §3d: row_key `名瀬保健所|奄美市名瀬`、計の行と「合計（3月末）」の列は is_total=1、構成比は float・%・
fiscal_year=NULL、「5(1)」は value=5 のセルと、`…（うち死亡）` という別の行のセル（value=1。括弧のあるセルが1つでもある行は、
値の読めた年・合計の列を全部出し、括弧の無い所は 0。読めない所は NULL）、空欄は value=NULL。

使い方: python3 scripts/c98b_habu_cells.py [--doc bite|kaiage] [--dry-run]
reviewed.csv の列: row（row_key）, col（col_key: H28〜R7・合計(3月末)・構成比）, value（原表の表記。空欄は空）, reviewer, note
"""
import argparse
import csv
import datetime
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import common
import doccells
from ocr import cellmatch
from ocr.cellmatch import (CONF_AI, CONF_AUTO, CONF_HUMAN, CONF_XOCR, ENGINES, KNOWN_AI, norm,   # noqa: F401（テストが c.xxx で参照）
                           verified_by_for)

ROOT = common.ROOT
OCR_DIR = ROOT / "data/ocr/habu"
YEAR_LABELS = ["H28", "H29", "H30", "R1", "R2", "R3", "R4", "R5", "R6", "R7"]
COL_TOTAL, COL_RATIO = "合計(3月末)", "構成比"
COL_KEYS = YEAR_LABELS + [COL_TOTAL, COL_RATIO]
NY = len(YEAR_LABELS)          # 年度の列数。列 NY が合計（3月末）、NY+1 が構成比
UNIT_PCT = "%"
SCRIPT_ID = "c98b_habu_cells"
SOURCE_ID = "kagoshima_habu_amami"
LICENSE = doccells.LICENSE_PREF_KAGOSHIMA

NASE = "名瀬保健所"
TOKU = "徳之島保健所"
_BASE_ROWS = [   # (row_key, 原表の行の見出し〔検査用〕, is_total)
    (f"{NASE}|奄美市名瀬", "奄美市名瀬", 0), (f"{NASE}|奄美市住用町", "奄美市住用町", 0),
    (f"{NASE}|奄美市笠利町", "奄美市笠利町", 0), (f"{NASE}|大和村", "大和村", 0), (f"{NASE}|宇検村", "宇検村", 0),
    (f"{NASE}|瀬戸内町", "瀬戸内町", 0), (f"{NASE}|龍郷町", "龍郷町", 0), (f"{NASE}|名瀬計", "計", 1),
    (f"{TOKU}|徳之島町", "徳之島町", 0), (f"{TOKU}|天城町", "天城町", 0), (f"{TOKU}|伊仙町", "伊仙町", 0),
    (f"{TOKU}|徳之島計", "計", 1),
]
SPECS = {
    "kagoshima_habu_bite_h28r7": dict(
        suffix="bite", title="年度・保健所・市町村別ハブ咬傷者発生状況（最近10年間）", unit="人",
        pdf="data/raw/kagoshima_doc/habu_bite_h28r7.pdf",
        url="https://www.pref.kagoshima.jp/ae10/kenko-fukushi/yakuji-eisei/habu/documents/4348_20260420093052-1.pdf",
        rows=_BASE_ROWS + [("合計", "合計", 1)],
        sums={7: list(range(0, 7)), 11: [8, 9, 10], 12: [7, 11]},   # 合計の行 -> 足す行
        grand=12),
    "kagoshima_habu_kaiage_h28r7": dict(
        suffix="kaiage", title="年度・保健所・市町村・業者別ハブ買上状況（最近10年間）", unit="匹",
        pdf="data/raw/kagoshima_doc/habu_kaiage_h28r7.pdf",
        url="https://www.pref.kagoshima.jp/ae10/kenko-fukushi/yakuji-eisei/habu/documents/4349_20260420093702-1.pdf",
        rows=_BASE_ROWS + [("保健所計", "保健所計", 1), ("業者|名瀬管内", "名瀬管内", 0),
                           ("業者|徳之島管内", "徳之島管内", 0), ("業者計", "業者計", 1), ("全体計", "全体計", 1)],
        sums={7: list(range(0, 7)), 11: [8, 9, 10], 12: [7, 11], 15: [13, 14], 16: [12, 15]},
        grand=16),
}
FOOTNOTE_DEATH = "（　）は死亡者数で内数（原表の注記）"


# ------------------------------------------------------------ 文字と格子
def is_ratio_col(j):
    return j == NY + 1


def lenient(j, s):
    """整数の列の「.」は桁区切りカンマの誤読とみなして除く（構成比の列は小数点なので除かない）。"""
    return s if is_ratio_col(j) else s.replace(".", "")


def fmt_ok(j, s):
    if s == "":
        return True
    return bool(re.fullmatch(r"\d+\.\d%", s) if is_ratio_col(j) else re.fullmatch(r"\d+(\(\d+\))?", s))


def assign(data):
    """OCR の JSON -> (文字の行列、bbox、収まらない箱の理由、その数)。共通部分は ocr/cellmatch.py。"""
    return cellmatch.assign(data, lenient)


def label_report(spec, data):
    """行の見出し列の文字を、期待の見出しと照合（警告用）。-> [(行番号, 期待, OCR の文字)] の不一致"""
    g = data["grid"]
    x0, x1 = g["groupcol"][0], g["labelcol"][1]   # 「合計」「保健所計」の見出しは管内の列にまたがる
    bad = []
    for i, (y0, y1) in enumerate(g["rows"]):
        txt = norm("".join(b["text"] for b in sorted(data["boxes"], key=lambda b: b["x0"])
                           if x0 <= (b["x0"] + b["x1"]) / 2 <= x1 and y0 - 1 <= (b["y0"] + b["y1"]) / 2 <= y1 + 1))
        exp = spec["rows"][i][1]
        if exp not in txt and not (len(txt) >= 2 and txt in exp):
            bad.append((i, exp, txt))
    return bad


# ------------------------------------------------------------ 検算
def constraints(spec):
    """-> [(名前, 左辺の行・列のキー, 右辺のキー, 種類, 余分なキー)]。キーは (層, 行, 列)、層は n=件数・d=死亡数・r=構成比"""
    nrow = len(spec["rows"])
    out = []
    for layer in ("n", "d"):
        for i in range(nrow):
            out.append((f"{layer}:row[{i}]", [(layer, i, j) for j in range(NY)], (layer, i, NY), "sum", ()))
        for tot, mem in spec["sums"].items():
            for j in range(NY + 1):
                out.append((f"{layer}:col[{tot},{j}]", [(layer, i, j) for i in mem], (layer, tot, j), "sum", ()))
    for i in range(nrow):
        out.append((f"r:ratio[{i}]", [("n", i, NY)], ("r", i, NY + 1), "ratio",
                    (("n", i, NY), ("n", spec["grand"], NY))))
    return out


def evaluate(spec, lhs, rhs, kind, val):
    """val: キー -> 数値（未確定は無い前提）。-> True/False/None（空欄の構成比など検査対象外）"""
    if kind == "sum":
        return abs(sum(val[k] for k in lhs) - val[rhs]) < 0.5
    if val[rhs] is None:
        return None
    g = spec["grand"]
    grand = val[("n", g, NY)]
    return grand != 0 and abs(val[lhs[0]] / grand * 100 - val[rhs]) <= 0.06


# ------------------------------------------------------------ 本体
def parse_cell(s):
    """確定した文字 -> (件数, 死亡数)。空欄は (None, None)"""
    if s == "":
        return None, None
    return doccells.parse_count(s)


def to_float(s):
    return float(s.rstrip("%"))


def load_reviewed(path):
    return cellmatch.load_reviewed(path, norm)


def load_engines(doc_id, ocr_dir, pdf_root):
    """2つの OCR の JSON を読み、整合を確かめる。-> (data, pdf_sha256)。"""
    spec = SPECS[doc_id]
    return cellmatch.load_engines(doc_id, ocr_dir, len(spec["rows"]), NY + 2, pdf_root / spec["pdf"], "pdf_sha256")


def decide_state(spec, A, B, bad, reviewed):
    """2つの OCR の文字行列と人の確認 -> {(i,j): dict(text, by, …)}。text=None は未確定（reason 付き）。"""
    rowidx = {r[0]: i for i, r in enumerate(spec["rows"])}
    by_cell = {}
    for (rk, ck), (txt, who, note) in reviewed.items():
        if rk not in rowidx or ck not in COL_KEYS:
            raise ValueError(f"reviewed.csv: 行・列が不明 {rk!r} {ck!r}")
        i, j = rowidx[rk], COL_KEYS.index(ck)
        txt = lenient(j, txt)
        if not fmt_ok(j, txt):
            raise ValueError(f"reviewed.csv: 書式不正 {rk} {ck} {txt!r}")
        by_cell[(i, j)] = (txt, who, note)
    return cellmatch.decide(A, B, bad, fmt_ok, by_cell)


def arith_flag(spec, state):
    """確定したセルだけで検算し、疑うセルを絞る。-> (flagged, hints, touching, stats)。共通部分は cellmatch.arith_flag。
    人が確認したセルも、検算に合わなければ疑う（採用しない）。"""
    val, known = {}, set()
    for (i, j), s in state.items():
        if s["text"] is None:
            continue
        if is_ratio_col(j):
            val[("r", i, j)] = None if s["text"] == "" else to_float(s["text"])
            known.add(("r", i, j))
        else:
            n, dth = parse_cell(s["text"])
            val[("n", i, j)], val[("d", i, j)] = float(n or 0), float(dth or 0)
            known |= {("n", i, j), ("d", i, j)}
    return cellmatch.arith_flag(constraints(spec), val, known,
                                lambda lhs, rhs, kind, v: evaluate(spec, lhs, rhs, kind, v),
                                hint_ok=lambda name: not name.startswith("d:"))


def to_rows(spec, state, A, B, bbox, flagged, hints, touching, extractor, sha):
    """確定・未確定の状態から cells の行を作る。-> (rows, 未採用のセル数)。
    死亡数の行: 括弧のあるセルが1つでもある行は、値の読めた列を全部（括弧の無い列は 0）。読めない列は NULL。"""
    rows, n_unread = [], 0
    extracted_at = datetime.datetime.now().isoformat(timespec="seconds")
    for i, (rk, _lbl, row_total) in enumerate(spec["rows"]):
        main, death, has_death = [], [], False
        for j in range(NY + 2):
            s, ck = state[(i, j)], COL_KEYS[j]
            base = dict(page_no=1, table_id="p1_t1", row_key=rk, col_key=ck,
                        unit=UNIT_PCT if is_ratio_col(j) else spec["unit"],
                        fiscal_year=doccells.era_to_year(ck) if j < NY else None, era_raw=ck if j < NY else None,
                        source_bbox=json.dumps(bbox[i][j]), notes_ref=None, is_total=int(bool(row_total) or j == NY),
                        merged=0, extractor=extractor, extracted_at=extracted_at, doc_sha256=sha)
            arith = flagged.get((i, j))
            if s["text"] is None or arith:
                hint = f"（検算の示す値 {'/'.join(map(str, sorted(hints[(i, j)])))}）" if hints.get((i, j)) else ""
                if s["text"] is None:
                    reason = s["reason"] + hint
                else:
                    who = "人が確認した値が" if s["by"] == "reviewed" else "OCR が一致した値が"
                    reason = (f"{who}検算（{', '.join(arith)}）に合わない"
                              f"（{ENGINES[0]}={A[i][j]!r} {ENGINES[1]}={B[i][j]!r} 採用={s['text']!r}）")
                n_unread += 1
                cell = dict(base, value_raw=None, value=None, value_type=None,
                            source_text=f"{ENGINES[0]}={A[i][j]!r} {ENGINES[1]}={B[i][j]!r}",
                            unreadable_reason=f"ocr_disagree: {reason}", confidence=None, verified_by=None)
                main.append(cell)
                if j <= NY:
                    death.append(dict(cell))
                continue
            txt = s["text"]
            if s["by"] == "agree":
                by, conf = ("auto:xocr+arith", CONF_AUTO) if (touching.get(("n", i, j)) or touching.get(("r", i, j))) \
                    else ("auto:xocr", CONF_XOCR)
            else:
                by, conf = verified_by_for(s["reviewer"])
            ok = dict(unreadable_reason=None, confidence=conf, verified_by=by)
            if txt == "":
                cell = dict(base, value_raw=None, value=None, value_type=None, source_text="(空欄)", **ok)
                main.append(cell)
                if j <= NY:
                    death.append(dict(cell))
            elif is_ratio_col(j):
                main.append(dict(base, value_raw=txt, value=str(to_float(txt)), value_type="float", source_text=txt, **ok))
            else:
                n, dth = doccells.parse_count(txt)
                main.append(dict(doccells.count_cell(txt, **base), source_text=txt, **ok))
                has_death |= dth is not None
                death.append(dict(base, value_raw=None if dth is None else txt, value=str(dth or 0), value_type="int",
                                  source_text=txt, **ok))
        rows += main
        if has_death:
            rows += [dict(d, row_key=f"{rk}（うち死亡）") for d in death]
    return rows, n_unread


def build(doc_id, ocr_dir=OCR_DIR, pdf_root=ROOT):
    """-> dict(rows=cells の行, notes, stats, warnings)。DB には触れない。"""
    spec = SPECS[doc_id]
    data, sha = load_engines(doc_id, ocr_dir, pdf_root)
    warnings, texts, bad = [], {}, {}
    bbox = None
    for e in ENGINES:
        texts[e], b, bad_e, orphans = assign(data[e])
        bbox = bbox or b
        for cell, why in bad_e.items():
            bad.setdefault(cell, []).append(f"{e}: {why}")
        if orphans:
            warnings.append(f"{e}: 格子に収まらない OCR の箱 {orphans} 個（該当セルは未採用）")
        for i, exp, got in label_report(spec, data[e]):
            warnings.append(f"{e}: 行 {i} の見出し {got!r}（期待 {exp!r}）")
    A, B = (texts[e] for e in ENGINES)
    bad = {c: "; ".join(v) for c, v in bad.items()}
    state = decide_state(spec, A, B, bad, load_reviewed(ocr_dir / doc_id / "reviewed.csv"))
    flagged, hints, touching, stats = arith_flag(spec, state)
    for (i, j) in flagged:
        if state[(i, j)]["by"] == "reviewed":
            warnings.append(f"人が確認したセルが検算に合わない（未採用にした）: {spec['rows'][i][0]} {COL_KEYS[j]}")
    extractor = "ocr:" + "+".join(f"{e}@" + "+".join(f"{k}{v}" for k, v in data[e]["versions"].items()) for e in ENGINES)
    rows, n_unread = to_rows(spec, state, A, B, bbox, flagged, hints, touching, extractor, sha)
    nrow, ncol = len(spec["rows"]), NY + 2
    stats.update(n_cells=len(rows), unreadable=n_unread, ocr_disagree=sum(1 for s in state.values() if s["by"] is None),
                 reviewed=sum(1 for s in state.values() if s["by"] == "reviewed"), arith_flagged=len(flagged),
                 agree_rate=sum(1 for i in range(nrow) for j in range(ncol) if A[i][j] == B[i][j]) / (nrow * ncol),
                 pdf_sha256=sha)
    return dict(rows=rows, notes=notes_for(doc_id), stats=stats, warnings=warnings, spec=spec)


def notes_for(doc_id):
    spec = SPECS[doc_id]
    notes = [
        dict(kind="survey_scope", table_ids=["p1_t1"], page=1, text=(
            "表に載る範囲は名瀬保健所管内（奄美市〔名瀬・住用町・笠利町〕・大和村・宇検村・瀬戸内町・龍郷町）と、"
            "徳之島保健所管内（徳之島町・天城町・伊仙町）。徳之島は奄美大島ではない。"
            "「合計」「保健所計」「全体計」は両保健所管内の合算で、奄美大島だけの値ではない。")),
        dict(kind="footnote", table_ids=["p1_t1"], page=1, text=(
            "原表には 0 と空欄がどちらもある。空欄のセルは value を NULL とし（0 にはしない）、"
            "検算では 0 として扱った。空欄の意味は原表に説明が無い。")),
        dict(kind="footnote", table_ids=["p1_t1"], page=1, text=(
            "「合計（3月末）」の列は10年度分の合計で、構成比は合計（3月末）の列の全体の値に対する割合（%）。"
            "どちらも年度の系列ではないので fiscal_year は付けていない（is_total の列と構成比）。")),
    ]
    if spec["suffix"] == "bite":
        notes.append(dict(kind="footnote", table_ids=["p1_t1"], page=1, text=(
            "原表の注記: 「（　）は死亡者数で内数」。「5(1)」は咬傷者5人のうち死亡1人。"
            "死亡数は「…（うち死亡）」という行のセルに分けて入れた（value は死亡数）。"
            "死亡数の行には、括弧の無い年・列を 0 として入れた（括弧が無い＝死亡0と読んだ。原表に 0 の印字は無い）。")))
    else:
        notes.append(dict(kind="footnote", table_ids=["p1_t1"], page=1, text=(
            "「業者」の行（名瀬管内・徳之島管内・業者計）は市町村の行とは別の内訳で、保健所計には含まれない"
            "（全体計＝保健所計＋業者計）。")))
    return notes


# ------------------------------------------------------------ DB
def write(doc_id, built):
    spec, st = built["spec"], built["stats"]
    return doccells.commit_doc(
        doc_id,
        document=dict(title=spec["title"], publisher="鹿児島県 保健福祉部薬務課", url=spec["url"], local_path=spec["pdf"],
                      doc_sha256=st["pdf_sha256"], n_pages=1, fiscal_year=2025, license=LICENSE),
        cells=built["rows"], notes=built["notes"],
        log=[dict(verdict="pass" if not st["unreadable"] else "fail", page_no=1, table_id="p1_t1",
                  failures={"warnings": built["warnings"]} if built["warnings"] else None,
                  note=f"{SCRIPT_ID}: OCR 2種の一致率 {st['agree_rate']:.1%}、未採用 {st['unreadable']} セル、"
                       f"人の確認 {st['reviewed']} セル、検算 {st['evaluated']} 件中 失敗 {st['failed_constraints']} 件")])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", choices=["bite", "kaiage"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-register", action="store_true", help="source_registry に登録しない")
    a = ap.parse_args()
    total, written = 0, 0
    for doc_id, spec in SPECS.items():
        if a.doc and a.doc != spec["suffix"]:
            continue
        b = build(doc_id)
        st = b["stats"]
        print(f"{doc_id}: cells {st['n_cells']}（未採用 {st['unreadable']}、うち OCR 食い違い {st['ocr_disagree']}、検算で特定 {st['arith_flagged']}）"
              f"、人の確認 {st['reviewed']}、OCR 一致率 {st['agree_rate']:.1%}、検算 {st['evaluated']} 件・失敗 {st['failed_constraints']} 件")
        for w in b["warnings"]:
            print("  警告:", w)
        if not a.dry_run:
            write(doc_id, b)
            total += st["n_cells"]
            written += 1
    if written and not a.dry_run and not a.no_register and not a.doc:
        register(total)



def register(n_cells):
    """咬傷・買上の2文書をまとめて1出典として登録（record_count は2文書の cells 行数の合計）。"""
    common.register(
        SOURCE_ID, "鹿児島県 ハブ咬傷者数・ハブ買上数（奄美、保健所・市町村別、H28〜R7年度）",
        "鹿児島県 保健福祉部薬務課", "https://www.pref.kagoshima.jp/ae10/kenko-fukushi/yakuji-eisei/habu/index.html",
        "野生動物被害(ハブ)", "PDF（画像）→ OCR 2種＋検算 → cells.sqlite", "PDF", LICENSE, False, n_cells,
        "doc_id=kagoshima_habu_bite_h28r7・kagoshima_habu_kaiage_h28r7。OCR 2種の一致＋検算で採用。"
        "人の見直しが済んでいない3セル（reviewed.csv、claude(vision) が画像で確認）を含む。PDF は data/raw に置き再配布しない。")


if __name__ == "__main__":
    main()
