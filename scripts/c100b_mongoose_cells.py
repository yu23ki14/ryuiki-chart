"""奄美大島のマングース捕獲数・わな日・CPUE（2000〜2022年度、環境省のお知らせの表1 = PNG）の OCR 結果の JSON から、
行政文書の cells を作る。**OCR のライブラリは使わない**（JSON だけ読む。CI の pytest が JSON のフィクスチャから回す）。
OCR 本体は c100_mongoose_ocr_run.py（別の venv）。

設計: docs/plans/AMAMI_STEP3A.md §2〜§4・§5。ハブ（c98b）と同じ仕組みで、2つの OCR を並べて一致したセルだけを検算つきで
採用する。2つの OCR の突き合わせ・reviewer の検査・疑うセルの絞り込みは ocr/cellmatch.py に共通化してある。

流れ:
1. JSON の文字を、c100 が取った格子（行帯＝年度23＋合計、列＝わな捕獲数・のべわな日・CPUE・探索犬・総捕獲の5）に割り当てる。
2. 文字を正規化する。**整数の列の「.」は桁区切りの誤読として除く**（CPUE の列は小数点なので除かない）。
   書式（整数の列は `\\d+`、CPUE は `\\d+\\.\\d{3,4}`、空欄は可）と、空欄があるはずの場所（2000年度のわな日・CPUE、
   2000〜2007年度の探索犬）を検査する。空欄が別の場所にある・空欄のはずの場所に値があるセルは採用しない。
3. 2つの OCR が一致し書式も正しいセルだけを「確定」にする。data/ocr/mongoose/<doc_id>/reviewed.csv を未確定のセルに当てる。
4. 検算: 総捕獲 = わな捕獲 + 探索犬（空欄は 0）、CPUE ≒ 捕獲 ÷ わな日 × 1000（印字桁の半分以内。2001年度以降と合計）、
   列の和 = 合計。失敗した検算に対し、疑うセルを絞って確定を取り消す。ほかに年度ラベルの並び・括弧内の西暦を警告する。
5. 評価シート（令和4年度）の表1（data/raw/amami_doc/mon_a-4-j.pdf p.54、文字情報のある同じ表）と全セルを突き合わせる。
   CPUE は3桁に丸めて比べる。合計の CPUE（PNG 0.616・シート 0.513。シートは2001年度以降の捕獲数で計算）だけが
   宣言した差で、過不足なく一致しなければ止める。PDF（または pdfplumber）が無いときは警告して飛ばす（CI の最小環境）。
6. verified_by: 2つの OCR が一致し、年度の列でシートとも一致 = `auto:xocr+xtext`（1.0）／一致し検算が通った
   （合計の列・行、空欄のはずの場所など）= `auto:xocr+arith`（1.0）／人・AI の確認 = reviewer（`human:` 1.0・AI 0.9）／
   一致したが確かめる検算が無い = `auto:xocr`（0.8）／未採用 = NULL。OCR が食い違うセルは `unreadable_reason` に
   シート・検算の示す値を書くだけで採用しない。

cells の形は §3: 行＝指標5本（PNG の転置）、列＝年度（`2000`〜`2022`）と `合計`。合計の列は is_total=1・fiscal_year=NULL。

使い方: python3 scripts/c100b_mongoose_cells.py [--dry-run] [--no-register]
reviewed.csv の列: row（row_key）, col（col_key: 2000〜2022・合計）, value（原表の表記。空欄は空）, reviewer, note
"""
import argparse
import datetime
import json
import pathlib
import re
import sys
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import common
import doccells
from ocr import cellmatch

ROOT = common.ROOT
OCR_DIR = ROOT / "data/ocr/mongoose"
ENGINES = cellmatch.ENGINES
DOC_ID = "moe_mongoose_catch_h12r4"
SOURCE_ID = "moe_mongoose_amami"
SCRIPT_ID = "c100b_mongoose_cells"
LICENSE = doccells.LICENSE_MOE_PDL
PNG = "data/raw/moe_mongoose/r4_hyo1_000157229.png"
SHEET_PDF = "data/raw/amami_doc/mon_a-4-j.pdf"
SHEET_PAGE = 54
URL = "https://kyushu.env.go.jp/okinawa/press_00065.html"
TITLE = "奄美大島におけるマングース捕獲数・捕獲努力量・CPUE の経年推移（2000〜2022年度）"
PUBLISHER = "環境省 沖縄奄美自然環境事務所"

YEARS = list(range(2000, 2023))
NYEAR = len(YEARS)                       # 行 NYEAR が合計
NROW, NCOL = NYEAR + 1, 5
COL_TOTAL = "合計"
COL_KEYS = [str(y) for y in YEARS] + [COL_TOTAL]   # PNG の行（i）= cells の col_key
# PNG の列（j）= cells の row_key。(row_key, unit, 種類)
METRICS = [
    ("わな捕獲|捕獲頭数", "頭", "int"),
    ("わな捕獲|のべわな日", "わな日", "int"),
    ("わな捕獲|CPUE", "頭/1000わな日", "cpue"),
    ("探索犬|探索犬による捕獲頭数", "頭", "int"),
    ("総捕獲頭数", "頭", "int"),
]
J_CATCH, J_TRAP, J_CPUE, J_DOG, J_TOTAL = range(5)
ROW_KEYS = [m[0] for m in METRICS]
# 空欄があるはずの場所（原表の注記・探索犬の導入は2008年度）
BLANK = {(0, J_TRAP), (0, J_CPUE)} | {(i, J_DOG) for i in range(2000 - 2000, 2008 - 2000)}
# 評価シートとの宣言した差: (row_key, col_key) -> (PNG, シート)
DECLARED_SHEET_DIFF = {("わな捕獲|CPUE", COL_TOTAL): ("0.616", "0.513")}


# ------------------------------------------------------------ 文字と書式
def norm(s):
    return cellmatch.norm(s)


def lenient(j, s):
    """整数の列の「.」は桁区切りカンマの誤読とみなして除く（CPUE の列は小数点なので除かない）。"""
    return s if j == J_CPUE else s.replace(".", "")


def fmt_ok(j, s):
    if s == "":
        return True
    return bool(re.fullmatch(r"\d+\.\d{3,4}", s) if j == J_CPUE else re.fullmatch(r"\d+", s))


def era_label(year):
    """西暦の年度 -> 原表の見出し（空白を除いた形）。平成12年度(2000)・令和元年度(2019)。"""
    if year >= 2019:
        n = year - 2018
        return f"令和{'元' if n == 1 else n}年度({year})"
    return f"平成{year - 1988}年度({year})"


def printed(j, s):
    """確定した文字 -> 原表の表記（整数はカンマ付き、CPUE は印字の桁のまま）。"""
    return s if j == J_CPUE else f"{int(s):,}"


def label_report(data):
    """行の見出し列（年度ラベル）を照合する（警告用）。-> [(行番号, 期待, OCR の文字)] の不一致。
    ラベルの括弧内の西暦が行の並びと合うか、最後の行が「合計」か。labelcol の無い JSON は照合しない。"""
    lc = data["grid"].get("labelcol")
    if not lc:
        return []
    bad = []
    for i, (y0, y1) in enumerate(data["grid"]["rows"]):
        txt = norm("".join(b["text"] for b in sorted(data["boxes"], key=lambda b: b["x0"])
                           if lc[0] <= (b["x0"] + b["x1"]) / 2 <= lc[1] and y0 - 1 <= (b["y0"] + b["y1"]) / 2 <= y1 + 1))
        if i == NYEAR:
            exp = COL_TOTAL
            ok = COL_TOTAL in txt
        else:
            exp = str(YEARS[i])
            ok = exp in txt
        if not ok:
            bad.append((i, exp, txt))
    return bad


# ------------------------------------------------------------ 検算
def constraints():
    """-> [(名前, 左辺のキー, 右辺のキー, 種類, 余分なキー)]。キーは ('n', 行, 列)。
    空欄があるはずのセル（BLANK）は 0 として足すだけなので、左辺には入れない（疑うセルの候補にしない）。"""
    def keys(rows, j):
        return [("n", i, j) for i in rows if (i, j) not in BLANK]
    out = []
    for i in range(NROW):
        out.append((f"total[{i}]", keys([i], J_CATCH) + keys([i], J_DOG), ("n", i, J_TOTAL), "sum", ()))
    for j in (J_CATCH, J_TRAP, J_DOG, J_TOTAL):
        out.append((f"col[{j}]", keys(range(NYEAR), j), ("n", NYEAR, j), "sum", ()))
    for i in range(1, NROW):   # 2000年度はわな日・CPUE が空欄
        out.append((f"cpue[{i}]", [("n", i, J_CATCH), ("n", i, J_TRAP)], ("n", i, J_CPUE), "cpue", ()))
    return out


def make_evaluate(digits):
    """digits: 行 -> CPUE の印字の小数桁数。"""
    def evaluate(lhs, rhs, kind, val):
        if kind == "sum":
            return abs(sum(val[k] for k in lhs) - val[rhs]) < 0.5
        if val[rhs] is None:
            return None
        catch, trap = val[lhs[0]], val[lhs[1]]
        return trap > 0 and abs(catch / trap * 1000 - val[rhs]) <= 0.5 * 10 ** -digits[rhs[1]] + 1e-9
    return evaluate


def arith_flag(state):
    """確定したセルだけで検算し、疑うセルを絞る。人が確認したセルも検算に合わなければ疑う。
    -> (flagged {(i,j): [検算名]}, hints, touching, stats)"""
    val, known, digits = {}, set(), {}
    for (i, j), s in state.items():
        if s["text"] is None:
            continue
        key = ("n", i, j)
        if s["text"] == "":
            val[key] = None if j == J_CPUE else 0.0
        else:
            val[key] = float(s["text"])
            if j == J_CPUE:
                digits[i] = len(s["text"].split(".")[1])
        known.add(key)
    return cellmatch.arith_flag(constraints(), val, known, make_evaluate(digits))


# ------------------------------------------------------------ 評価シート
def sheet_rows(pdf_path, page=SHEET_PAGE):
    """評価シートの表1（文字情報）-> {(i, j): 表記}。ページ内の「2000 3,884 …」「合計 …」の行を読む。
    のべわな日・CPUE・探索犬が空欄の行は項目が減る（2項目＝2000年度、4項目＝探索犬なし）。"""
    _, tables = doccells.pdf_tables(pdf_path, [page])
    lines = [ln for t in tables[page] for row in t for cell in row if cell for ln in cell.split("\n")]
    out = {}
    for ln in lines:
        tok = ln.split()
        if not tok or tok[0] not in COL_KEYS:
            continue
        vals = [norm(t) for t in tok[1:]]
        if not all(re.fullmatch(r"\d+(\.\d+)?", v) for v in vals):
            continue
        i = COL_KEYS.index(tok[0])
        layout = {2: (J_CATCH, J_TOTAL), 4: (J_CATCH, J_TRAP, J_CPUE, J_TOTAL),
                  5: (J_CATCH, J_TRAP, J_CPUE, J_DOG, J_TOTAL)}.get(len(vals))
        if layout is None:
            raise ValueError(f"評価シートの行の項目数が想定外: {ln!r}")
        row = {j: "" for j in range(NCOL)}
        row.update(dict(zip(layout, vals)))
        for j, v in row.items():
            if (i, j) in out and out[(i, j)] != v:
                raise ValueError(f"評価シートの行が重複して食い違う: {tok[0]} {ROW_KEYS[j]}")
            out[(i, j)] = v
    missing = [COL_KEYS[i] for i in range(NROW) if (i, J_CATCH) not in out]
    if missing:
        raise ValueError(f"評価シートに行が無い: {missing}")
    return out


def sheet_compare(sheet, state):
    """確定したセルを評価シートと比べる。CPUE は3桁に丸めて比べる。-> (一致したセルの集合〔年度の行〕, 宣言した差の実際)。
    宣言した差の集合が過不足なく一致しなければ doccells.IdentityError（止める）。"""
    q3 = Decimal("0.001")
    observed = {}
    for (i, j), s in state.items():
        if s["text"] is None:
            continue
        a, b = s["text"], sheet[(i, j)]
        if j == J_CPUE and i < NYEAR:   # 合計の CPUE は宣言した差を比べるので、丸めず原表の表記のまま
            a, b = (str(Decimal(x).quantize(q3, ROUND_HALF_UP)) if x else x for x in (a, b))
        observed[(ROW_KEYS[j], COL_KEYS[i])] = (a, b)
    declared = {k: v for k, v in DECLARED_SHEET_DIFF.items() if k in observed}
    actual = doccells.check_identity("PNG と評価シート（令和4年度）の表1", observed, declared)
    matched = {(i, j) for (i, j), s in state.items()
               if s["text"] is not None and i < NYEAR and (ROW_KEYS[j], COL_KEYS[i]) not in actual}
    return matched, actual


# ------------------------------------------------------------ 本体
def to_rows(state, A, B, bbox, flagged, hints, touching, sheet_ok, extractor, sha):
    """確定・未確定の状態から cells の行を作る。-> (rows, 未採用のセル数)"""
    rows, n_unread = [], 0
    extracted_at = datetime.datetime.now().isoformat(timespec="seconds")
    for j, (rk, unit, kind) in enumerate(METRICS):
        for i, ck in enumerate(COL_KEYS):
            s, is_total = state[(i, j)], i == NYEAR
            base = dict(page_no=1, table_id="p1_t1", row_key=rk, col_key=ck, unit=unit,
                        fiscal_year=None if is_total else YEARS[i], era_raw=None if is_total else era_label(YEARS[i]),
                        source_bbox=json.dumps(bbox[i][j]), notes_ref=None, is_total=int(is_total),
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
                rows.append(dict(base, value_raw=None, value=None, value_type=None,
                                 source_text=f"{ENGINES[0]}={A[i][j]!r} {ENGINES[1]}={B[i][j]!r}",
                                 unreadable_reason=f"ocr_disagree: {reason}", confidence=None, verified_by=None))
                continue
            txt = s["text"]
            if s["by"] == "agree":
                if (i, j) in sheet_ok:
                    by, conf = "auto:xocr+xtext", cellmatch.CONF_AUTO
                elif touching.get(("n", i, j)) or (i, j) in BLANK:
                    by, conf = "auto:xocr+arith", cellmatch.CONF_AUTO
                else:
                    by, conf = "auto:xocr", cellmatch.CONF_XOCR
            else:
                by, conf = cellmatch.verified_by_for(s["reviewer"])
            ok = dict(unreadable_reason=None, confidence=conf, verified_by=by)
            if txt == "":
                rows.append(dict(base, value_raw=None, value=None, value_type=None, source_text="(空欄)", **ok))
            else:
                raw = printed(j, txt)
                if kind == "cpue":
                    rows.append(dict(base, value_raw=raw, value=str(float(txt)), value_type="float", source_text=raw, **ok))
                else:
                    rows.append(dict(base, value_raw=raw, value=str(int(txt)), value_type="int", source_text=raw, **ok))
    return rows, n_unread


def build(ocr_dir=None, root=ROOT, sheet_pdf="default"):
    """-> dict(rows=cells の行, notes, stats, warnings)。DB には触れない。
    sheet_pdf: 評価シートの PDF のパス。既定は root/data/raw/amami_doc/mon_a-4-j.pdf（無ければ警告して飛ばす）、None なら使わない。"""
    ocr_dir = ocr_dir or OCR_DIR
    data, sha = cellmatch.load_engines(DOC_ID, ocr_dir, NROW, NCOL, root / PNG, "pdf_sha256", "PNG")
    warnings, texts, bad, bbox = [], {}, {}, None
    for e in ENGINES:
        texts[e], b, bad_e, orphans = cellmatch.assign(data[e], lenient)
        bbox = bbox or b
        for cell, why in bad_e.items():
            bad.setdefault(cell, []).append(f"{e}: {why}")
        if orphans:
            warnings.append(f"{e}: 格子に収まらない OCR の箱 {orphans} 個（該当セルは未採用）")
        for i, exp, got in label_report(data[e]):
            warnings.append(f"{e}: 行 {i} の見出し {got!r}（期待に {exp!r} を含む）")
    A, B = (texts[e] for e in ENGINES)
    bad = {c: "; ".join(v) for c, v in bad.items()}
    reviewed = {}
    for (rk, ck), (txt, who, note) in cellmatch.load_reviewed(ocr_dir / DOC_ID / "reviewed.csv", norm).items():
        if rk not in ROW_KEYS or ck not in COL_KEYS:
            raise ValueError(f"reviewed.csv: 行・列が不明 {rk!r} {ck!r}")
        i, j = COL_KEYS.index(ck), ROW_KEYS.index(rk)
        txt = lenient(j, txt)
        if not fmt_ok(j, txt):
            raise ValueError(f"reviewed.csv: 書式不正 {rk} {ck} {txt!r}")
        reviewed[(i, j)] = (txt, who, note)
    state = cellmatch.decide(A, B, bad, fmt_ok, reviewed)
    for (i, j), s in state.items():   # 空欄があるはずの場所だけが空欄
        if s["text"] is not None and ((s["text"] == "") != ((i, j) in BLANK)):
            kind = "空欄のはずの場所に値がある" if s["text"] else "空欄のはずでない場所が空欄"
            state[(i, j)] = dict(text=None, by=None, reason=f"{kind}（{ENGINES[0]}={A[i][j]!r} {ENGINES[1]}={B[i][j]!r}）")
            if s["by"] == "reviewed":
                warnings.append(f"人が確認したセルが空欄の構造に合わない（未採用にした）: {ROW_KEYS[j]} {COL_KEYS[i]}")
    flagged, hints, touching, stats = arith_flag(state)
    for (i, j) in flagged:
        if state[(i, j)]["by"] == "reviewed":
            warnings.append(f"人が確認したセルが検算に合わない（未採用にした）: {ROW_KEYS[j]} {COL_KEYS[i]}")
    sheet_ok, declared_diff = set(), {}
    if sheet_pdf == "default":
        sheet_pdf = root / SHEET_PDF
    if sheet_pdf is not None and pathlib.Path(sheet_pdf).exists():
        try:
            sheet = sheet_rows(sheet_pdf)
        except ImportError:
            warnings.append("pdfplumber が無いので評価シートとの突き合わせを飛ばした（xocr+arith に落とす）")
        else:
            adopted = {c: s for c, s in state.items() if c not in flagged}
            sheet_ok, declared_diff = sheet_compare(sheet, adopted)
    else:
        warnings.append("評価シートの PDF が無いので突き合わせを飛ばした（xocr+arith に落とす）")
    extractor = "ocr:" + "+".join(f"{e}@" + "+".join(f"{k}{v}" for k, v in data[e]["versions"].items()) for e in ENGINES)
    rows, n_unread = to_rows(state, A, B, bbox, flagged, hints, touching, sheet_ok, extractor, sha)
    stats.update(n_cells=len(rows), unreadable=n_unread, ocr_disagree=sum(1 for s in state.values() if s["by"] is None),
                 reviewed=sum(1 for s in state.values() if s["by"] == "reviewed"), arith_flagged=len(flagged),
                 sheet_matched=len(sheet_ok), sheet_declared_diff=sorted(declared_diff),
                 agree_rate=sum(1 for i in range(NROW) for j in range(NCOL) if A[i][j] == B[i][j]) / (NROW * NCOL),
                 input_sha256=sha)
    return dict(rows=rows, notes=notes(), stats=stats, warnings=warnings)


def notes():
    t = ["p1_t1"]
    return [
        dict(kind="survey_scope", table_ids=t, page=1, blocks_timeseries=0, text=(
            "奄美大島。環境省の防除事業（わな捕獲＋探索犬）の年度（4月〜3月）ごとの値。表の列は「わな捕獲総計」"
            "「探索犬の発見による捕獲」「総捕獲頭数」。2000年度は環境庁（当時）と鹿児島県が開始した事業で、"
            "2001年度から環境省のみ（報道発表の記述）。")),
        dict(kind="footnote", table_ids=t, page=1, blocks_timeseries=0, text=(
            "わな日＝のべわな日数（わなの数×わな有効日数）、CPUE＝わなによるマングース捕獲数 ÷ 1,000わな日"
            "（お知らせの注記 *1・*2）。CPUE の単位は全年度 頭/1,000わな日。")),
        dict(kind="comparability", table_ids=t, page=1, blocks_timeseries=0, text=(
            "2000年度はわな日の集計が不十分でわな日・CPUE が無い（原表の注記）。探索犬の列は導入前の2007年度以前は空欄。"),
            reason="2000年度のわな日・CPUE は空欄"),
        dict(kind="footnote", table_ids=t, page=1, blocks_timeseries=0, text=(
            "合計の CPUE は原表（PNG）が 0.616（2000年度の捕獲数を含めて計算）、評価シート（令和4年度）の同じ表は 0.513"
            "（2001年度以降の捕獲数 19,245 頭で計算）。値は PNG の印字どおり入れた。")),
        dict(kind="footnote", table_ids=t, page=1, blocks_timeseries=0, text=(
            "2018年度の CPUE は原表（PNG）が 0.0004（ほかの年度と桁が違う印字）。評価シートでは 0.000。")),
        dict(kind="footnote", table_ids=t, page=1, blocks_timeseries=0, text=(
            "2018年4月に1頭を捕獲して以降、わなによる捕獲は 0（2019〜2022年度は表のとおり 0）。"
            "2023年度以降の数表は未取得。")),
    ]


# ------------------------------------------------------------ DB
def write(built, register=True):
    st = built["stats"]
    return doccells.commit_doc(
        DOC_ID,
        document=dict(title=TITLE, publisher=PUBLISHER, url=URL, local_path=PNG.removeprefix("data/raw/"),
                      doc_sha256=st["input_sha256"], n_pages=1, fiscal_year=2022, license=LICENSE),
        cells=built["rows"], notes=built["notes"],
        log=[dict(verdict="pass" if not st["unreadable"] else "fail", page_no=1, table_id="p1_t1",
                  failures={"warnings": built["warnings"]} if built["warnings"] else None,
                  note=f"{SCRIPT_ID}: OCR 2種の一致率 {st['agree_rate']:.1%}、未採用 {st['unreadable']} セル、"
                       f"人の確認 {st['reviewed']} セル、評価シートと一致 {st['sheet_matched']} セル、"
                       f"検算 {st['evaluated']} 件中 失敗 {st['failed_constraints']} 件")],
        source=source_args() if register else None)


def source_args():
    return dict(
        source_id=SOURCE_ID, name="環境省 奄美大島 マングース捕獲数・わな日・CPUE（2000〜2022年度）",
        publisher=PUBLISHER, url=URL, category="野生動物被害(マングース防除)",
        access_method="PNG（画像）→ OCR 2種＋検算＋評価シート突き合わせ → cells.sqlite", fmt="PNG",
        license_=LICENSE, redistributable=True,
        notes=("doc_id=moe_mongoose_catch_h12r4（PNG の表を OCR 2種＋検算＋評価シート突き合わせ、2000〜2022年度）・"
               "moe_mongoose_eradication_declaration_2024（documents と notes だけ）。2023年度以降の数表は未取得。"
               "PNG は data/raw に置き再配布しない。"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="DB に書かない")
    ap.add_argument("--no-register", action="store_true", help="source_registry に登録しない")
    a = ap.parse_args()
    b = build()
    st = b["stats"]
    print(f"{DOC_ID}: cells {st['n_cells']}（未採用 {st['unreadable']}、うち OCR 食い違い {st['ocr_disagree']}、検算で特定 {st['arith_flagged']}）"
          f"、人の確認 {st['reviewed']}、評価シートと一致 {st['sheet_matched']}、OCR 一致率 {st['agree_rate']:.1%}、"
          f"検算 {st['evaluated']} 件・失敗 {st['failed_constraints']} 件")
    for w in b["warnings"]:
        print("  警告:", w)
    if a.dry_run:
        return
    if st["unreadable"]:
        raise SystemExit(f"未採用のセルが {st['unreadable']} 個ある。reviewed.csv で確認してから書く")
    write(b, register=not a.no_register)


if __name__ == "__main__":
    main()
