#!/usr/bin/env python3
"""P1 Maker v2 — biodic_6th_kanagawa_h16 等、罫線が疎な表の再構成専用 Fixer。

診断（P5_triage.md の「B. OCR品質＝テキスト抽出順序破綻」説を実測で検証した結果）:
  誤りだった。extract_text() の行順序そのものは正しい（例: p.41 の
  「大洞沢 1,316 12 481」のように、実際のPDFテキストストリームは行ごとに
  正しい順序で並んでいる）。

  真因は pdfplumber の find_tables()（罫線ベースの表構造検出）が、
  「外枠＋ヘッダ下の1本」程度しか罫線を持たない疎な表で、複数の実データ行
  （例: 7地点）や複数の実データ列（例: 3つの調査日）を、たった1つの
  グリッド行/列に誤って畳み込んでしまうことにある。さらに既存の
  p1_maker.py の clean_cell() が改行を区切り文字なしで除去する
  （"1,316 12 481\n3,424 15 344" → "1,316 12 4813,424 15 344"）ため、
  隣接する行・列の数値が文字列として物理的に連結され、生テキストへの
  literal 一致が構造的に不可能になっていた。

対処:
  pdfplumber の壊れたセルテキストは使わず、ページの単語（extract_words）の
  x0/x1/top 座標を直接クラスタリングして、行アンカー（キー列の単語の行揃え）
  と列アンカー（ヘッダ行の単語のx1揃え）を再構成する。決定論的処理のみ。
  推測は一切行わない。見つからないセルは value_raw=null + unreadable_reason。

対象: --doc で指定した doc_id のみ。他文書には一切触れない。
"""
import sys, re, json, sqlite3, argparse
sys.path.insert(0, "scripts")
import pdfplumber
from common import DB, ROOT, now, to_fiscal_year, to_number

# p1_maker.py の既存ロジックを「壊さず再利用」する（読み取り専用import）
import p1_maker as m

EXTRACTOR = f"pdfplumber-v2@{pdfplumber.__version__}"
ROW_TOL = 4.0      # 同一視覚行とみなす top の許容差(pt)。行間隔(~19-20pt)より十分小さい
COL_TOL = 6.0       # 同一視覚列とみなす x1 の許容差(pt)


def cluster_1d(vals_with_ref, tol):
    """vals_with_ref: [(pos, ref), ...] -> 位置でクラスタリングし、
    [{'center':float, 'refs':[ref,...]}] を昇順(center)で返す。"""
    if not vals_with_ref:
        return []
    order = sorted(vals_with_ref, key=lambda p: p[0])
    clusters = [[order[0]]]
    for v, ref in order[1:]:
        if v - clusters[-1][-1][0] <= tol:
            clusters[-1].append((v, ref))
        else:
            clusters.append([(v, ref)])
    out = []
    for c in clusters:
        vs = [v for v, _ in c]
        out.append({"center": sum(vs) / len(vs), "refs": [r for _, r in c]})
    return out


def words_in_bbox(page, bbox):
    x0, top, x1, bottom = bbox
    x0 = max(0, x0); top = max(0, top)
    x1 = min(page.width, x1); bottom = min(page.height, bottom)
    if x1 <= x0 or bottom <= top:
        return []
    try:
        return page.crop((x0, top, x1, bottom)).extract_words(x_tolerance=2, y_tolerance=3)
    except Exception:
        return []


def needs_reflow(page, grid, header_rows, key_cols, table):
    """既存p1_maker.pyのグリッドが壊れているサインを検出する。
    1) データセルに改行が含まれる(複数実データ行が1グリッド行に畳み込まれた)
    2) ヘッダセル(key_cols以降)のbbox内に単語が2つ以上ある
       (複数実データ列が1グリッド列に畳み込まれた)
    のどちらかがあれば True。"""
    nrows = len(grid)
    for r in range(header_rows, nrows):
        for c, cell in enumerate(grid[r]):
            if cell and "\n" in cell:
                return True
    try:
        header_row_obj = table.rows[0]
    except Exception:
        return False
    for c in range(key_cols, len(header_row_obj.cells)):
        bbox = header_row_obj.cells[c]
        if not bbox:
            continue
        words = words_in_bbox(page, bbox)
        if len(words) > 1:
            return True
    return False


def header_rows_reliable(grid, max_header=3):
    """detect_header_rows()の内部制御フローを厳密に再現し、'早期(i<=max_header)に
    numeric_ratio>=0.4の行が見つかって、そのままの行番号で返った'(信頼できる)場合
    にのみTrueを返す。
    'どの行も条件を満たさずフォールバック値を返した'場合、および
    'max_headerを超えた遠い行がたまたま条件を満たし、min()で切り詰められた'
    場合は、どちらも本来ヘッダ境界の検出に失敗している(=標本一覧表のような
    密なテキスト行がヘッダとして丸ごと誤認識されるモード)ため、Falseとする。"""
    for i, row in enumerate(grid):
        cells = [c for c in row if c not in (None, "")]
        if not cells:
            continue
        numeric_ratio = sum(1 for c in cells if m.looks_numeric(c)) / len(cells)
        if numeric_ratio >= 0.4:
            return i <= max_header
    return False


def key_cols_reliable(grid, header_rows, max_key=4):
    if len(grid) <= header_rows:
        return True
    ncols = len(grid[0])
    data_rows = grid[header_rows:]
    for c in range(ncols):
        colvals = [row[c] for row in data_rows if c < len(row) and row[c] not in (None, "")]
        if not colvals:
            continue
        numeric_ratio = sum(1 for v in colvals if m.looks_numeric(v)) / len(colvals)
        if numeric_ratio >= 0.5:
            return c <= max_key
    return False


BARE_INT_RE = re.compile(r"^\d+$")


def correct_header_rows_overreach(grid, header_rows, key_cols):
    """既知の失敗モード: header_rows が実際より1行多く数えられ、
    最初の実データ行(標本番号のような素の整数連番)がヘッダ領域に
    取り込まれてしまうケースがある(P5_triageの想定と異なり、
    numeric_ratioヒューリスティックが密なテキスト表で誤作動するため)。
    最後のヘッダ行のキー列が素の整数(行番号らしきもの)に見える間、
    header_rows を1つずつ減らす。header_rows を増やす方向には絶対に働かない
    ので、既に正しく動いている表を壊すことはない。"""
    hr = header_rows
    while hr >= 1 and hr <= len(grid):
        row = grid[hr - 1]
        looks_like_data_row = any(
            row[c] is not None and BARE_INT_RE.match(row[c].replace("\n", "").strip())
            for c in range(min(key_cols, len(row)))
        )
        if looks_like_data_row and hr > 1:
            hr -= 1
        else:
            break
    return max(1, hr)


def forward_fill_lookup(clusters, anchor_center):
    """clustersは(位置クラスタ)のリスト。anchor_center以下で最も近いクラスタの
    テキストを返す(縦方向/横方向のラベルの見出しかぶり=rowspan/colspanの代替)。
    該当が1つもクラスタが無い場合はNone。"""
    if not clusters:
        return None
    best = None
    for cl in clusters:
        if cl["center"] <= anchor_center + 1.0:
            if best is None or cl["center"] > best["center"]:
                best = cl
    if best is None:
        # anchorより手前に何もなければ、最も近いクラスタで代用(単一クラスタが
        # ページ全体にまたがるケース、例:単一の分類群ラベルが全行にかかる)
        best = min(clusters, key=lambda cl: abs(cl["center"] - anchor_center))
    return best


def reflow_table(doc_id, doc_sha256, page, page_no, table, raw_text, table_id):
    grid = table.extract()
    if not grid or not grid[0]:
        return [], 0, False
    ncols = max(len(r) for r in grid)
    grid = [r + [None] * (ncols - len(r)) for r in grid]

    header_rows = m.detect_header_rows(grid)
    key_cols = m.detect_key_cols(grid, header_rows)
    header_rows = correct_header_rows_overreach(grid, header_rows, key_cols)

    if not needs_reflow(page, grid, header_rows, key_cols, table):
        recs, unreadable = m.process_table(
            doc_id, doc_sha256, page_no, 0, table, raw_text, table_id
        )
        for rec in recs:
            rec["extractor"] = EXTRACTOR
        return recs, unreadable, False

    # --- ここから word-position ベースの再構成 ---
    try:
        header_bbox_top = table.rows[0].bbox[1]
        header_bbox_bottom = table.rows[header_rows - 1].bbox[3]
    except Exception:
        return [], 0, False

    # 列境界 (header行のセルbboxから; 全行で共通のはず)
    col_x = []  # [(x0,x1), ...] per column index
    ref_row = None
    for r in table.rows:
        if all(c is not None for c in r.cells[:ncols]):
            ref_row = r
            break
    if ref_row is None:
        ref_row = table.rows[0]
    for c in range(ncols):
        cell = ref_row.cells[c] if c < len(ref_row.cells) else None
        if cell:
            col_x.append((cell[0], cell[2]))
        else:
            col_x.append((None, None))

    tbl_x0, tbl_top, tbl_x1, tbl_bottom = table.bbox
    key_col_x1 = None
    for c in range(key_cols):
        if col_x[c][1] is not None:
            key_col_x1 = col_x[c][1] if key_col_x1 is None else max(key_col_x1, col_x[c][1])
    if key_col_x1 is None:
        key_col_x1 = tbl_x0

    data_top = header_bbox_bottom
    data_bottom = tbl_bottom

    # --- 行アンカー: 各キー列の単語をクラスタリングし、最も細かいものをアンカーにする ---
    key_col_clusters = []  # per key col index: cluster list
    for c in range(key_cols):
        x0, x1 = col_x[c]
        if x0 is None:
            key_col_clusters.append([])
            continue
        words = words_in_bbox(page, (x0, data_top, x1, data_bottom))
        items = [(w["top"], w) for w in words]
        key_col_clusters.append(cluster_1d(items, ROW_TOL))

    if not key_col_clusters or all(len(cl) == 0 for cl in key_col_clusters):
        # キー列から何も取れない → 再構成不能。元のprocess_tableに委ねる。
        recs, unreadable = m.process_table(
            doc_id, doc_sha256, page_no, 0, table, raw_text, table_id
        )
        for rec in recs:
            rec["extractor"] = EXTRACTOR
        return recs, unreadable, False

    anchor_idx = max(range(key_cols), key=lambda c: len(key_col_clusters[c]))
    anchor_clusters = key_col_clusters[anchor_idx]

    def cluster_text(cl):
        ws = sorted(cl["refs"], key=lambda w: (round(w["top"], 0), w["x0"]))
        return " ".join(w["text"] for w in ws) if ws else None

    # 既知の失敗モード: 他のキー列のラベルが2行に折り返している場合
    # (例:"横浜川崎地域\n計")、上のクラスタリングだと2つの別クラスタに
    # 分かれてしまい、forward_fill_lookupが片方だけを拾って
    # "計"のような断片ラベルを複数の別グループに誤って使い回してしまう。
    # アンカー行の典型的な行間隔よりずっと近い間隔で隣接するクラスタは、
    # 同じラベルの折り返しとみなして1つに結合する。
    if len(anchor_clusters) >= 2:
        anchor_gaps = sorted(
            anchor_clusters[i + 1]["center"] - anchor_clusters[i]["center"]
            for i in range(len(anchor_clusters) - 1)
        )
        typical_row_gap = anchor_gaps[len(anchor_gaps) // 2]
        for c in range(key_cols):
            if c == anchor_idx:
                continue
            merged = []
            for cl in key_col_clusters[c]:
                if merged and cl["center"] - merged[-1]["center"] < typical_row_gap * 1.5:
                    # center は結合ラベルの「開始位置」(=先に現れた行の位置)を保持する。
                    # forward_fill_lookup は「このcenter以下で最も近いアンカー」を
                    # 探す前方一致方式なので、開始位置を保つことで
                    # ラベルが及ぶ全サブ行(2行目以降)にも正しく転記される。
                    merged[-1] = {
                        "center": merged[-1]["center"],
                        "refs": merged[-1]["refs"] + cl["refs"],
                    }
                else:
                    merged.append(dict(cl))
            key_col_clusters[c] = merged

    row_labels = []  # per subrow: list of label text per key col
    for cl in anchor_clusters:
        labels = [None] * key_cols
        labels[anchor_idx] = cluster_text(cl)
        for c in range(key_cols):
            if c == anchor_idx:
                continue
            other = forward_fill_lookup(key_col_clusters[c], cl["center"])
            labels[c] = cluster_text(other) if other else None
        row_labels.append(labels)

    n_subrows = len(anchor_clusters)
    row_boundaries = []  # (top_bound, bottom_bound) per subrow, using midpoints
    centers = [cl["center"] for cl in anchor_clusters]
    for i in range(n_subrows):
        top_b = data_top if i == 0 else (centers[i - 1] + centers[i]) / 2
        bot_b = data_bottom if i == n_subrows - 1 else (centers[i] + centers[i + 1]) / 2
        row_boundaries.append((top_b, bot_b))

    # 安全弁: ヘッダ領域の単語をtopでクラスタリングし、複数の物理行に
    # 分かれている場合、それが「密な折り返しヘッダ(行間隔が実データ行の
    # 間隔よりずっと狭い、例:仮名/属和名などの2行見出し)」なのか、
    # 「header_bbox_bottomが実データ行を1行以上飲み込んでしまった」のかを
    # 行間隔の比較で判定する。後者ならこのシンプルな
    # 「単一ヘッダ+単一キー列ブロック」モデルでは再構成できないので、
    # 安全側(元のprocess_table、null化)に倒す。
    header_line_words = words_in_bbox(
        page, (key_col_x1, header_bbox_top, tbl_x1, header_bbox_bottom)
    )
    header_line_clusters = cluster_1d(
        [(w["top"], w) for w in header_line_words], ROW_TOL
    )
    if len(header_line_clusters) > 1:
        h_centers = sorted(cl["center"] for cl in header_line_clusters)
        h_gaps = [h_centers[i + 1] - h_centers[i] for i in range(len(h_centers) - 1)]
        if len(centers) >= 2:
            row_gaps = sorted(centers[i + 1] - centers[i] for i in range(len(centers) - 1))
            typical_row_gap = row_gaps[len(row_gaps) // 2]
            header_looks_like_data = max(h_gaps) >= 0.6 * typical_row_gap
        else:
            header_looks_like_data = True  # 行間隔の基準が無く判断できない→安全側
        if header_looks_like_data:
            recs, unreadable = m.process_table(
                doc_id, doc_sha256, page_no, 0, table, raw_text, table_id
            )
            for rec in recs:
                rec["extractor"] = EXTRACTOR
            return recs, unreadable, False

    # --- 列アンカー: ヘッダ行の単語のx1でクラスタリング ---
    header_words = words_in_bbox(page, (key_col_x1, header_bbox_top, tbl_x1, header_bbox_bottom))
    col_items = [(w["x1"], w) for w in header_words]
    col_clusters = cluster_1d(col_items, COL_TOL)
    if not col_clusters:
        recs, unreadable = m.process_table(
            doc_id, doc_sha256, page_no, 0, table, raw_text, table_id
        )
        for rec in recs:
            rec["extractor"] = EXTRACTOR
        return recs, unreadable, False

    def col_label(cl):
        ws = sorted(cl["refs"], key=lambda w: w["x0"])
        return "".join(w["text"] for w in ws) if len(ws) == 1 else " ".join(w["text"] for w in ws)

    col_labels = [col_label(cl) for cl in col_clusters]
    col_anchors = [cl["center"] for cl in col_clusters]

    # 安全弁: ヘッダラベルに6桁以上の連続した数字(標本番号のようなID)が
    # 混入していたら、ヘッダ/データ境界の検出そのものが破綻しているサイン。
    # 無理に使わず元のprocess_table(安全側=null化)に委ねる。
    if any(re.search(r"\d{6,}", lbl or "") for lbl in col_labels):
        recs, unreadable = m.process_table(
            doc_id, doc_sha256, page_no, 0, table, raw_text, table_id
        )
        for rec in recs:
            rec["extractor"] = EXTRACTOR
        return recs, unreadable, False

    # --- データ領域の単語を (行, 列) にビニング ---
    data_words = words_in_bbox(page, (key_col_x1, data_top, tbl_x1, data_bottom))
    bins = {}  # (row_i, col_j) -> [word, ...]
    for w in data_words:
        # 行: 境界に基づいて割り当て
        ri = None
        for i, (tb, bb) in enumerate(row_boundaries):
            if tb <= w["top"] < bb or (i == n_subrows - 1 and w["top"] <= bb):
                ri = i
                break
        if ri is None:
            continue
        cj = min(range(len(col_anchors)), key=lambda j: abs(w["x1"] - col_anchors[j]))
        bins.setdefault((ri, cj), []).append(w)

    records = []
    unreadable = 0
    for i in range(n_subrows):
        row_key = m.dedupe_join(row_labels[i])
        for cj, col_key in enumerate(col_labels):
            ws = bins.get((i, cj), [])
            value_raw_display = None
            if ws:
                ws_sorted = sorted(ws, key=lambda w: w["x0"])
                value_raw_display = " ".join(w["text"] for w in ws_sorted).strip() or None

            bbox_out = None
            if ws:
                x0s = [w["x0"] for w in ws]; x1s = [w["x1"] for w in ws]
                t0s = [w["top"] for w in ws]; b0s = [w["bottom"] for w in ws]
                bbox_out = [round(min(x0s), 1), round(min(t0s), 1), round(max(x1s), 1), round(max(b0s), 1)]

            rec = {
                "doc_id": doc_id, "doc_sha256": doc_sha256, "page_no": page_no,
                "table_id": table_id, "row_key": row_key, "col_key": col_key,
                "value_raw": None, "value": None, "value_type": None, "unit": None,
                "fiscal_year": None, "era_raw": None,
                "source_text": None, "source_bbox": json.dumps(bbox_out) if bbox_out else None,
                "notes_ref": None,
                "is_total": 1 if (m.is_total_key(row_key) or m.is_total_key(col_key)) else 0,
                "merged": 1, "unreadable_reason": None,
                "confidence": None, "extractor": EXTRACTOR, "verified_by": None,
                "extracted_at": now(),
            }

            if value_raw_display is None:
                records.append(rec)
                continue

            span = m.literal_search(raw_text, value_raw_display)
            if span is None:
                rec["unreadable_reason"] = (
                    f"cell_text_not_found_in_page_rawtext(v2_reflow): {value_raw_display!r}"
                )
                unreadable += 1
                records.append(rec)
                continue

            rec["value_raw"] = value_raw_display
            rec["source_text"] = m.make_source_text(raw_text, span)
            val, vtype = to_number(value_raw_display)
            rec["value"] = json.dumps(val) if not isinstance(val, (int, float, type(None))) else val
            rec["value_type"] = vtype
            blob = "|".join([str(row_key or ""), str(col_key or "")])
            rec["unit"] = m.find_unit(blob)
            era_raw, fy = m.extract_era(row_key or "")
            if fy is None:
                era_raw2, fy2 = m.extract_era(col_key or "")
                era_raw, fy = era_raw2, fy2
            rec["era_raw"] = era_raw
            rec["fiscal_year"] = fy
            records.append(rec)

    return records, unreadable, True


def run(doc_id, verbose=True):
    con = sqlite3.connect(DB / "cells.sqlite", timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()

    # superseded列がなければ追加(スキーマ拡張のみ。既存行のデータは変更しない)
    cols = [r[1] for r in cur.execute("PRAGMA table_info(cells)").fetchall()]
    if "superseded" not in cols:
        cur.execute("ALTER TABLE cells ADD COLUMN superseded INTEGER DEFAULT 0")
        con.commit()

    row = cur.execute(
        "SELECT doc_id, doc_sha256, local_path FROM documents WHERE doc_id=?", (doc_id,)
    ).fetchone()
    if not row:
        print(f"[error] doc_id not found: {doc_id}")
        return
    _, doc_sha256, local_path = row
    path = ROOT / local_path

    # 旧行(pdfplumber@版)を superseded=1 にする(削除しない)
    old_extractor = m.EXTRACTOR
    n_old = cur.execute(
        "SELECT COUNT(*) FROM cells WHERE doc_id=? AND extractor=?", (doc_id, old_extractor)
    ).fetchone()[0]
    cur.execute(
        "UPDATE cells SET superseded=1 WHERE doc_id=? AND extractor=?", (doc_id, old_extractor)
    )
    # v2で過去に投入した行があれば(再実行の冪等性)削除して作り直す
    cur.execute("DELETE FROM cells WHERE doc_id=? AND extractor=?", (doc_id, EXTRACTOR))
    con.commit()

    total_tables = total_cells = total_unreadable = total_reflowed_tables = 0
    with pdfplumber.open(str(path)) as pdf:
        for page_no0, page in enumerate(pdf.pages):
            page_no = page_no0 + 1
            try:
                tables = page.find_tables()
            except Exception as e:
                print(f"  [error] p{page_no}: find_tables failed: {e}")
                continue
            if not tables:
                continue
            raw_text = page.extract_text() or ""
            for ti, table in enumerate(tables):
                table_id = f"p{page_no}_t{ti+1}"
                try:
                    records, unreadable, was_reflowed = reflow_table(
                        doc_id, doc_sha256, page, page_no, table, raw_text, table_id
                    )
                except Exception as e:
                    print(f"  [error] p{page_no} t{ti+1}: {e}")
                    continue
                if not records:
                    continue
                total_tables += 1
                total_cells += len(records)
                total_unreadable += unreadable
                if was_reflowed:
                    total_reflowed_tables += 1
                for rec in records:
                    cur.execute(
                        """INSERT INTO cells
                        (doc_id, doc_sha256, page_no, table_id, row_key, col_key,
                         value_raw, value, value_type, unit, fiscal_year, era_raw,
                         source_text, source_bbox, notes_ref, is_total, merged,
                         unreadable_reason, confidence, extractor, verified_by, extracted_at,
                         superseded)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
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

    cur.execute(
        "INSERT INTO extraction_log (ts, doc_id, page_no, table_id, role, attempt, verdict, failures, note) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (now(), doc_id, None, None, "maker_v2", 1, "done", "[]",
         json.dumps({
             "old_extractor": old_extractor, "old_rows_superseded": n_old,
             "new_extractor": EXTRACTOR, "new_rows": total_cells,
             "new_unreadable": total_unreadable, "tables": total_tables,
             "tables_reflowed": total_reflowed_tables,
             "note": "旧行はDELETEせずsuperseded=1に更新。新行をextractor=pdfplumber-v2として追加。",
         }, ensure_ascii=False)),
    )
    con.commit()
    con.close()
    print(f"\n[{doc_id}] tables={total_tables} (reflowed={total_reflowed_tables}) "
          f"cells={total_cells} unreadable={total_unreadable} "
          f"old_rows_superseded={n_old}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", required=True)
    args = ap.parse_args()
    run(args.doc)
