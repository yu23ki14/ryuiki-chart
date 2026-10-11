"""c100b（マングース捕獲数の OCR JSON -> cells）のテスト。コミット済みの OCR の JSON（data/ocr/mongoose/）と、目で読んだ
正解 CSV（scripts/tests/fixtures/mongoose/I2b_mongoose_r4.csv）だけを使う。OCR のライブラリも DB も要らない。
評価シートとの突き合わせは PDF（data/raw/amami_doc/mon_a-4-j.pdf。gitignore 済み）が無ければ skip する。"""
import csv
import json
import pathlib
import shutil
import sqlite3

import pytest

import c100b_mongoose_cells as c
import doccells

HERE = pathlib.Path(__file__).parent
GT_CSV = HERE / "fixtures" / "mongoose" / "I2b_mongoose_r4.csv"
SHEET = c.ROOT / c.SHEET_PDF
needs_sheet = pytest.mark.skipif(not SHEET.exists(), reason="評価シートの PDF が無い（CI の最小環境）")


def gt_matrix():
    rows = list(csv.reader(open(GT_CSV, encoding="utf-8")))[1:]
    assert len(rows) == c.NROW and all(len(r) == c.NCOL + 1 for r in rows)
    return [[c.norm(x) for x in r[1:]] for r in rows]


def grid_of(built):
    """cells の行 -> (PNG の向き〔24行×5列〕の原表の表記の行列、未採用セルの集合)"""
    got = {(r["row_key"], r["col_key"]): r for r in built["rows"]}
    mat, unread = [], set()
    for i, ck in enumerate(c.COL_KEYS):
        row = []
        for j, rk in enumerate(c.ROW_KEYS):
            r = got[(rk, ck)]
            if r["unreadable_reason"]:
                unread.add((i, j))
            row.append(c.norm(r["value_raw"] or ""))
        mat.append(row)
    return mat, unread


def copy_ocr(tmp_path, with_reviewed):
    tmp_path.mkdir(parents=True, exist_ok=True)
    shutil.copytree(c.OCR_DIR / c.DOC_ID, tmp_path / c.DOC_ID)
    if not with_reviewed and (tmp_path / c.DOC_ID / "reviewed.csv").exists():
        (tmp_path / c.DOC_ID / "reviewed.csv").unlink()
    return tmp_path


def _mutate(tmp_path, engine, fn):
    root = tmp_path if (tmp_path / c.DOC_ID).exists() else copy_ocr(tmp_path, with_reviewed=True)
    p = root / c.DOC_ID / f"{engine}.json"
    d = json.load(open(p, encoding="utf-8"))
    fn(d)
    json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    return root


def _cell_boxes(d, row, col):
    g = d["grid"]
    (y0, y1), (x0, x1) = g["rows"][row], g["cols"][col]
    return [b for b in d["boxes"] if x0 <= (b["x0"] + b["x1"]) / 2 <= x1 and y0 - 1 <= (b["y0"] + b["y1"]) / 2 <= y1 + 1]


def _set_cell(d, row, col, text):
    hit = _cell_boxes(d, row, col)
    assert len(hit) == 1
    hit[0]["text"] = text


def _build(root, sheet=None):
    return c.build(root, sheet_pdf=sheet)


def _by(b):
    return {(r["row_key"], r["col_key"]): r for r in b["rows"]}


# ------------------------------------------------------------ 受け入れ基準
def test_every_cell_matches_ground_truth():
    """受け入れ基準: 人の確認（reviewed.csv）まで通した出力が、正解の 24行×5列の全部と一致する。未採用のセルは無い。"""
    b = c.build()
    mat, unread = grid_of(b)
    assert not unread
    assert mat == gt_matrix()
    assert b["stats"]["failed_constraints"] == 0 and b["stats"]["unreadable"] == 0


def test_without_review_no_silent_errors(tmp_path):
    """人の確認が無いと、食い違いのセルは未採用になる。採用したセルは全部正解と一致する（黙った誤りが無い）。"""
    b = _build(copy_ocr(tmp_path, with_reviewed=False))
    mat, unread = grid_of(b)
    gt = gt_matrix()
    for i, row in enumerate(mat):
        for j, v in enumerate(row):
            if (i, j) not in unread:
                assert v == gt[i][j], (i, j)
    reviewed = c.cellmatch.load_reviewed(c.OCR_DIR / c.DOC_ID / "reviewed.csv", c.norm)
    assert unread == {(c.COL_KEYS.index(ck), c.ROW_KEYS.index(rk)) for rk, ck in reviewed}   # reviewed.csv の集合と一致（無ければ空）
    for r in b["rows"]:
        if r["unreadable_reason"]:
            assert r["unreadable_reason"].startswith("ocr_disagree:")
            assert r["value_raw"] is None and r["value"] is None and r["verified_by"] is None and r["confidence"] is None


# ------------------------------------------------------------ 変異（黙って通らない）
def test_disagreement_is_flagged_not_adopted(tmp_path):
    root = _mutate(tmp_path, "paddle", lambda d: _set_cell(d, 5, c.J_CATCH, "9999"))   # 2005 のわな捕獲（もう片方は正しい値）
    b = _build(root)
    r = _by(b)[(c.ROW_KEYS[c.J_CATCH], "2005")]
    assert r["unreadable_reason"].startswith("ocr_disagree:") and r["value"] is None and r["verified_by"] is None
    assert b["stats"]["ocr_disagree"] >= 1


def test_both_ocr_wrong_the_same_way_is_found_by_arithmetic(tmp_path):
    """2つの OCR が同じ誤読をしても、行と列の検算が交点で特定して未採用にする。"""
    root = tmp_path
    for e in c.ENGINES:
        root = _mutate(tmp_path, e, lambda d: _set_cell(d, 10, c.J_TRAP, "2,201,116"))   # 2010 のわな日 2,101,116 -> 2,201,116（CPUE も合わなくなる大きさ）
    b = _build(root)
    flagged = {(r["row_key"], r["col_key"]) for r in b["rows"] if r["unreadable_reason"]}
    assert (c.ROW_KEYS[c.J_TRAP], "2010") in flagged
    assert b["stats"]["arith_flagged"] >= 1
    assert all(k[1] in ("2010", c.COL_TOTAL) for k in flagged)


def test_cpue_off_is_found_by_arithmetic(tmp_path):
    root = tmp_path
    for e in c.ENGINES:
        root = _mutate(tmp_path, e, lambda d: _set_cell(d, 7, c.J_CPUE, "0.657"))   # 2007: 0.567 -> 0.657
    flagged = {(r["row_key"], r["col_key"]) for r in _build(root)["rows"] if r["unreadable_reason"]}
    assert flagged == {(c.ROW_KEYS[c.J_CPUE], "2007")}


def test_zero_vs_blank_is_flagged(tmp_path):
    def add_zero(d):   # 2003 の探索犬は空欄。片方の OCR が 0 を読んだことにする
        g = d["grid"]
        (y0, y1), (x0, x1) = g["rows"][3], g["cols"][c.J_DOG]
        d["boxes"].append(dict(text="0", x0=x0 + 2, x1=x1 - 2, y0=y0 + 2, y1=y1 - 2, conf=0.9))
    r = _by(_build(_mutate(tmp_path, "paddle", add_zero)))[(c.ROW_KEYS[c.J_DOG], "2003")]
    assert "0 と空欄の区別がつかない" in r["unreadable_reason"]


def test_blank_where_a_value_should_be_is_not_adopted(tmp_path):
    """2つの OCR が同じ場所を空欄と読んでも、空欄のはずでない場所（2012 のわな日）は採用しない。"""
    root = tmp_path
    for e in c.ENGINES:
        def drop(d):
            g = d["grid"]
            (y0, y1), (x0, x1) = g["rows"][12], g["cols"][c.J_TRAP]
            d["boxes"] = [b for b in d["boxes"] if b not in _cell_boxes(d, 12, c.J_TRAP)]
        root = _mutate(tmp_path, e, drop)
    r = _by(_build(root))[(c.ROW_KEYS[c.J_TRAP], "2012")]
    assert "空欄のはずでない" in r["unreadable_reason"] and r["value"] is None
    assert "検算の示す値 2256995" in r["unreadable_reason"]


def test_value_where_blank_expected_is_not_adopted(tmp_path):
    root = tmp_path
    for e in c.ENGINES:
        def add(d):
            g = d["grid"]
            (y0, y1), (x0, x1) = g["rows"][2], g["cols"][c.J_DOG]
            d["boxes"].append(dict(text="3", x0=x0 + 2, x1=x1 - 2, y0=y0 + 2, y1=y1 - 2, conf=0.9))
        root = _mutate(tmp_path, e, add)
    r = _by(_build(root))[(c.ROW_KEYS[c.J_DOG], "2002")]
    assert "空欄のはずの場所に値がある" in r["unreadable_reason"]


def test_dot_in_integer_column_is_a_thousands_separator():
    assert c.lenient(c.J_CATCH, "2.716") == "2716" and c.lenient(c.J_CPUE, "0.567") == "0.567"
    assert c.fmt_ok(c.J_CATCH, "2716") and c.fmt_ok(c.J_CATCH, "") and not c.fmt_ok(c.J_CATCH, "27.16")
    assert c.fmt_ok(c.J_CPUE, "0.0004") and c.fmt_ok(c.J_CPUE, "20.409") and not c.fmt_ok(c.J_CPUE, "0.57")
    assert not c.fmt_ok(c.J_CPUE, "0567")


def test_box_that_fits_no_column_makes_cell_unread(tmp_path):
    def spanning(d):
        g = d["grid"]
        (y0, y1), (x0, _) = g["rows"][4], g["cols"][c.J_CATCH]
        x2 = g["cols"][c.J_TRAP][1]
        d["boxes"].append(dict(text="99", x0=x0 + 2, x1=x2 - 2, y0=y0 + 2, y1=y1 - 2, conf=0.9))   # 2列にまたがる箱
    b = _build(_mutate(tmp_path, "paddle", spanning))
    assert "格子に収まらない" in _by(b)[(c.ROW_KEYS[c.J_CATCH], "2004")]["unreadable_reason"]
    assert any("格子に収まらない OCR の箱" in w for w in b["warnings"])


def test_grid_size_and_input_sha_must_agree(tmp_path):
    with pytest.raises(ValueError, match="格子"):
        _build(_mutate(tmp_path / "a", "paddle", lambda d: d["grid"]["rows"].pop()))
    with pytest.raises(ValueError, match="sha256"):
        _build(_mutate(tmp_path / "b", "paddle", lambda d: d.update(pdf_sha256="0" * 64)))


def test_reviewed_value_that_breaks_arithmetic_is_not_adopted(tmp_path):
    root = copy_ocr(tmp_path, with_reviewed=False)
    for e in c.ENGINES:   # 2010 のわな捕獲を片方 OCR で壊し、人の確認が検算に合わない値を書く
        _mutate(tmp_path, e, lambda d: None)
    _mutate(tmp_path, "paddle", lambda d: _set_cell(d, 10, c.J_CATCH, "9"))
    (root / c.DOC_ID / "reviewed.csv").write_text(
        "row,col,value,reviewer,note\nわな捕獲|捕獲頭数,2010,999,claude(vision),test\n", encoding="utf-8")
    b = _build(root)
    assert any("人が確認したセルが検算に合わない" in w for w in b["warnings"])
    r = _by(b)[(c.ROW_KEYS[c.J_CATCH], "2010")]
    assert r["unreadable_reason"].startswith("ocr_disagree:") and r["value"] is None and r["verified_by"] is None


def test_reviewed_csv_fills_a_disagreement_with_ai_confidence(tmp_path):
    root = _mutate(copy_ocr(tmp_path, with_reviewed=False), "paddle", lambda d: _set_cell(d, 10, c.J_CATCH, "9"))
    (root / c.DOC_ID / "reviewed.csv").write_text(
        "row,col,value,reviewer,note\nわな捕獲|捕獲頭数,2010,311,claude(vision),test\n", encoding="utf-8")
    r = _by(_build(root))[(c.ROW_KEYS[c.J_CATCH], "2010")]
    assert (r["value_raw"], r["verified_by"], r["confidence"]) == ("311", "claude(vision)", 0.9)


def test_reviewed_csv_requires_known_reviewer(tmp_path):
    root = copy_ocr(tmp_path, with_reviewed=False)
    p = root / c.DOC_ID / "reviewed.csv"
    p.write_text("row,col,value,reviewer,note\nわな捕獲|捕獲頭数,2010,311,,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="reviewer"):
        _build(root)
    p.write_text("row,col,value,reviewer,note\nわな捕獲|捕獲頭数,2010,311,山田,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="reviewer が不明"):
        _build(root)


# ------------------------------------------------------------ cells の形
def test_shape_and_provenance():
    rows = c.build(sheet_pdf=None)["rows"]
    assert len(rows) == 5 * 24
    assert {r["row_key"] for r in rows} == {"わな捕獲|捕獲頭数", "わな捕獲|のべわな日", "わな捕獲|CPUE", "探索犬|捕獲頭数", "総捕獲頭数"}
    by = _by({"rows": rows})
    years = [r for r in rows if r["row_key"] == "総捕獲頭数" and r["col_key"] != "合計"]
    assert [r["fiscal_year"] for r in years] == list(range(2000, 2023)) and [r["col_key"] for r in years] == [str(y) for y in range(2000, 2023)]
    assert {r["is_total"] for r in years} == {0}
    assert by[("総捕獲頭数", "2000")]["era_raw"] == "平成12年度(2000)"
    for rk in c.ROW_KEYS:   # 合計の列は is_total=1・fiscal_year なし
        t = by[(rk, "合計")]
        assert (t["is_total"], t["fiscal_year"], t["era_raw"]) == (1, None, None)
    cell = by[("わな捕獲|のべわな日", "2022")]
    assert (cell["value_raw"], cell["value"], cell["value_type"], cell["unit"]) == ("1,387,005", "1387005", "int", "わな日")
    assert (cell["page_no"], cell["table_id"], json_len(cell["source_bbox"])) == (1, "p1_t1", 4)
    # CPUE: float・印字の桁のまま・単位
    cpue = by[("わな捕獲|CPUE", "2018")]
    assert (cpue["value_raw"], cpue["value"], cpue["value_type"], cpue["unit"]) == ("0.0004", "0.0004", "float", "頭/1000わな日")
    assert by[("わな捕獲|CPUE", "2019")]["value_raw"] == "0.0000" and by[("わな捕獲|CPUE", "合計")]["value_raw"] == "0.616"
    assert by[("わな捕獲|CPUE", "2001")]["value_raw"] == "20.409"
    # 0 は 0（空欄ではない）
    zero = by[("探索犬|捕獲頭数", "2009")]
    assert (zero["value"], zero["value_raw"], zero["value_type"]) == ("0", "0", "int")
    # 空欄は value=NULL・value_raw=NULL・(空欄)。未採用ではない
    blanks = {k for k, r in by.items() if r["value"] is None}
    assert blanks == {(c.ROW_KEYS[j], str(2000 + i)) for i, j in c.BLANK}
    assert len(blanks) == 2 + 8
    for k in blanks:
        r = by[k]
        assert (r["source_text"], r["value_raw"], r["value_type"], r["unreadable_reason"]) == ("(空欄)", None, None, None)
    assert {r["extractor"] for r in rows}.pop().startswith("ocr:docling_rapid@")


def json_len(s):
    return len(json.loads(s))


def test_verified_by_without_sheet_falls_back_to_arith():
    b = c.build(sheet_pdf=None)
    assert any("評価シート" in w for w in b["warnings"])
    by = {(r["row_key"], r["col_key"]): r for r in b["rows"]}
    reviewed = c.cellmatch.load_reviewed(c.OCR_DIR / c.DOC_ID / "reviewed.csv", c.norm)
    for k, r in by.items():   # 人の確認でない reviewer（claude(vision)）は 0.9、それ以外は検算 1.0
        assert (r["verified_by"], r["confidence"]) == (("claude(vision)", 0.9) if k in reviewed else ("auto:xocr+arith", 1.0))


def test_doc_series_where_counts():
    """/documents の系列（DOC_SERIES_WHERE）に出る点: 5本、捕獲頭数23・わな日22・CPUE22・探索犬15・総捕獲23。"""
    rows = c.build(sheet_pdf=None)["rows"]
    pts = {}
    for r in rows:
        if r["is_total"] == 0 and r["value_type"] in ("int", "float") and r["value"] is not None and r["fiscal_year"] is not None:
            pts.setdefault(r["row_key"], set()).add(r["fiscal_year"])
    assert {k: len(v) for k, v in pts.items()} == {
        "わな捕獲|捕獲頭数": 23, "わな捕獲|のべわな日": 22, "わな捕獲|CPUE": 22, "探索犬|捕獲頭数": 15, "総捕獲頭数": 23}
    assert min(pts["探索犬|捕獲頭数"]) == 2008 and min(pts["わな捕獲|CPUE"]) == 2001


def test_notes_are_facts_and_block_nothing():
    n = c.build(sheet_pdf=None)["notes"]
    assert len(n) == 6 and {x["table_ids"][0] for x in n} == {"p1_t1"} and {x["blocks_timeseries"] for x in n} == {0}
    assert {x["kind"] for x in n} <= set(doccells.NOTE_KINDS)
    text = "".join(x["text"] for x in n)
    assert "0.616" in text and "0.513" in text and "0.0004" in text


# ------------------------------------------------------------ 評価シートとの突き合わせ
@needs_sheet
def test_sheet_reads_the_same_table():
    sheet = c.sheet_rows(SHEET)
    gt = gt_matrix()
    for (i, j), v in sheet.items():
        if (i, j) == (c.NYEAR, c.J_CPUE):
            assert v == "0.513"
        elif j == c.J_CPUE and v:
            assert v == f"{float(gt[i][j]):.3f}"[:len(v)] or abs(float(v) - float(gt[i][j])) < 0.0006
        else:
            assert v == gt[i][j], (i, j)


@needs_sheet
def test_with_sheet_year_cells_are_xtext_and_the_declared_diff_is_the_total_cpue():
    b = c.build(sheet_pdf=SHEET)
    st = b["stats"]
    assert st["sheet_matched"] == 23 * 5 and st["sheet_declared_diff"] == [(c.ROW_KEYS[c.J_CPUE], c.COL_TOTAL)]
    by = _by(b)
    reviewed = c.cellmatch.load_reviewed(c.OCR_DIR / c.DOC_ID / "reviewed.csv", c.norm)
    assert {by[(rk, str(y))]["verified_by"] for rk in c.ROW_KEYS for y in range(2000, 2023) if (rk, str(y)) not in reviewed} == {"auto:xocr+xtext"}
    assert {by[(rk, c.COL_TOTAL)]["verified_by"] for rk in c.ROW_KEYS if (rk, c.COL_TOTAL) not in reviewed} == {"auto:xocr+arith"}
    assert by[(c.ROW_KEYS[c.J_CPUE], "2018")]["value_raw"] == "0.0004"   # 3桁に丸めて比べるが、値は PNG の印字のまま


def test_sheet_difference_stops_the_build(tmp_path, monkeypatch):
    """シートの値が PNG と食い違えば止める（宣言した差以外）。宣言した差が食い違わなくなっても止める。"""
    dummy = tmp_path / "sheet.pdf"
    dummy.write_bytes(b"%PDF-")
    base = {}
    for i, y in enumerate(gt_matrix()):
        for j, v in enumerate(y):
            base[(i, j)] = v
    base[(c.NYEAR, c.J_CPUE)] = "0.513"
    for i in range(c.NYEAR):
        if base[(i, c.J_CPUE)]:
            base[(i, c.J_CPUE)] = f"{float(base[(i, c.J_CPUE)]):.3f}"
    monkeypatch.setattr(c, "sheet_rows", lambda p: dict(base))
    assert c.build(sheet_pdf=dummy)["stats"]["sheet_matched"] == 23 * 5
    bad = {**base, (9, c.J_CATCH): "599"}
    monkeypatch.setattr(c, "sheet_rows", lambda p: bad)
    with pytest.raises(doccells.IdentityError, match="2009"):
        c.build(sheet_pdf=dummy)
    same = {**base, (c.NYEAR, c.J_CPUE): "0.616"}   # 宣言した差が消えた
    monkeypatch.setattr(c, "sheet_rows", lambda p: same)
    with pytest.raises(doccells.IdentityError, match="宣言した例外"):
        c.build(sheet_pdf=dummy)


# ------------------------------------------------------------ 書き込み
def test_write_replaces_only_own_doc_id(tmp_path, monkeypatch):
    """DB への書き込みは自分の doc_id の行だけを入れ替える。ほかの doc_id には触れない（c101 の宣言の文書も）。"""
    import common
    import c101_mongoose_declaration as d
    db = tmp_path / "cells.sqlite"
    con = sqlite3.connect(db)
    con.executescript((c.ROOT / "scripts/schema_cells.sql").read_text(encoding="utf-8"))
    con.execute("ALTER TABLE cells ADD COLUMN superseded INTEGER DEFAULT 0")
    con.execute("INSERT INTO documents(doc_id,title) VALUES('other','x')")
    con.execute("INSERT INTO cells(doc_id,row_key,col_key,value,value_type) VALUES('other','r','c','1','int')")
    con.execute("INSERT INTO notes(note_id,doc_id,kind,text) VALUES('other_n001','other','footnote','t')")
    con.commit()
    con.close()
    monkeypatch.setattr(common, "cellsdb", lambda: sqlite3.connect(db))
    built = c.build(sheet_pdf=None)
    for _ in range(2):   # 2回書いても行は増えない（入れ替え）
        c.write(built, register=False)
    con = sqlite3.connect(db)
    d_doc, d_notes = d.build()
    doccells.write_doc(con, d.DOC_ID, d_doc, [], d_notes)
    assert con.execute("SELECT count(*) FROM cells WHERE doc_id='other'").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM notes WHERE doc_id='other'").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM cells WHERE doc_id=?", (c.DOC_ID,)).fetchone()[0] == 120
    assert con.execute("SELECT count(*) FROM notes WHERE doc_id=?", (c.DOC_ID,)).fetchone()[0] == 6
    assert con.execute("SELECT count(*) FROM notes WHERE doc_id=?", (d.DOC_ID,)).fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM cells WHERE doc_id=?", (d.DOC_ID,)).fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM documents WHERE doc_id IN (?,?)", (c.DOC_ID, d.DOC_ID)).fetchone()[0] == 2
    assert con.execute("SELECT n_pages FROM documents WHERE doc_id=?", (d.DOC_ID,)).fetchone()[0] is None
    assert con.execute("SELECT count(*) FROM extraction_log").fetchone()[0] == 2   # 2回書いて c100b のログ 2 行


def test_register_writes_one_source_with_the_cell_count(tmp_path, monkeypatch):
    import common
    cells_db, app_db = tmp_path / "cells.sqlite", tmp_path / "ryuiki.sqlite"
    con = sqlite3.connect(cells_db)
    con.executescript((c.ROOT / "scripts/schema_cells.sql").read_text(encoding="utf-8"))
    con.execute("ALTER TABLE cells ADD COLUMN superseded INTEGER DEFAULT 0")
    con.commit()
    con.close()
    con = sqlite3.connect(app_db)
    con.executescript((c.ROOT / "scripts/schema_app.sql").read_text(encoding="utf-8"))
    con.commit()
    con.close()
    monkeypatch.setattr(common, "cellsdb", lambda: sqlite3.connect(cells_db))
    monkeypatch.setattr(common, "appdb", lambda: sqlite3.connect(app_db))
    c.write(c.build(sheet_pdf=None))
    row = sqlite3.connect(app_db).execute(
        "SELECT source_id, license, redistributable, record_count FROM source_registry").fetchall()
    assert row == [(c.SOURCE_ID, doccells.LICENSE_MOE_PDL, 1, 120)]
