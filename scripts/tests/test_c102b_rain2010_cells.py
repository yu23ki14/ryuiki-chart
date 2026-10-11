"""c102b（2010年奄美豪雨の雨量・被害 -> cells）のテスト。目で読んだ正解 csv（fixtures/amami_rain2010/truth.csv）と
気象庁の突き合わせ用 csv（jma_check.csv）だけを使う。DB も PDF も pdfplumber も要らない。
PDF との突き合わせ（本文の文・表-2）は PDF（data/raw。gitignore 済み）が無ければ skip する。"""
import copy
import csv
import sqlite3

import pytest

import c102b_rain2010_cells as c
import doccells

FIX = c.ROOT / "scripts/tests/fixtures/amami_rain2010"
needs_pdf = pytest.mark.skipif(
    not all((c.ROOT / c.RAW_DIR / m["file"]).exists() for m in c.DOCS.values()), reason="PDF が無い（CI の最小環境）")


def jma():
    return c.jma_from_csv(FIX / "jma_check.csv")


def built(spec=None):
    return c.build(spec=spec, jma=jma(), check_pdfs=False)


def all_rows(b):
    return [(d, r) for d, x in b["docs"].items() for r in x["rows"]]


def test_every_cell_matches_ground_truth():
    """正解 csv（目で読んだ106行）と cells が、過不足なく (doc, table, row, col, value_raw, unit) で一致する。"""
    truth = list(csv.DictReader(open(FIX / "truth.csv", encoding="utf-8")))
    assert len(truth) == 106
    want = sorted((t["doc_id"], t["table_id"], t["row_key"], t["col_key"], t["value_raw"], t["unit"]) for t in truth)
    got = sorted((d, r["table_id"], r["row_key"], r["col_key"], r["value_raw"] or "", r["unit"]) for d, r in all_rows(built()))
    assert got == want
    pages = {(t["doc_id"], t["table_id"]): int(t["pdf_page"]) for t in truth}
    assert all(pages[(d, r["table_id"])] == r["page_no"] for d, r in all_rows(built()))


def test_counts_and_shape():
    b = built()
    assert {d: len(x["rows"]) for d, x in b["docs"].items()} == {c.DPRI: 12, c.KAGO: 94}
    rows = [r for _, r in all_rows(b)]
    assert sum(r["is_total"] for r in rows) == 9 and {r["table_id"] for r in rows if r["is_total"]} == {c.T_K17}
    assert {r["fiscal_year"] for r in rows} == {None}
    # era_raw は原資料に期間・時点が書かれているものだけ（推定で入れない）
    era = {(d, r["table_id"], r["row_key"]): r["era_raw"] for d, r in all_rows(b)}
    assert era[(c.DPRI, c.T_RAIN, "総雨量（住用）")] is None and era[(c.KAGO, c.T_K2, "総雨量（住用町）")] is None
    assert era[(c.KAGO, c.T_K38, "奄美市名瀬")] is None
    assert era[(c.KAGO, c.T_K17, "死者")] == "2010年11月26日現在" and era[(c.KAGO, c.T_K6, "20日の日積算雨量（名瀬）")] == "10月20日"
    blank = [r for r in rows if r["value_raw"] is None]
    assert len(blank) == 9 * 6 - sum(v is not None for _, _, vs, _ in c.P17_ROWS for v in vs)
    assert all(r["value"] is None and r["source_text"] == "(内訳に記載なし)" for r in blank)
    # 同じ表の中で row_key（最後の | の後ろ）が一意（列ごと）
    seen = {}
    for d, r in all_rows(b):
        key = (d, r["table_id"], r["row_key"].split("|")[-1], r["col_key"])
        assert key not in seen
        seen[key] = 1
    # p17 の値・型
    by = {(r["table_id"], r["row_key"], r["col_key"]): r for _, r in all_rows(b)}
    assert by[(c.T_K16, "被害総額（判明分）", "値")]["value"] == "11568106" and by[(c.T_K16, "被害総額（判明分）", "値")]["value_raw"] == "11,568,106"
    assert by[(c.T_K38, "奄美市名瀬", "時間雨量")]["value_type"] == "float"
    assert by[(c.T_K17, "床上浸水", "合計")]["value_type"] == "int"


def test_provenance():
    rows = {(r["table_id"], r["row_key"], r["col_key"]): r for _, r in all_rows(built())}
    for (t, *_), r in rows.items():
        if t in c.VISION_TABLES:
            assert (r["extractor"], r["verified_by"], r["confidence"]) == ("manual:vision", "claude(vision)", 0.9)
        else:
            assert r["extractor"] == "manual:pdftext" and (r["verified_by"], r["confidence"]) in (("auto:xtext+arith", 1.0), ("claude(text)", 0.9))
    # 突き合わせ先のあるものは検算つき、無いもの・宣言した差のものは claude(text)
    assert rows[(c.T_K38, "奄美市名瀬", "連続雨量")]["verified_by"] == "auto:xtext+arith"
    assert rows[(c.T_RAIN, "最大1時間雨量（名瀬）")[0:2] + ("値",)]["verified_by"] == "auto:xtext+arith"
    assert rows[(c.T_RAIN, "総雨量（住用）", "値")]["verified_by"] == "claude(text)"
    assert rows[(c.T_K38, "奄美市住用町", "連続雨量")]["verified_by"] == "claude(text)"
    assert rows[(c.T_K38, "瀬戸内町古仁屋", "日雨量")]["verified_by"] == "claude(text)"
    assert rows[(c.T_DMG, "全壊・半壊の住家", "値")]["verified_by"] == "claude(text)"
    # vision（p17・p2）とだけ一致するセルは auto に上げない
    for k in [(c.T_DMG, "死者", "値"), (c.T_K6, "浸水による死者", "値"), (c.T_K6, "崖崩れによる死者", "値")]:
        assert (rows[k]["verified_by"], rows[k]["confidence"]) == ("claude(text)", 0.9)
    assert rows[(c.T_RAIN, "最大1時間雨量（住用）", "値")]["verified_by"] == "auto:xtext+arith"   # 表-2 とも一致


def test_declared_differences_are_exactly_the_twelve():
    assert built()["stats"]["declared_diffs"] == sorted(c.DECLARED_DIFFS)
    assert len(c.DECLARED_DIFFS) == 12


def test_no_series_for_doc_series_where():
    """DOC_SERIES_WHERE（web/src/lib/cube/doc-series-where.ts）を通るセルは 0（fiscal_year が全部 NULL）。"""
    src = (c.ROOT / "web/src/lib/cube/doc-series-where.ts").read_text(encoding="utf-8")
    where = src.split('DOC_SERIES_WHERE =\n  "')[1].split('";')[0]
    con = sqlite3.connect(":memory:")
    con.executescript((c.ROOT / "scripts/schema_cells.sql").read_text(encoding="utf-8"))
    con.execute("ALTER TABLE cells ADD COLUMN superseded INTEGER DEFAULT 0")
    for d, x in built()["docs"].items():
        doccells.replace_doc_cells(con, d, x["rows"])
    assert con.execute("SELECT count(*) FROM cells").fetchone()[0] == 106
    assert con.execute(f"SELECT count(*) FROM cells WHERE {where}").fetchone()[0] == 0


def test_notes_are_facts_and_block_nothing():
    n = built()["docs"]
    assert len(n[c.DPRI]["notes"]) == 4 and len(n[c.KAGO]["notes"]) == 7
    for x in (y for d in n.values() for y in d["notes"]):
        assert x["blocks_timeseries"] == 0 and x["kind"] in doccells.NOTE_KINDS
    text = "".join(y["text"] for y in n[c.KAGO]["notes"])
    assert "891" in text and "893" in text and "24時間雨量" in text and "0 とは書かれていない" in text
    # note の table_ids は cells にある table_id
    for d, x in n.items():
        have = {r["table_id"] for r in x["rows"]}
        assert all(set(nt["table_ids"]) <= have for nt in x["notes"])


# ------------------------------------------------------------ 検算（変異）
def mutate(table, row, col, new):
    spec = copy.deepcopy(c.SPEC)
    hit = [s for s in spec if (s["table_id"], s["row_key"], s["col_key"]) == (table, row, col)]
    assert len(hit) == 1
    hit[0]["value_raw"] = new
    return spec


@pytest.mark.parametrize("table,row,col,new", [
    (c.T_K17, "床下浸水", "奄美市", "352"),             # 和 != 合計
    (c.T_K17, "死者", "合計", "4"),
    (c.T_K38, "奄美市名瀬", "連続雨量", "766"),          # 気象庁の和と合わない
    (c.T_K38, "瀬戸内町古仁屋", "時間雨量", "88.5"),
    (c.T_K6, "20日の日積算雨量（名瀬）", "値", "623"),
    (c.T_K16, "最大1時間雨量（名瀬）", "値", "78.0"),
    (c.T_RAIN, "24時間雨量（住用）", "値", "704"),        # 出典間の一致が崩れる
    (c.T_RAIN, "総雨量（住用）", "値", "895"),            # 宣言した差の値が変わる
    (c.T_K2, "総雨量（住用町）", "値", "893"),            # 宣言した差が消える
    (c.T_FLOOD, "床下浸水", "値", "767"),
])
def test_a_changed_value_stops_the_build(table, row, col, new):
    with pytest.raises((doccells.IdentityError, ValueError)):
        built(mutate(table, row, col, new))


def test_rounded_integer_must_be_floor_or_half_even_of_the_decimal():
    assert c.rounded_ok(c.D(78), c.D("78.5")) and c.rounded_ok(c.D(766), c.D("766.5"))
    assert not c.rounded_ok(c.D(79), c.D("78.5")) and not c.rounded_ok(c.D(767), c.D("766.5"))
    with pytest.raises(doccells.IdentityError, match="丸め"):
        built(mutate(c.T_RAIN, "最大1時間雨量（名瀬）", "値", "79"))
    with pytest.raises(doccells.IdentityError, match="丸め"):
        built(mutate(c.T_RAIN, "総雨量（名瀬）", "値", "767"))


def test_table2_shape_is_checked():
    with pytest.raises(ValueError, match="値の形"):
        built(mutate(c.T_K38, "奄美市名瀬", "連続雨量", "766.25"))
    with pytest.raises(ValueError, match="値の形"):
        built(mutate(c.T_K38, "奄美市名瀬", "時間雨量", "78.55"))


# ------------------------------------------------------------ 気象庁
def test_jma_csv_is_the_section_2_3_table():
    j = jma()
    assert len(j) == 8
    assert c.sum_jma(j, "名瀬", 0) == 766.5 and c.sum_jma(j, "古仁屋", 0) == 380.5
    assert j[("名瀬", "2010-10-20")] == (622.0, 78.5) and j[("古仁屋", "2010-10-20")] == (286.5, 89.5)


def test_missing_jma_day_stops():
    j = jma()
    del j[("古仁屋", "2010-10-19")]
    with pytest.raises(doccells.IdentityError, match="足りない"):
        c.build(jma=j, check_pdfs=False)


def test_jma_without_sources_falls_back_to_csv_only_when_not_writing(tmp_path):
    with pytest.raises(FileNotFoundError):
        c.load_jma(tmp_path)
    b = c.build(root=tmp_path, check_pdfs=False)
    assert any("jma_check.csv" in w for w in b["warnings"])
    with pytest.raises(SystemExit, match="書き込みには必須"):
        c.build(root=tmp_path, check_pdfs=False, require_jma=True)


# ------------------------------------------------------------ PDF
@needs_pdf
def test_pdf_text_and_table2_match_spec():
    pytest.importorskip("pdfplumber")
    b = c.build(jma=jma())
    assert b["stats"]["pdf_checked"] is True
    boxes = [r["source_bbox"] for _, r in all_rows(b) if r["table_id"] == c.T_K38]
    assert len(boxes) == 9 and all(boxes)


@needs_pdf
def test_pdf_text_change_stops():
    pytest.importorskip("pdfplumber")
    spec = copy.deepcopy(c.SPEC)
    next(s for s in spec if s["row_key"] == "20日の日雨量（名瀬）")["needle"] = "20日の日雨量は，名瀬で623mm"
    with pytest.raises(ValueError, match="現れない"):
        c.build(spec=spec, jma=jma())


def test_pdf_with_wrong_sha_stops(tmp_path):
    d = tmp_path / c.RAW_DIR
    d.mkdir(parents=True)
    for m in c.DOCS.values():
        (d / m["file"]).write_bytes(b"%PDF-1.4 not the real file")
    with pytest.raises(SystemExit, match="sha256"):
        c.build(root=tmp_path, jma=jma())


def test_docs_urls_and_shas_come_from_the_fetch_script():
    import c102a_rain2010_fetch as f
    for m in c.DOCS.values():
        assert (m["url"], m["sha256"]) == f.FILES[m["file"]]
    assert set(f.FILES) == {m["file"] for m in c.DOCS.values()}


def test_writing_requires_the_pdfs(tmp_path):
    with pytest.raises(SystemExit, match="必須"):
        c.build(root=tmp_path, jma=jma(), require_pdfs=True)


# ------------------------------------------------------------ 書き込み
def schema(path, *files, cells=False):
    con = sqlite3.connect(path)
    for f in files:
        con.executescript((c.ROOT / "scripts" / f).read_text(encoding="utf-8"))
    if cells:
        con.execute("ALTER TABLE cells ADD COLUMN superseded INTEGER DEFAULT 0")
    con.commit()
    con.close()


def test_write_replaces_only_own_doc_ids_and_registers(tmp_path, monkeypatch):
    import common
    cells_db, app_db = tmp_path / "cells.sqlite", tmp_path / "ryuiki.sqlite"
    schema(cells_db, "schema_cells.sql", cells=True)
    schema(app_db, "schema_app.sql")
    con = sqlite3.connect(cells_db)
    con.execute("INSERT INTO documents(doc_id,title) VALUES('other','x')")
    con.execute("INSERT INTO cells(doc_id,row_key,col_key,value,value_type) VALUES('other','r','c','1','int')")
    con.execute("INSERT INTO notes(note_id,doc_id,kind,text) VALUES('other_n001','other','footnote','t')")
    con.commit()
    con.close()
    monkeypatch.setattr(common, "cellsdb", lambda: sqlite3.connect(cells_db))
    monkeypatch.setattr(common, "appdb", lambda: sqlite3.connect(app_db))
    b = built()
    for _ in range(2):   # 2回書いても行は増えない
        assert c.write(b) == {c.DPRI: 12, c.KAGO: 94}
    con = sqlite3.connect(cells_db)
    assert con.execute("SELECT count(*) FROM cells WHERE doc_id='other'").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM notes WHERE doc_id='other'").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM cells").fetchone()[0] == 107
    assert con.execute("SELECT count(*) FROM notes").fetchone()[0] == 12
    assert con.execute("SELECT n_pages, fiscal_year, license FROM documents WHERE doc_id=?", (c.KAGO,)).fetchone() == (
        191, 2011, doccells.LICENSE_NOTE_UNSTATED)
    assert con.execute("SELECT fiscal_year FROM documents WHERE doc_id=?", (c.DPRI,)).fetchone() == (2010,)
    reg = sqlite3.connect(app_db).execute(
        "SELECT source_id, license, redistributable, record_count FROM source_registry ORDER BY source_id").fetchall()
    assert reg == [("dpri_gouu2010_amami", doccells.LICENSE_NOTE_UNSTATED, 0, 12),
                   ("kagoshima_univ_gouu2010_amami", doccells.LICENSE_NOTE_UNSTATED, 0, 94)]


def test_source_ids_contain_amami_as_a_word():
    import re
    for m in c.DOCS.values():
        assert re.search(r"(^|_)amami($|_)", m["source_id"])
