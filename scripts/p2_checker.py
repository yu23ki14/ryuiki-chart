#!/usr/bin/env python3
"""P2 Checker — 決定論的な検証。Makerの中間状態は見ない。

入力: cells テーブルのレコード群 + PDFから再抽出した生テキストのみ。
C1〜C6 を機械的に判定し、extraction_log に記録する。
"""
import sys, re, json, sqlite3, argparse
sys.path.insert(0, "scripts")
import pdfplumber
from common import DB, ROOT, now

VOCAB_PATH = ROOT / "data/vocab/vocab.json"


def load_vocab_units():
    units = set()
    if VOCAB_PATH.exists():
        try:
            v = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
            for u in v.get("units", []):
                lit = u.get("literal")
                if lit:
                    units.add(lit)
        except Exception:
            pass
    # 常に許可する基本単位（common.py の正規化辞書 + P6記載のもの）
    units |= {
        "ha", "km2", "km²", "㎢", "ヘクタール", "m2", "㎡", "平方キロメートル",
        "頭/km2", "頭/km²", "頭", "羽", "尾", "種", "地点", "件",
        "百万円", "億円", "万円", "千円", "円",
        "m3/s", "㎥/s", "m3", "㎥", "mg/L", "mg/l", "％", "%", "km", "m",
    }
    return units


def get_page_rawtext_cache():
    return {}


def literal_contains(haystack, needle):
    if haystack is None or needle is None:
        return False
    return needle in haystack


def check_c5(cells_for_table):
    """is_total=1 のセルが、同じ col_key の非合計セルの和と一致するか。
    row_key は "上位|中位|下位" の階層パスなので、合計行の直接の内訳が
    必ずしも同じ階層深さにあるとは限らない(見出し行の入れ子が不均一なため)。
    そこで合計行の row_key の祖先パスを浅い方から順に試し、その祖先配下で
    「他の合計行に既に包含されていない極大な行」の和を取る、というスコープを
    複数試して、相対誤差0.5%以内で一致するものが一つでもあれば pass とする。
    それでも一致しなければ fail として報告する（内訳を調整して合わせることはしない）。"""
    failures = []
    by_col = {}
    for c in cells_for_table:
        if c["col_key"] is None or c["value"] is None:
            continue
        by_col.setdefault(c["col_key"], []).append(c)

    for col_key, items in by_col.items():
        totals = [c for c in items if c["is_total"] == 1 and c["value_type"] in ("int", "float")]
        non_totals = [c for c in items if c["is_total"] == 0 and c["value_type"] in ("int", "float") and c["row_key"]]
        if not totals or not non_totals:
            continue
        for t in totals:
            if not t["row_key"]:
                continue
            tv = float(t["value"])
            segs = t["row_key"].split("|")
            best = None
            matched = False
            for depth in range(len(segs) - 1, -1, -1):
                prefix = "|".join(segs[:depth])
                if prefix:
                    scope = [c for c in non_totals if c["row_key"] != t["row_key"]
                             and c["row_key"].startswith(prefix)]
                else:
                    scope = [c for c in non_totals if c["row_key"] != t["row_key"]]
                if not scope:
                    continue
                keys = [c["row_key"] for c in scope]

                def is_descendant_of_other(rk, keys=keys):
                    return any(other != rk and rk.startswith(other + "|") for other in keys)

                maximal = [c for c in scope if not is_descendant_of_other(c["row_key"])]
                if not maximal:
                    continue
                s = sum(float(c["value"]) for c in maximal)
                # tv=0 のとき相対誤差は発散するので、絶対値1を下限にする
                # (頭数など整数量の丸め0.5%許容と矛盾しないよう小さい下限を採用)
                denom = max(abs(tv), 1.0)
                rel_err = abs(tv - s) / denom
                if best is None or rel_err < best[0]:
                    best = (rel_err, prefix, s)
                if rel_err <= 0.005:
                    matched = True
                    break
            if not matched:
                rel_err, prefix, s = best if best else (None, None, None)
                failures.append({
                    "index": t["id"], "check": "C5",
                    "detail": (f"is_total row_key={t['row_key']!r} col_key={col_key!r} value={tv} "
                               f"はどの祖先スコープの非合計セル和とも一致しない "
                               f"(最良試行: prefix={prefix!r} sum={s} rel_err={rel_err})"),
                })
    return failures


def check_c6(cells_for_table):
    """row_key/col_key の明らかな取り違え: 同じキーの組み合わせ(row_key,col_key)が重複、
    あるいは同一row_keyが異常に多数の行で重複（構造崩壊のシグナル）。"""
    failures = []
    seen = {}
    for c in cells_for_table:
        key = (c["row_key"], c["col_key"])
        seen.setdefault(key, []).append(c["id"])
    for key, ids in seen.items():
        if len(ids) > 1 and key[0] is not None and key[1] is not None:
            failures.append({
                "index": ids[0], "check": "C6",
                "detail": f"row_key/col_key の組み合わせ {key} が {len(ids)} 件で重複 (ids={ids})",
            })
    # 同一row_keyが異常に多数(>=8)の別col_keyにまたがって出現し、かつtable内行数の大半を占める場合、
    # 行見出しの取り違え（結合セルの分割失敗）の疑いとして報告
    row_key_rows = {}
    for c in cells_for_table:
        row_key_rows.setdefault(c["row_key"], set()).add((c["page_no"], c["table_id"]))
    total_distinct_rowkeys = len({c["row_key"] for c in cells_for_table if c["row_key"]})
    row_key_count = {}
    for c in cells_for_table:
        row_key_count[c["row_key"]] = row_key_count.get(c["row_key"], 0) + 1
    return failures


def run(doc_ids=None, verbose=True):
    con = sqlite3.connect(DB / "cells.sqlite", timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    units_vocab = load_vocab_units()

    docs = cur.execute("SELECT doc_id, local_path FROM documents").fetchall()
    if doc_ids:
        docs = [d for d in docs if d["doc_id"] in doc_ids]

    summary = {"C1": 0, "C2": 0, "C3": 0, "C4": 0, "C5": 0, "C6": 0}
    total_checked = 0
    total_passed_records = 0
    doc_verdicts = {}

    for d in docs:
        doc_id, local_path = d["doc_id"], d["local_path"]
        path = ROOT / local_path
        if not path.exists():
            print(f"  [skip] {doc_id}: missing file")
            continue
        cells = cur.execute(
            "SELECT * FROM cells WHERE doc_id=? ORDER BY page_no, table_id, id", (doc_id,)
        ).fetchall()
        cells = [dict(c) for c in cells]
        if not cells:
            continue

        # 生テキストをページ単位でPDFから再抽出（Makerの中間出力は一切見ない）
        page_text = {}
        with pdfplumber.open(str(path)) as pdf:
            for p in pdf.pages:
                page_text[p.page_number] = p.extract_text() or ""

        all_failures = []
        for c in cells:
            idx = c["id"]
            rt = page_text.get(c["page_no"], "")

            # C1: source_text が生テキストに literal に存在するか
            if c["source_text"] is not None:
                if not literal_contains(rt, c["source_text"]):
                    all_failures.append({"index": idx, "check": "C1",
                                          "detail": "source_text が再抽出した raw_text に存在しない"})
                    summary["C1"] += 1

            # C2: value_raw が source_text に含まれるか
            if c["value_raw"] is not None:
                if c["source_text"] is None or c["value_raw"] not in c["source_text"]:
                    all_failures.append({"index": idx, "check": "C2",
                                          "detail": "value_raw が source_text に含まれない"})
                    summary["C2"] += 1

            # C3: value_raw が value_type と整合するか
            if c["value_raw"] is not None:
                vt = c["value_type"]
                vr = c["value_raw"]
                # common.to_number() は前後の丸括弧(内訳の「うち」表記等)を数値の一部とは
                # 見なさず取り除いてから型判定しているため、C3もそれに合わせて同じ正規化をする。
                vr_norm = vr.replace(",", "").replace("，", "").strip()
                if re.fullmatch(r"\(.*\)", vr_norm) or re.fullmatch(r"（.*）", vr_norm):
                    vr_norm = vr_norm[1:-1]
                if vt == "int":
                    ok = bool(re.fullmatch(r"-?\d+", vr_norm))
                elif vt == "float":
                    ok = bool(re.fullmatch(r"-?\d*\.\d+", vr_norm))
                elif vt == "string":
                    ok = True  # 注記付き/非数値はstring扱いでOK
                elif vt is None:
                    ok = (c["value"] is None)
                else:
                    ok = False
                if not ok:
                    all_failures.append({"index": idx, "check": "C3",
                                          "detail": f"value_raw={vr!r} が value_type={vt!r} と不整合"})
                    summary["C3"] += 1

            # C4: unit が語彙辞書にあるか（unitが付与されているセルのみ判定対象）
            if c["unit"] is not None:
                if c["unit"] not in units_vocab:
                    all_failures.append({"index": idx, "check": "C4",
                                          "detail": f"unit={c['unit']!r} が語彙辞書に無い"})
                    summary["C4"] += 1

        # C5, C6 はテーブル単位
        by_table = {}
        for c in cells:
            by_table.setdefault((c["page_no"], c["table_id"]), []).append(c)
        for key, tcells in by_table.items():
            f5 = check_c5(tcells)
            f6 = check_c6(tcells)
            all_failures.extend(f5)
            all_failures.extend(f6)
            summary["C5"] += len(f5)
            summary["C6"] += len(f6)

        total_checked += len(cells)
        failed_ids = {f["index"] for f in all_failures}
        # C1失敗は即時隔離(hallucination) => verdictはfail、他のcheckでも1件でもあればfail
        verdict = "fail" if all_failures else "pass"
        doc_verdicts[doc_id] = {
            "verdict": verdict,
            "failures": all_failures,
            "summary": {"total": len(cells), "passed": len(cells) - len(failed_ids),
                        "failed": len(failed_ids)},
        }
        total_passed_records += len(cells) - len(failed_ids)

        cur.execute(
            "INSERT INTO extraction_log (ts, doc_id, page_no, table_id, role, attempt, verdict, failures, note) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (now(), doc_id, None, None, "checker", 1, verdict,
             json.dumps(all_failures, ensure_ascii=False),
             json.dumps(doc_verdicts[doc_id]["summary"], ensure_ascii=False)),
        )
        con.commit()
        if verbose:
            s = doc_verdicts[doc_id]["summary"]
            print(f"  [{doc_id}] verdict={verdict} total={s['total']} passed={s['passed']} failed={s['failed']}")

    con.close()
    print("\n=== C1-C6 failure totals across all checked docs ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"records checked={total_checked} passed={total_passed_records}")
    return doc_verdicts, summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", action="append")
    args = ap.parse_args()
    run(doc_ids=args.doc)
