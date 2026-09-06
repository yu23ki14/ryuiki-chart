#!/usr/bin/env python3
"""P1 Maker — 決定論的な表抽出 (pdfplumber). LLMは使わない。

1呼び出し=1表の精神を、コードのループで機械的に実施する。
source_text は生テキストからの literal 部分文字列を検索して切り出すのみ。
見つからなければ value_raw を null にし、unreadable_reason に理由を残す。
"""
import sys, re, json, sqlite3, argparse
sys.path.insert(0, "scripts")
import pdfplumber
from common import DB, ROOT, now, to_fiscal_year, to_number

EXTRACTOR = f"pdfplumber@{pdfplumber.__version__}"
VOCAB_VERSION = "v1"

TOTAL_PATTERNS = [
    re.compile(r"^(合計|総計|小計)"),
    re.compile(r"^計[\s(（]"),
    re.compile(r"^計$"),
    re.compile(r"計\.$"),
]

UNIT_TOKENS = [
    "km2", "km²", "㎢", "ha", "ヘクタール", "m2", "㎡", "平方キロメートル",
    "頭/km2", "頭/km²", "頭", "羽", "尾", "種", "地点", "件",
    "百万円", "億円", "万円", "千円", "円",
    "m3/s", "㎥/s", "m3", "㎥", "mg/L", "mg/l",
    "％", "%", "km", "m",
]

NUMERIC_RE = re.compile(r"^[\-‐―－0-9,，.\s％%]+$")


def is_total_key(key):
    if not key:
        return False
    for seg in key.split("|"):
        seg = seg.strip()
        if not seg:
            continue
        for pat in TOTAL_PATTERNS:
            if pat.search(seg):
                return True
    return False


def looks_numeric(s):
    if s is None:
        return False
    s = s.strip()
    if s == "":
        return False
    if s in ("－", "―", "-", "‐", "・", "…", "n.d.", "N.D.", "NA"):
        return True  # counts as a "data-like" cell (explicit non-value marker)
    return bool(NUMERIC_RE.match(s)) or bool(re.search(r"\d", s) and len(s) <= 12)


def detect_header_rows(grid, max_header=3):
    n = len(grid)
    if n == 0:
        return 1
    for i, row in enumerate(grid):
        cells = [c for c in row if c not in (None, "")]
        if not cells:
            continue
        numeric_ratio = sum(1 for c in cells if looks_numeric(c)) / len(cells)
        if numeric_ratio >= 0.4:
            return max(1, min(i, max_header))
    return min(max(1, n - 1), max_header)


def detect_key_cols(grid, header_rows, max_key=4):
    if len(grid) <= header_rows:
        return 1
    ncols = len(grid[0])
    data_rows = grid[header_rows:]
    for c in range(ncols):
        colvals = [row[c] for row in data_rows if c < len(row) and row[c] not in (None, "")]
        if not colvals:
            continue
        numeric_ratio = sum(1 for v in colvals if looks_numeric(v)) / len(colvals)
        if numeric_ratio >= 0.5:
            return max(1, min(c, max_key))
    return min(max(1, ncols - 1), max_key)


def clean_cell(text):
    if text is None:
        return None
    t = text.replace("\n", "").strip()
    return t if t else None


def forward_fill_column(grid, col, start_row, end_row):
    """None を、同じ列の直近上にある非Noneで埋める（縦方向の結合セル展開）。
    返り値: {row_index: (value, was_filled)}"""
    out = {}
    last = None
    for r in range(start_row, end_row):
        v = clean_cell(grid[r][col]) if col < len(grid[r]) else None
        if v is not None:
            last = v
            out[r] = (v, False)
        else:
            out[r] = (last, True) if last is not None else (None, False)
    return out


def forward_fill_row(row, start_col, end_col):
    """None を、同じ行の直近左にある非Noneで埋める（横方向の結合ヘッダ展開）。"""
    out = {}
    last = None
    for c in range(start_col, end_col):
        v = clean_cell(row[c]) if c < len(row) else None
        if v is not None:
            last = v
            out[c] = (v, False)
        else:
            out[c] = (last, True) if last is not None else (None, False)
    return out


def dedupe_join(parts):
    seen_last = None
    out = []
    for p in parts:
        if p is None or p == "":
            continue
        if p == seen_last:
            continue
        out.append(p)
        seen_last = p
    return "|".join(out) if out else None


def find_unit(text_blob):
    if not text_blob:
        return None
    for tok in UNIT_TOKENS:
        if tok in text_blob:
            return tok
    return None


def literal_search(raw_text, needle):
    """needle を raw_text から探す。まず完全一致、駄目なら空白許容の正規表現。
    見つかれば (start, end, matched_substring) を返す。見つからなければ None。"""
    if not needle:
        return None
    idx = raw_text.find(needle)
    if idx >= 0:
        return idx, idx + len(needle), raw_text[idx:idx + len(needle)]
    # 空白/改行を許容した文字単位マッチ（文字自体は変えない。literal照合の緩和のみ）
    pattern = r"\s*".join(re.escape(ch) for ch in needle if not ch.isspace())
    if not pattern:
        return None
    m = re.search(pattern, raw_text)
    if m:
        return m.start(), m.end(), raw_text[m.start():m.end()]
    return None


def make_source_text(raw_text, span, min_ctx=10, max_ctx=40):
    start, end, _ = span
    ctx = 25
    s = max(0, start - ctx)
    e = min(len(raw_text), end + ctx)
    snippet = raw_text[s:e]
    # 前後合わせて40文字超なら詰める
    while len(snippet) > (end - start) + max_ctx and (s < start or e > end):
        if s < start:
            s += 1
        if e > end and len(snippet) > (end - start) + max_ctx:
            e -= 1
        snippet = raw_text[s:e]
    return snippet


ERA_PAT = re.compile(r"(令和|平成|昭和|R|H|S)\s*(元|\d{1,2})\s*(年度|年|)")


def extract_era(text):
    if not text:
        return None, None
    for seg in text.split("|"):
        m = ERA_PAT.search(seg)
        if m:
            raw = m.group(0)
            fy = to_fiscal_year(raw)
            if fy:
                return raw, fy
    m = re.search(r"(19|20)\d{2}", text)
    if m:
        return m.group(0), int(m.group(0))
    return None, None


def process_table(doc_id, doc_sha256, page_no, table_idx, table, raw_text, table_id_prefix):
    grid = table.extract()
    if not grid or not grid[0]:
        return [], 0
    ncols = max(len(r) for r in grid)
    grid = [r + [None] * (ncols - len(r)) for r in grid]
    nrows = len(grid)

    header_rows = detect_header_rows(grid)
    key_cols = detect_key_cols(grid, header_rows)
    table_id = f"{table_id_prefix}"

    # forward-fill header rows (left fill) for columns >= key_cols
    header_fill = {}  # (r,c) -> (val, filled)
    for r in range(header_rows):
        header_fill[r] = forward_fill_row(grid[r], key_cols, ncols)

    # forward-fill key columns (up/down fill) for rows >= header_rows
    keycol_fill = {}  # c -> {r: (val, filled)}
    for c in range(key_cols):
        keycol_fill[c] = forward_fill_column(grid, c, header_rows, nrows)

    records = []
    unreadable = 0
    for r in range(header_rows, nrows):
        # row_key
        row_parts = []
        for c in range(key_cols):
            v, filled = keycol_fill[c].get(r, (None, False))
            row_parts.append(v)
        row_key = dedupe_join(row_parts)
        row_merged = any(keycol_fill[c].get(r, (None, False))[1] for c in range(key_cols))

        for c in range(key_cols, ncols):
            col_parts = []
            col_merged = False
            for hr in range(header_rows):
                v, filled = header_fill[hr].get(c, (None, False))
                col_parts.append(v)
                col_merged = col_merged or filled
            col_key = dedupe_join(col_parts)

            raw_cell = grid[r][c] if c < len(grid[r]) else None
            value_raw_display = clean_cell(raw_cell)
            cell_merged = 1 if (row_merged or col_merged) else 0

            rec = {
                "doc_id": doc_id, "doc_sha256": doc_sha256, "page_no": page_no,
                "table_id": table_id, "row_key": row_key, "col_key": col_key,
                "value_raw": None, "value": None, "value_type": None, "unit": None,
                "fiscal_year": None, "era_raw": None,
                "source_text": None, "source_bbox": None, "notes_ref": None,
                "is_total": 1 if (is_total_key(row_key) or is_total_key(col_key)) else 0,
                "merged": cell_merged, "unreadable_reason": None,
                "confidence": None, "extractor": EXTRACTOR, "verified_by": None,
                "extracted_at": now(),
            }

            bbox = None
            try:
                cellbbox = table.rows[r].cells[c] if c < len(table.rows[r].cells) else None
                if cellbbox:
                    bbox = [round(x, 1) for x in cellbbox]
            except Exception:
                bbox = None
            rec["source_bbox"] = json.dumps(bbox) if bbox else None

            if value_raw_display is None:
                # 真の空欄。raw_text照合は不要。
                records.append(rec)
                continue

            span = literal_search(raw_text, value_raw_display)
            if span is None:
                # value_rawの完全一致が見つからない -> 推測で埋めない。null化。
                rec["unreadable_reason"] = (
                    f"cell_text_not_found_in_page_rawtext: {value_raw_display!r}"
                )
                unreadable += 1
                records.append(rec)
                continue

            rec["value_raw"] = value_raw_display
            rec["source_text"] = make_source_text(raw_text, span)
            val, vtype = to_number(value_raw_display)
            rec["value"] = json.dumps(val) if not isinstance(val, (int, float, type(None))) else val
            rec["value_type"] = vtype
            blob = "|".join([str(row_key or ""), str(col_key or "")])
            rec["unit"] = find_unit(blob)
            era_raw, fy = extract_era(row_key or "")
            if fy is None:
                era_raw2, fy2 = extract_era(col_key or "")
                era_raw, fy = era_raw2, fy2
            rec["era_raw"] = era_raw
            rec["fiscal_year"] = fy
            records.append(rec)
    return records, unreadable


def run(doc_ids=None, verbose=True):
    con = sqlite3.connect(DB / "cells.sqlite", timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()
    rows = cur.execute("SELECT doc_id, doc_sha256, local_path FROM documents").fetchall()
    if doc_ids:
        rows = [r for r in rows if r[0] in doc_ids]

    total_tables = 0
    total_cells = 0
    total_unreadable = 0
    per_doc = {}

    for doc_id, doc_sha256, local_path in rows:
        path = ROOT / local_path if not str(local_path).startswith("/") else pathlib_fix(local_path)
        if not path.exists():
            print(f"  [skip] {doc_id}: file not found at {local_path}")
            continue
        # idempotency: 同一 doc_sha256+extractor+vocab_version の既存セルは削除して作り直す
        cur.execute(
            "DELETE FROM cells WHERE doc_id=? AND extractor=?", (doc_id, EXTRACTOR)
        )
        doc_tables = 0
        doc_cells = 0
        doc_unreadable = 0
        with pdfplumber.open(str(path)) as pdf:
            for page_no0, page in enumerate(pdf.pages):
                page_no = page_no0 + 1
                try:
                    tables = page.find_tables()
                except Exception as e:
                    print(f"  [error] {doc_id} p{page_no}: find_tables failed: {e}")
                    continue
                if not tables:
                    continue
                raw_text = page.extract_text() or ""
                for ti, table in enumerate(tables):
                    table_id = f"p{page_no}_t{ti+1}"
                    try:
                        records, unreadable = process_table(
                            doc_id, doc_sha256, page_no, ti, table, raw_text, table_id
                        )
                    except Exception as e:
                        print(f"  [error] {doc_id} p{page_no} t{ti+1}: {e}")
                        continue
                    if not records:
                        continue
                    doc_tables += 1
                    doc_cells += len(records)
                    doc_unreadable += unreadable
                    for rec in records:
                        cur.execute(
                            """INSERT INTO cells
                            (doc_id, doc_sha256, page_no, table_id, row_key, col_key,
                             value_raw, value, value_type, unit, fiscal_year, era_raw,
                             source_text, source_bbox, notes_ref, is_total, merged,
                             unreadable_reason, confidence, extractor, verified_by, extracted_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (
                                rec["doc_id"], rec["doc_sha256"], rec["page_no"], rec["table_id"],
                                rec["row_key"], rec["col_key"], rec["value_raw"],
                                rec["value"], rec["value_type"], rec["unit"],
                                rec["fiscal_year"], rec["era_raw"], rec["source_text"],
                                rec["source_bbox"], rec["notes_ref"], rec["is_total"],
                                rec["merged"], rec["unreadable_reason"], rec["confidence"],
                                rec["extractor"], rec["verified_by"], rec["extracted_at"],
                            ),
                        )
        con.commit()
        per_doc[doc_id] = (doc_tables, doc_cells, doc_unreadable)
        total_tables += doc_tables
        total_cells += doc_cells
        total_unreadable += doc_unreadable
        if verbose:
            print(f"  [{doc_id}] tables={doc_tables} cells={doc_cells} unreadable={doc_unreadable}")

    con.close()
    print(f"\nTOTAL: docs={len(per_doc)} tables={total_tables} cells={total_cells} unreadable={total_unreadable}")
    return per_doc


import pathlib
def pathlib_fix(p):
    return pathlib.Path(p)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", action="append", help="限定するdoc_id(複数可)")
    args = ap.parse_args()
    run(doc_ids=args.doc)
