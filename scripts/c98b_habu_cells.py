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
7. verified_by: 一致＋検算が通った = `auto:xocr+arith`（confidence 1.0）／人の確認 = `human:<名前>`（1.0。reviewer が `claude(vision)` など AI のときは `claude(vision)` のまま。人の見直しは済んでいない）／
   一致したが検算で確かめられない（入る検算が1つも評価できない）= `auto:xocr`（0.8）／未採用 = NULL。
cells の形は §3d: row_key `名瀬保健所|奄美市名瀬`、計の行と「合計（3月末）」の列は is_total=1、構成比は float・%・
fiscal_year=NULL、「5(1)」は value=5 のセルと、`…（うち死亡）` という別の行のセル（value=1）、空欄は value=NULL。

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
import unicodedata
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import common
import doccells

ROOT = pathlib.Path(__file__).resolve().parent.parent
OCR_DIR = ROOT / "data/ocr/habu"
ENGINES = ("docling_rapid", "paddle")
YEAR_LABELS = ["H28", "H29", "H30", "R1", "R2", "R3", "R4", "R5", "R6", "R7"]
COL_TOTAL, COL_RATIO = "合計(3月末)", "構成比"
COL_KEYS = YEAR_LABELS + [COL_TOTAL, COL_RATIO]
NY = len(YEAR_LABELS)          # 年度の列数。列 NY が合計（3月末）、NY+1 が構成比
UNIT_PCT = "%"
SCRIPT_ID = "c98b_habu_cells"

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
def norm(s):
    return re.sub(r"[\s,，、]", "", unicodedata.normalize("NFKC", s or ""))


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
    """OCR の JSON -> (文字の行列 [行][列]、各セルの bbox [行][列])。列は年度10・合計・構成比の12。"""
    g = data["grid"]
    rows, cols = g["rows"], g["cols"]
    cells = [[[] for _ in cols] for _ in rows]
    for b in data["boxes"]:
        cx, cy = (b["x0"] + b["x1"]) / 2, (b["y0"] + b["y1"]) / 2
        ri = [i for i, (a, c) in enumerate(rows) if a - 1 <= cy <= c + 1]
        ci = [j for j, (a, c) in enumerate(cols) if a <= cx <= c]
        if ri and len(ci) == 1:
            cells[ri[0]][ci[0]].append((cx, b["text"]))
    text = [[lenient(j, norm("".join(t for _, t in sorted(c)))) for j, c in enumerate(r)] for r in cells]
    bbox = [[[round(cols[j][0], 1), round(rows[i][0], 1), round(cols[j][1], 1), round(rows[i][1], 1)]
             for j in range(len(cols))] for i in range(len(rows))]
    return text, bbox


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
    """-> [(名前, 左辺の行・列のキー, 右辺のキー, 種類)]。キーは (層, 行, 列)、層は n=件数・d=死亡数・r=構成比"""
    nrow = len(spec["rows"])
    out = []
    for layer in ("n", "d"):
        for i in range(nrow):
            out.append((f"{layer}:row[{i}]", [(layer, i, j) for j in range(NY)], (layer, i, NY), "sum"))
        for tot, mem in spec["sums"].items():
            for j in range(NY + 1):
                out.append((f"{layer}:col[{tot},{j}]", [(layer, i, j) for i in mem], (layer, tot, j), "sum"))
    for i in range(nrow):
        out.append((f"r:ratio[{i}]", [("n", i, NY)], ("r", i, NY + 1), "ratio"))
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


def verified_by_for(reviewer):
    """reviewed.csv の reviewer → verified_by。人の確認を装わない:
    `human:` で始まる名前だけを人とし、`claude(...)` など AI の確認はそのまま書く（c26 の前例: `claude(vision)`）。
    それ以外の名前（人名）は `human:<名前>`。"""
    r = reviewer.strip()
    if r.startswith("human:") or r.lower().startswith("claude"):
        return r
    return f"human:{r}"


def load_reviewed(path):
    if not path.exists():
        return {}
    out = {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if not (r.get("row") or "").strip():
                continue
            out[(r["row"].strip(), r["col"].strip())] = (norm(r["value"]), (r.get("reviewer") or "").strip(), r.get("note", ""))
    return out


def build(doc_id, ocr_dir=OCR_DIR):
    """-> dict(rows=cells の行, notes, stats, warnings)。DB には触れない。"""
    spec = SPECS[doc_id]
    d = ocr_dir / doc_id
    data = {e: json.load(open(d / f"{e}.json", encoding="utf-8")) for e in ENGINES}
    for e in ENGINES:
        if data[e]["doc_id"] != doc_id:
            raise ValueError(f"{e}.json の doc_id が違う: {data[e]['doc_id']}")
    ga, gb = data[ENGINES[0]]["grid"], data[ENGINES[1]]["grid"]
    for key in ("rows", "cols"):   # 2つの JSON の格子は同じ画像から取るので一致するはず
        for p, q in zip(ga[key], gb[key]):
            if max(abs(p[0] - q[0]), abs(p[1] - q[1])) > 2:
                raise ValueError(f"2つの JSON の格子（{key}）が一致しない: {p} {q}")
    nrow, ncol = len(spec["rows"]), NY + 2
    if len(ga["rows"]) != nrow or len(ga["cols"]) != ncol:
        raise ValueError(f"格子が {len(ga['rows'])}行×{len(ga['cols'])}列（期待 {nrow}×{ncol}）")
    texts, bbox = {}, None
    for e in ENGINES:
        texts[e], b = assign(data[e])
        bbox = bbox or b
    warnings = []
    for e in ENGINES:
        for i, exp, got in label_report(spec, data[e]):
            warnings.append(f"{e}: 行 {i} の見出し {got!r}（期待 {exp!r}）")
    A, B = (texts[e] for e in ENGINES)

    # 3. 確定／未確定
    state = {}      # (i,j) -> dict(text, by, reviewer, reason)
    for i in range(nrow):
        for j in range(ncol):
            a, b = A[i][j], B[i][j]
            if a == b and fmt_ok(j, a):
                state[(i, j)] = dict(text=a, by="agree")
                continue
            if a == b:
                why = f"書式不正 {a!r}（2つの OCR とも同じ）"
            elif {a, b} == {"", "0"}:
                why = f"0 と空欄の区別がつかない（{ENGINES[0]}={a!r} {ENGINES[1]}={b!r}）"
            else:
                why = f"{ENGINES[0]}={a!r} {ENGINES[1]}={b!r}" + ("" if fmt_ok(j, a) and fmt_ok(j, b) else "（書式不正あり）")
            state[(i, j)] = dict(text=None, by=None, reason=why)

    # 4. 人の確認
    reviewed = load_reviewed(d / "reviewed.csv")
    rowidx = {r[0]: i for i, r in enumerate(spec["rows"])}
    for (rk, ck), (txt, who, note) in reviewed.items():
        if rk not in rowidx or ck not in COL_KEYS:
            raise ValueError(f"reviewed.csv: 行・列が不明 {rk!r} {ck!r}")
        i, j = rowidx[rk], COL_KEYS.index(ck)
        txt = lenient(j, txt)
        if not fmt_ok(j, txt):
            raise ValueError(f"reviewed.csv: 書式不正 {rk} {ck} {txt!r}")
        if not who:
            raise ValueError(f"reviewed.csv: reviewer が空 {rk} {ck}")
        state[(i, j)] = dict(text=txt, by="human", reviewer=who, note=note)

    # 5. 検算（確定したセルだけで。疑われたセルは確定を取り消す）
    cons = constraints(spec)
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
    status, cons_keys, touching = {}, {}, defaultdict(set)   # 検算 -> 成否／検算 -> 入るキー／キー -> 入る検算
    for name, lhs, rhs, kind in cons:
        keys = set(lhs) | {rhs} | ({("n", rhs[1], NY), ("n", spec["grand"], NY)} if kind == "ratio" else set())
        if not keys <= known:
            continue
        ok = evaluate(spec, lhs, rhs, kind, val)
        if ok is None:
            continue
        status[name], cons_keys[name] = ok, keys
        for k in keys:
            touching[k].add(name)
    failed = {n for n, ok in status.items() if not ok}
    hints = defaultdict(set)   # 未確定のセル -> 件数の和の検算が示す値（人が確認するときの手がかり。採用はしない）
    for name, lhs, rhs, kind in cons:
        if kind != "sum" or name.startswith("d:"):
            continue
        missing = [k for k in list(lhs) + [rhs] if k not in known]
        if len(missing) == 1:
            k = missing[0]
            rest = sum(val[x] for x in lhs if x != k)
            hints[(k[1], k[2])].add(int(val[rhs] - rest) if k != rhs else int(rest))
    # 疑い候補 = 入る検算がすべて失敗しているキー。最小の組を貪欲法で選ぶ。候補で覆えない検算は全キーを疑う。
    suspects = {k for k, ns in touching.items() if ns <= failed}
    flagged_by_arith, remaining = {}, set(failed)
    while remaining:
        best = max(((k, remaining & touching[k]) for k in sorted(suspects) if remaining & touching[k]),
                   key=lambda kv: len(kv[1]), default=None)
        if best is None:
            n = min(remaining)
            picks, cov = sorted(cons_keys[n]), {n}
        else:
            picks, cov = [best[0]], best[1]
        for k in picks:
            c = (k[1], k[2])
            if state[c]["by"] == "human":
                warnings.append(f"人が確認したセルが検算に合わない: {spec['rows'][c[0]][0]} {COL_KEYS[c[1]]}（{sorted(cov)}）")
            else:
                flagged_by_arith.setdefault(c, set()).update(cov)
        remaining -= cov
    flagged_by_arith = {c: sorted(ns) for c, ns in flagged_by_arith.items()}
    stats = dict(failed_constraints=len(failed), evaluated=len(status))

    # 6. cells
    rows, extracted_at = [], datetime.datetime.now().isoformat(timespec="seconds")
    extractor = "ocr:" + "+".join(f"{e}@" + "+".join(f"{k}{v}" for k, v in data[e]["versions"].items()) for e in ENGINES)
    sha = data[ENGINES[0]]["pdf_sha256"]
    n_unread = 0
    for i, (rk, _lbl, row_total) in enumerate(spec["rows"]):
        for j in range(ncol):
            s = state[(i, j)]
            ck = COL_KEYS[j]
            is_total = int(bool(row_total) or j == NY)
            fy = doccells.era_to_year(ck) if j < NY else None
            base = dict(page_no=1, table_id="p1_t1", row_key=rk, col_key=ck, unit=UNIT_PCT if is_ratio_col(j) else spec["unit"],
                        fiscal_year=fy, era_raw=ck if j < NY else None, source_bbox=json.dumps(bbox[i][j]),
                        notes_ref=None, is_total=is_total, merged=0, extractor=extractor, extracted_at=extracted_at,
                        doc_sha256=sha)
            arith = flagged_by_arith.get((i, j))
            if s["text"] is None or arith:
                hint = f"（検算の示す値 {'/'.join(map(str, sorted(hints[(i, j)])))}）" if hints.get((i, j)) else ""
                reason = (s.get("reason") + hint) if s["text"] is None else \
                    f"検算（{', '.join(arith)}）が交点で特定（{ENGINES[0]}={A[i][j]!r} {ENGINES[1]}={B[i][j]!r}）"
                n_unread += 1
                rows.append(dict(base, value_raw=None, value=None, value_type=None, source_text=f"{ENGINES[0]}={A[i][j]!r} {ENGINES[1]}={B[i][j]!r}",
                                 unreadable_reason=f"ocr_disagree: {reason}", confidence=None, verified_by=None))
                continue
            txt = s["text"]
            by, conf = ("auto:xocr+arith", 1.0) if s["by"] == "agree" else (verified_by_for(s['reviewer']), 1.0)
            if s["by"] == "agree" and not (touching.get(("n", i, j)) or touching.get(("r", i, j))):
                by, conf = "auto:xocr", 0.8
            if txt == "":
                rows.append(dict(base, value_raw=None, value=None, value_type=None, source_text="(空欄)",
                                 unreadable_reason=None, confidence=conf, verified_by=by))
                continue
            if is_ratio_col(j):
                rows.append(dict(base, value_raw=txt, value=str(to_float(txt)), value_type="float", source_text=txt,
                                 unreadable_reason=None, confidence=conf, verified_by=by))
                continue
            n, dth = doccells.parse_count(txt)
            rows.append(dict(base, value_raw=txt, value=str(n), value_type="int", source_text=txt,
                             unreadable_reason=None, confidence=conf, verified_by=by))
            if dth is not None:
                rows.append(dict(base, row_key=f"{rk}（うち死亡）", value_raw=txt, value=str(dth), value_type="int",
                                 source_text=txt, unreadable_reason=None, confidence=conf, verified_by=by))
    stats.update(n_cells=len(rows), unreadable=n_unread, ocr_disagree=sum(1 for s in state.values() if s["by"] is None),
                 reviewed=sum(1 for s in state.values() if s["by"] == "human"),
                 arith_flagged=len(flagged_by_arith),
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
            "死亡数は「…（うち死亡）」という行のセルに分けて入れた（value は死亡数）。")))
    else:
        notes.append(dict(kind="footnote", table_ids=["p1_t1"], page=1, text=(
            "「業者」の行（名瀬管内・徳之島管内・業者計）は市町村の行とは別の内訳で、保健所計には含まれない"
            "（全体計＝保健所計＋業者計）。")))
    return notes


# ------------------------------------------------------------ DB
def write(doc_id, built):
    spec, st = built["spec"], built["stats"]
    con = common.cellsdb()
    try:
        doccells.write_doc(
            con, doc_id,
            document=dict(title=spec["title"], publisher="鹿児島県 保健福祉部薬務課", url=spec["url"], local_path=spec["pdf"],
                          doc_sha256=st["pdf_sha256"], n_pages=1, fiscal_year=2025,
                          license=LICENSE),
            cells=built["rows"], notes=built["notes"],
            log=[dict(verdict="pass" if not st["unreadable"] else "fail", page_no=1, table_id="p1_t1",
                      failures=built["warnings"],
                      note=f"{SCRIPT_ID}: OCR 2種の一致率 {st['agree_rate']:.1%}、未採用 {st['unreadable']} セル、"
                           f"人の確認 {st['reviewed']} セル、検算 {st['evaluated']} 件中 失敗 {st['failed_constraints']} 件")])
    finally:
        con.close()


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


SOURCE_ID = "kagoshima_habu_amami"
LICENSE = "鹿児島県ホームページ（無断転載・改変不可）。事実（数値）のみ抽出し出典を明記"


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
