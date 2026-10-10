"""c98b（ハブ統計の OCR JSON -> cells）のテスト。コミット済みの OCR の JSON（data/ocr/habu/）と、ベンチの正解 CSV
（scripts/tests/fixtures/habu/）だけを使う。OCR のライブラリも DB も要らない。"""
import csv
import json
import pathlib
import shutil

import pytest

import c98b_habu_cells as c

HERE = pathlib.Path(__file__).parent
GT_DIR = HERE / "fixtures" / "habu"
DOCS = {"kagoshima_habu_bite_h28r7": "I1_bite", "kagoshima_habu_kaiage_h28r7": "I1_kaiage"}


def gt_matrix(doc_id):
    rows = list(csv.reader(open(GT_DIR / f"{DOCS[doc_id]}.csv", encoding="utf-8")))[1:]
    return [[c.norm(x) for x in r[1:]] for r in rows]


def grid_of(built, doc_id):
    """cells の行 -> (原表の表記の行列、未採用セルの集合)。死亡数の行は除く。"""
    spec = c.SPECS[doc_id]
    got = {(r["row_key"], r["col_key"]): r for r in built["rows"]}
    mat, unread = [], set()
    for i, (rk, _, _) in enumerate(spec["rows"]):
        row = []
        for j, ck in enumerate(c.COL_KEYS):
            r = got[(rk, ck)]
            if r["unreadable_reason"]:
                unread.add((i, j))
            row.append(r["value_raw"] or "")
        mat.append(row)
    return mat, unread


def copy_ocr(tmp_path, doc_id, with_reviewed):
    tmp_path.mkdir(parents=True, exist_ok=True)
    dst = tmp_path / doc_id
    shutil.copytree(c.OCR_DIR / doc_id, dst)
    if not with_reviewed and (dst / "reviewed.csv").exists():
        (dst / "reviewed.csv").unlink()
    return tmp_path


@pytest.mark.parametrize("doc_id", sorted(DOCS))
def test_every_cell_matches_ground_truth(doc_id):
    """受け入れ基準: 人の確認（reviewed.csv）まで通した出力が、正解の全セルと一致する。未採用のセルは無い。"""
    b = c.build(doc_id)
    mat, unread = grid_of(b, doc_id)
    assert not unread
    assert mat == gt_matrix(doc_id)
    assert b["stats"]["failed_constraints"] == 0
    assert b["stats"]["unreadable"] == 0


@pytest.mark.parametrize("doc_id", sorted(DOCS))
def test_without_review_no_silent_errors(tmp_path, doc_id):
    """人の確認が無いと、食い違いのセルは未採用になる。採用したセルは全部正解と一致する（黙った誤りが無い）。"""
    b = c.build(doc_id, copy_ocr(tmp_path, doc_id, with_reviewed=False))
    mat, unread = grid_of(b, doc_id)
    gt = gt_matrix(doc_id)
    for i, row in enumerate(mat):
        for j, v in enumerate(row):
            if (i, j) not in unread:
                assert v == gt[i][j], (i, j)
    reviewed = c.load_reviewed(c.OCR_DIR / doc_id / "reviewed.csv")
    assert len(unread) == len(reviewed)
    for r in b["rows"]:
        if r["unreadable_reason"]:
            assert r["unreadable_reason"].startswith("ocr_disagree:")
            assert r["value_raw"] is None and r["value"] is None and r["verified_by"] is None and r["confidence"] is None


def test_kaiage_disagreements_carry_arithmetic_hint(tmp_path):
    doc = "kagoshima_habu_kaiage_h28r7"
    b = c.build(doc, copy_ocr(tmp_path, doc, with_reviewed=False))
    by_cell = {(r["row_key"], r["col_key"]): r["unreadable_reason"] for r in b["rows"] if r["unreadable_reason"]}
    assert "検算の示す値 995" in by_cell[("名瀬保健所|奄美市住用町", "H29")]
    assert "検算の示す値 9905" in by_cell[("名瀬保健所|名瀬計", "R5")]
    assert "検算の示す値 238" in by_cell[("業者|名瀬管内", "R2")]


def test_provenance_and_shape_bite():
    b = c.build("kagoshima_habu_bite_h28r7")
    rows = b["rows"]
    assert len(rows) == 13 * 12 + 3 * 11                 # 死亡数の行は3つ（天城町・徳之島計・合計）。年度10と合計（3月末）の11セルずつ
    assert {r["verified_by"] for r in rows} == {"auto:xocr+arith"}
    assert {r["confidence"] for r in rows} == {1.0}
    death = {(r["row_key"], r["col_key"]): r["value"] for r in rows if r["row_key"].endswith("（うち死亡）")}
    assert len(death) == 33
    assert {k for k, v in death.items() if v == "1"} == {
        (rk, ck) for rk in ("徳之島保健所|天城町（うち死亡）", "徳之島保健所|徳之島計（うち死亡）", "合計（うち死亡）")
        for ck in ("R7", "合計(3月末)")}
    assert {v for k, v in death.items()} == {"0", "1"}   # 括弧の無い年は 0
    zero = next(r for r in rows if (r["row_key"], r["col_key"]) == ("合計（うち死亡）", "H28"))
    assert (zero["value"], zero["value_raw"], zero["value_type"], zero["fiscal_year"], zero["is_total"]) == ("0", None, "int", 2016, 1)
    assert not any(r["row_key"].endswith("（うち死亡）") and r["col_key"] == "構成比" for r in rows)
    by = {(r["row_key"], r["col_key"]): r for r in rows}
    cell = by[("徳之島保健所|天城町", "R7")]
    assert (cell["value_raw"], cell["value"], cell["value_type"], cell["unit"]) == ("5(1)", "5", "int", "人")
    assert (cell["fiscal_year"], cell["era_raw"], cell["is_total"]) == (2025, "R7", 0)
    ratio = by[("名瀬保健所|奄美市名瀬", "構成比")]
    assert (ratio["value"], ratio["value_type"], ratio["unit"], ratio["fiscal_year"]) == ("12.9", "float", "%", None)
    tot = by[("名瀬保健所|奄美市名瀬", "合計(3月末)")]
    assert (tot["is_total"], tot["fiscal_year"]) == (1, None)
    assert by[("名瀬保健所|名瀬計", "H28")]["is_total"] == 1
    blank = by[("名瀬保健所|奄美市住用町", "R2")]
    assert blank["value"] is None and blank["value_raw"] is None and blank["unreadable_reason"] is None
    # 年度の列は H28=2016 … R7=2025
    assert [by[("名瀬保健所|奄美市名瀬", k)]["fiscal_year"] for k in c.YEAR_LABELS] == list(range(2016, 2026))


def _mutate(tmp_path, doc_id, engine, fn):
    root = tmp_path if (tmp_path / doc_id).exists() else copy_ocr(tmp_path, doc_id, with_reviewed=False)
    p = root / doc_id / f"{engine}.json"
    d = json.load(open(p, encoding="utf-8"))
    fn(d)
    json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    return root


def _cell_box(d, row, col, text=None):
    """格子の (row, col) の中心に入る箱を返す（text を渡すとその文字に書き換える）"""
    g = d["grid"]
    (y0, y1), (x0, x1) = g["rows"][row], g["cols"][col]
    hit = [b for b in d["boxes"] if x0 <= (b["x0"] + b["x1"]) / 2 <= x1 and y0 - 1 <= (b["y0"] + b["y1"]) / 2 <= y1 + 1]
    assert len(hit) == 1
    if text is not None:
        hit[0]["text"] = text
    return hit[0]


def test_disagreement_is_flagged_not_adopted(tmp_path):
    doc = "kagoshima_habu_bite_h28r7"
    root = _mutate(tmp_path, doc, "paddle", lambda d: _cell_box(d, 0, 0, "7"))   # 4 -> 7（もう片方は 4）
    b = c.build(doc, root)
    r = {(x["row_key"], x["col_key"]): x for x in b["rows"]}[("名瀬保健所|奄美市名瀬", "H28")]
    assert r["unreadable_reason"].startswith("ocr_disagree:") and r["value"] is None
    assert b["stats"]["ocr_disagree"] == 1


def test_both_ocr_wrong_the_same_way_is_found_by_arithmetic(tmp_path):
    """2つの OCR が同じ誤読をしても、行と列の検算が交点で特定して未採用にする。"""
    doc = "kagoshima_habu_bite_h28r7"
    root = tmp_path
    for e in c.ENGINES:
        root = _mutate(tmp_path, doc, e, lambda d: _cell_box(d, 4, 3, "9"))   # 宇検村 R1: 1 -> 9（両方とも）
    b = c.build(doc, root)
    flagged = {(x["row_key"], x["col_key"]) for x in b["rows"] if x["unreadable_reason"]}
    assert flagged == {("名瀬保健所|宇検村", "R1")}
    assert b["stats"]["arith_flagged"] == 1


def test_zero_vs_blank_is_flagged(tmp_path):
    doc = "kagoshima_habu_bite_h28r7"
    # 住用町 R2 は空欄。片方の OCR が 0 を読んだことにする
    def add_zero(d):
        g = d["grid"]; (y0, y1), (x0, x1) = g["rows"][1], g["cols"][4]
        d["boxes"].append(dict(text="0", x0=x0 + 5, x1=x1 - 5, y0=y0 + 5, y1=y1 - 5, conf=0.9))
    root = _mutate(tmp_path, doc, "paddle", add_zero)
    b = c.build(doc, root)
    r = {(x["row_key"], x["col_key"]): x for x in b["rows"]}[("名瀬保健所|奄美市住用町", "R2")]
    assert "0 と空欄の区別がつかない" in r["unreadable_reason"]


def test_dot_in_integer_column_is_a_thousands_separator():
    assert c.lenient(0, "2.716") == "2716" and c.lenient(c.NY + 1, "12.9%") == "12.9%"
    assert c.fmt_ok(0, "5(1)") and c.fmt_ok(0, "") and not c.fmt_ok(0, "5(") and not c.fmt_ok(c.NY + 1, "12%")


def test_reviewed_value_that_breaks_arithmetic_is_not_adopted(tmp_path):
    doc = "kagoshima_habu_kaiage_h28r7"
    root = copy_ocr(tmp_path, doc, with_reviewed=True)
    p = root / doc / "reviewed.csv"
    p.write_text(p.read_text(encoding="utf-8").replace("名瀬保健所|奄美市住用町,H29,995,", "名瀬保健所|奄美市住用町,H29,996,"), encoding="utf-8")
    b = c.build(doc, root)
    assert any("人が確認したセルが検算に合わない" in w for w in b["warnings"])
    r = {(x["row_key"], x["col_key"]): x for x in b["rows"]}[("名瀬保健所|奄美市住用町", "H29")]
    assert r["unreadable_reason"].startswith("ocr_disagree:") and r["value"] is None and r["verified_by"] is None


def test_reviewed_csv_requires_reviewer(tmp_path):
    doc = "kagoshima_habu_kaiage_h28r7"
    root = copy_ocr(tmp_path, doc, with_reviewed=True)
    (root / doc / "reviewed.csv").write_text("row,col,value,reviewer,note\n業者|名瀬管内,R2,238,,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="reviewer"):
        c.build(doc, root)


def test_write_replaces_only_own_doc_id(tmp_path, monkeypatch):
    """DB への書き込みは自分の doc_id の行だけを入れ替える。ほかの doc_id・もう一方のハブの資料には触れない。"""
    import sqlite3
    import common
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
    for _ in range(2):   # 2回書いても行は増えない（入れ替え）
        for doc_id in DOCS:
            c.write(doc_id, c.build(doc_id))
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM cells WHERE doc_id='other'").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM notes WHERE doc_id='other'").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM cells WHERE doc_id='kagoshima_habu_bite_h28r7'").fetchone()[0] == 189
    assert con.execute("SELECT count(*) FROM cells WHERE doc_id='kagoshima_habu_kaiage_h28r7'").fetchone()[0] == 204
    assert con.execute("SELECT count(*) FROM notes WHERE doc_id LIKE 'kagoshima_habu%'").fetchone()[0] == 8
    assert con.execute("SELECT count(*) FROM extraction_log").fetchone()[0] == 4


def test_verified_by_never_poses_as_human():
    assert c.verified_by_for("claude(vision)") == ("claude(vision)", 0.9)
    assert c.verified_by_for("GPT-5 vision") == ("GPT-5 vision", 0.9)
    assert c.verified_by_for("human:山田") == ("human:山田", 1.0)
    for bad in ("山田", "", "human:", None):
        with pytest.raises(ValueError):
            c.verified_by_for(bad)


def test_committed_reviews_are_ai_confidence_not_human():
    """コミット済みの reviewed.csv の3セルは claude(vision) の確認。verified_by は human: にならず、confidence は 1.0 でない。"""
    doc = "kagoshima_habu_kaiage_h28r7"
    b = c.build(doc)
    reviewed = c.load_reviewed(c.OCR_DIR / doc / "reviewed.csv")
    assert len(reviewed) == 3 and all(who == "claude(vision)" for _, who, _ in reviewed.values())
    by = {(r["row_key"], r["col_key"]): (r["verified_by"], r["confidence"]) for r in b["rows"]}
    for key in reviewed:
        assert by[key] == ("claude(vision)", 0.9)
    assert not any((r["verified_by"] or "").startswith("human:") for r in b["rows"])


def test_unknown_reviewer_name_stops(tmp_path):
    doc = "kagoshima_habu_kaiage_h28r7"
    root = copy_ocr(tmp_path, doc, with_reviewed=True)
    p = root / doc / "reviewed.csv"
    p.write_text(p.read_text(encoding="utf-8").replace("claude(vision)", "山田"), encoding="utf-8")
    with pytest.raises(ValueError, match="reviewer が不明"):
        c.build(doc, root)


def test_grid_size_and_pdf_sha_must_agree(tmp_path):
    doc = "kagoshima_habu_bite_h28r7"
    with pytest.raises(ValueError, match="格子"):
        c.build(doc, _mutate(tmp_path / "a", doc, "paddle", lambda d: d["grid"]["rows"].pop()))
    with pytest.raises(ValueError, match="pdf_sha256"):
        c.build(doc, _mutate(tmp_path / "b", doc, "paddle", lambda d: d.update(pdf_sha256="0" * 64)))


def test_local_pdf_sha_must_match_json(tmp_path):
    doc = "kagoshima_habu_bite_h28r7"
    pdf = tmp_path / "root" / c.SPECS[doc]["pdf"]
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"not the pdf")
    with pytest.raises(ValueError, match="ローカルの PDF"):
        c.build(doc, pdf_root=tmp_path / "root")
    assert c.build(doc, pdf_root=tmp_path / "none")["stats"]["pdf_sha256"]   # PDF が無い環境（CI）では照合を飛ばす


def test_box_that_fits_no_column_makes_cell_unread(tmp_path):
    doc = "kagoshima_habu_bite_h28r7"
    def spanning(d):
        g = d["grid"]; (y0, y1), (x0, x1) = g["rows"][0], g["cols"][3]
        x2 = g["cols"][4][1]
        d["boxes"].append(dict(text="99", x0=x0 + 5, x1=x2 - 5, y0=y0 + 5, y1=y1 - 5, conf=0.9))   # 2列にまたがる箱
    b = c.build(doc, _mutate(tmp_path, doc, "paddle", spanning))
    got = {(x["row_key"], x["col_key"]): x for x in b["rows"]}
    assert "格子に収まらない" in got[("名瀬保健所|奄美市名瀬", "R1")]["unreadable_reason"]
    assert any("格子に収まらない OCR の箱" in w for w in b["warnings"])
