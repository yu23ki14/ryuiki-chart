"""2つの OCR の JSON を格子に割り当てて突き合わせる、表の形に依らない部分。**OCR のライブラリは使わない**
（標準ライブラリだけ。CI の pytest が JSON のフィクスチャから回す）。

ハブ統計（c98b_habu_cells.py）から移した（設計: docs/plans/AMAMI_STEP3A.md §5）。使い方は `from ocr import cellmatch`
（`scripts/` が sys.path にあること）。列ごとの差（書式・小数点の扱い）は引数で渡す。検算の式（何と何が等しいか）は
表ごとに違うのでハブ・マングースの側に残し、疑うセルの絞り込みだけを `arith_flag` に共通化した。

API: norm / verified_by_for / load_reviewed / assign / decide / load_engines / arith_flag（各関数の docstring を見る）。
"""
import csv
import json
import re
import unicodedata
from collections import defaultdict

import common   # sha256。標準ライブラリだけで import できる（requests は遅延 import）

ENGINES = ("docling_rapid", "paddle")
KNOWN_AI = ("claude", "gpt", "gemini")   # reviewed.csv の reviewer がこれで始まれば AI の確認（人の確認として扱わない）
CONF_HUMAN, CONF_AI, CONF_AUTO, CONF_XOCR = 1.0, 0.9, 1.0, 0.8


def norm(s):
    return re.sub(r"[\s,，、]", "", unicodedata.normalize("NFKC", s or ""))


def verified_by_for(reviewer):
    """reviewed.csv の reviewer -> (verified_by, confidence)。人の確認を装わない。既定は拒否:
    `human:` で始まる名前だけを人（confidence 1.0）、既知の AI（claude・gpt・gemini で始まる名前）は名前のまま
    （AI は 0.9。人の見直しは済んでいない）、それ以外は ValueError（人なら `human:<名前>` と書く）。"""
    r = (reviewer or "").strip()
    if r.startswith("human:") and len(r) > len("human:"):
        return r, CONF_HUMAN
    if r.lower().startswith(KNOWN_AI):
        return r, CONF_AI
    raise ValueError(f"reviewer が不明: {r!r}（人は `human:<名前>`、AI は claude・gpt・gemini で始まる名前）")


def load_reviewed(path):
    """reviewed.csv（列: row, col, value, reviewer, note）-> {(row_key, col_key): (正規化した値, reviewer, note)}"""
    if not path.exists():
        return {}
    out = {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if not (r.get("row") or "").strip():
                continue
            who = (r.get("reviewer") or "").strip()
            if not who:
                raise ValueError(f"reviewed.csv: reviewer が空 {r['row']} {r['col']}")
            verified_by_for(who)   # 不明な名前はここで止める
            out[(r["row"].strip(), r["col"].strip())] = (norm(r["value"]), who, r.get("note", ""))
    return out


def assign(data, lenient=None):
    """OCR の JSON -> (文字の行列 [行][列]、各セルの bbox、収まらない箱の理由 {(行,列): 文字}、収まらない箱の数)。
    データ領域（格子の内側）に中心がある箱が、列を1つに決められない（どの列にも入らない・2列にまたがる）ときは、
    近いセルを未採用にするために理由を返す（黙って空欄にしない）。見出し・格子の外の列・表の外は無視する。
    lenient(j, s): 列ごとの後処理（例: 整数の列の「.」を桁区切りの誤読として除く）。None なら何もしない。"""
    g = data["grid"]
    rows, cols = g["rows"], g["cols"]
    x_lo, x_hi, y_lo, y_hi = cols[0][0], cols[-1][1], rows[0][0] - 1, rows[-1][1] + 1
    cells = [[[] for _ in cols] for _ in rows]
    bad, orphans = {}, 0
    for b in data["boxes"]:
        cx, cy = (b["x0"] + b["x1"]) / 2, (b["y0"] + b["y1"]) / 2
        if not (x_lo <= cx <= x_hi and y_lo <= cy <= y_hi):
            continue
        ri = [i for i, (a, c) in enumerate(rows) if a - 1 <= cy <= c + 1]
        w = max(b["x1"] - b["x0"], 1e-9)
        # 箱の幅（または列の幅）の 30% 以上が重なる列を数える。2列以上なら「またがる」
        over = [j for j, (a, c) in enumerate(cols) if min(b["x1"], c) - max(b["x0"], a) > 0.3 * min(w, c - a)]
        ci = [j for j, (a, c) in enumerate(cols) if a <= cx <= c]
        if ri and len(ci) == 1 and len(over) <= 1:
            cells[ri[0]][ci[0]].append((cx, b["text"]))
            continue
        orphans += 1
        near_r = ri or [min(range(len(rows)), key=lambda k: abs((rows[k][0] + rows[k][1]) / 2 - cy))]
        near_c = sorted(set(over) | set(ci)) or [min(range(len(cols)), key=lambda k: abs((cols[k][0] + cols[k][1]) / 2 - cx))]
        for i in near_r:
            for j in near_c:
                bad[(i, j)] = f"箱 {b['text']!r} が列を決められない"
    lenient = lenient or (lambda j, s: s)
    text = [[lenient(j, norm("".join(t for _, t in sorted(c)))) for j, c in enumerate(r)] for r in cells]
    bbox = [[[round(cols[j][0], 1), round(rows[i][0], 1), round(cols[j][1], 1), round(rows[i][1], 1)]
             for j in range(len(cols))] for i in range(len(rows))]
    return text, bbox, bad, orphans


def decide(A, B, bad, fmt_ok, reviewed=None, locate=None, lenient=None, engines=ENGINES):
    """2つの OCR の文字行列（A=engines[0]、B=engines[1]）と人の確認 -> {(i,j): dict(text, by, …)}。text=None は未確定（reason 付き）。
    fmt_ok(j, s): 列 j の書式検査。reviewed: load_reviewed の結果 {(row_key, col_key): (値, reviewer, note)}。
    locate(row_key, col_key) -> (i, j)（不明な行・列は None）。lenient(j, s): assign と同じ列ごとの後処理を人の値にも掛ける。
    人の値の行・列が不明、または書式不正なら ValueError（reviewed.csv の誤りは止める）。"""
    state = {}
    for i in range(len(A)):
        for j in range(len(A[i])):
            a, b = A[i][j], B[i][j]
            if (i, j) in bad:
                state[(i, j)] = dict(text=None, by=None, reason=f"OCR の箱が格子に収まらない（{bad[(i, j)]}）")
            elif a == b and fmt_ok(j, a):
                state[(i, j)] = dict(text=a, by="agree")
            elif a == b:
                state[(i, j)] = dict(text=None, by=None, reason=f"書式不正 {a!r}（2つの OCR とも同じ）")
            elif {a, b} == {"", "0"}:
                state[(i, j)] = dict(text=None, by=None,
                                     reason=f"0 と空欄の区別がつかない（{engines[0]}={a!r} {engines[1]}={b!r}）")
            else:
                state[(i, j)] = dict(text=None, by=None, reason=f"{engines[0]}={a!r} {engines[1]}={b!r}"
                                     + ("" if fmt_ok(j, a) and fmt_ok(j, b) else "（書式不正あり）"))
    for (rk, ck), (txt, who, note) in (reviewed or {}).items():
        cell = locate(rk, ck)
        if cell is None:
            raise ValueError(f"reviewed.csv: 行・列が不明 {rk!r} {ck!r}")
        i, j = cell
        txt = lenient(j, txt) if lenient else txt
        if not fmt_ok(j, txt):
            raise ValueError(f"reviewed.csv: 書式不正 {rk} {ck} {txt!r}")
        state[(i, j)] = dict(text=txt, by="reviewed", reviewer=who, note=note)
    return state


def load_engines(doc_id, ocr_dir, expect_rows, expect_cols, input_path, input_key="pdf_sha256", input_label="PDF"):
    """2つの OCR の JSON を読み、整合を確かめる。-> (data, 入力の sha256)。
    doc_id・格子の大きさと位置・入力の sha256（JSON のキー input_key）が2つで一致すること、ローカルに入力
    （PDF・PNG。input_path）があればその sha が JSON と一致すること。"""
    data = {e: json.load(open(ocr_dir / doc_id / f"{e}.json", encoding="utf-8")) for e in ENGINES}
    for e in ENGINES:
        if data[e]["doc_id"] != doc_id:
            raise ValueError(f"{e}.json の doc_id が違う: {data[e]['doc_id']}")
    ga, gb = data[ENGINES[0]]["grid"], data[ENGINES[1]]["grid"]
    for key in ("rows", "cols"):
        if len(ga[key]) != len(gb[key]):
            raise ValueError(f"2つの JSON の格子（{key}）の数が違う: {len(ga[key])} と {len(gb[key])}")
        for p, q in zip(ga[key], gb[key]):   # 同じ画像から取るので位置も一致するはず
            if max(abs(p[0] - q[0]), abs(p[1] - q[1])) > 2:
                raise ValueError(f"2つの JSON の格子（{key}）が一致しない: {p} {q}")
    if len(ga["rows"]) != expect_rows or len(ga["cols"]) != expect_cols:
        raise ValueError(f"格子が {len(ga['rows'])}行×{len(ga['cols'])}列（期待 {expect_rows}×{expect_cols}）")
    shas = {data[e][input_key] for e in ENGINES}
    if len(shas) != 1:
        raise ValueError(f"2つの JSON の {input_key} が違う: {sorted(shas)}")
    sha = shas.pop()
    if input_path.exists() and common.sha256(input_path) != sha:
        raise ValueError(f"ローカルの {input_label}（{input_path}）の sha256 が JSON の値と違う。{input_label}が更新された？ OCR をやり直す")
    return data, sha


def arith_flag(cons, val, known, evaluate, hint_ok=lambda name: True):
    """確定したセルだけで検算し、疑うセルを絞る。-> (flagged {(行,列): [検算名]}, hints {(行,列): {値}}, touching, stats)。
    touching は キー -> そのキーが入る検算のうち**通ったもの**（空なら裏づけ無し）。
    cons: [(名前, 左辺のキー, 右辺のキー, 種類, 余分なキー)]。キーは (層, 行, 列)。余分なキーは、その検算に入るが
      左右辺ではないセル（比の分母など）。
    val: キー -> 数値、known: 確定したキーの集合。evaluate(lhs, rhs, kind, val) -> True/False/None（None は対象外）。
    hint_ok(名前): 和の検算の示す値を手がかりに使うか。
    疑い候補 = 入る検算がすべて失敗しているキー。最小の組を貪欲法で選ぶ。絞れなければその検算の全キーを疑う。"""
    status, cons_keys, touching = {}, {}, defaultdict(set)   # 検算 -> 成否／検算 -> 入るキー／キー -> 入る検算
    for name, lhs, rhs, kind, extra in cons:
        keys = set(lhs) | {rhs} | set(extra)
        if not keys <= known:
            continue
        ok = evaluate(lhs, rhs, kind, val)
        if ok is None:
            continue
        status[name], cons_keys[name] = ok, keys
        for k in keys:
            touching[k].add(name)
    failed = {n for n, ok in status.items() if not ok}
    hints = defaultdict(set)   # 未確定のセル -> 和の検算が示す値（人が確認するときの手がかり。採用はしない）
    for name, lhs, rhs, kind, _extra in cons:
        if kind != "sum" or not hint_ok(name):
            continue
        missing = [k for k in list(lhs) + [rhs] if k not in known]
        if len(missing) == 1:
            k = missing[0]
            rest = sum(val[x] for x in lhs if x != k)
            hints[(k[1], k[2])].add(int(val[rhs] - rest) if k != rhs else int(rest))
    suspects = {k for k, ns in touching.items() if ns <= failed}
    flagged, remaining = {}, set(failed)
    while remaining:
        best = max(((k, remaining & touching[k]) for k in sorted(suspects) if remaining & touching[k]),
                   key=lambda kv: len(kv[1]), default=None)
        if best is None:
            n = min(remaining)
            picks, cov = sorted(cons_keys[n]), {n}
        else:
            picks, cov = [best[0]], best[1]
        for k in picks:
            flagged.setdefault((k[1], k[2]), set()).update(cov)
        remaining -= cov
    flagged = {c: sorted(ns) for c, ns in flagged.items()}
    passed = {k: ns - failed for k, ns in touching.items()}   # 返す touching は「通った検算」だけ（失敗した検算は裏づけにならない）
    return flagged, hints, passed, dict(failed_constraints=len(failed), evaluated=len(status))
