"""c104b（奄美の水道の水源種別・ダム容量 -> cells）のテスト。正解 csv（fixtures/amami_water_dam/）だけを使う。
DB も PDF も pdfplumber も要らない。PDF との突き合わせは PDF（data/raw。gitignore 済み）が無ければ skip する。"""
import copy
import csv
import sqlite3
from decimal import Decimal

import pytest

import c104b_amami_water_dam_cells as c
import doccells

FIX = c.ROOT / "scripts/tests/fixtures/amami_water_dam"
needs_pdf = pytest.mark.skipif(not all(m["path"].exists() for m in c.DOCS.values()), reason="PDF が無い（CI の最小環境）")


def built(spec=None):
    return c.build(spec=spec, check_pdfs=False)


def all_rows(b):
    return [(d, r) for d, x in b["docs"].items() for r in x["rows"]]


def test_every_cell_matches_ground_truth():
    water = list(csv.DictReader(open(FIX / "water_truth.csv", encoding="utf-8")))
    dam = list(csv.DictReader(open(FIX / "dam_truth.csv", encoding="utf-8")))
    assert len(water) == 48 and len(dam) == 9
    want = sorted([(t["doc"], t["table_id"], int(t["page_no"]), t["row_key"], t["col_key"], Decimal(t["value"]), t["unit"], int(t["is_total"]))
                   for t in water] +
                  [(c.DAM, c.T_P5 if t["row_key"] == "大和ダム" else c.T_P6, 5 if t["row_key"] == "大和ダム" else 6,
                    t["row_key"], t["col_key"], Decimal(t["value"]), t["unit"], 0) for t in dam])
    b = built()
    got = sorted((d, r["table_id"], r["page_no"], r["row_key"], r["col_key"], Decimal(r["value"]), r["unit"], r["is_total"])
                 for d, r in all_rows(b))
    assert got == want
    # 印字（value_raw）はカンマ付きの印字で、カンマを除けば value
    assert all(Decimal(r["value_raw"].replace(",", "")) == Decimal(r["value"]) for _, r in all_rows(b))


def test_counts_and_shape():
    b = built()
    assert {d: len(x["rows"]) for d, x in b["docs"].items()} == {c.JORYO: 24, c.KANI: 24, c.DAM: 9}
    rows = [r for _, r in all_rows(b)]
    assert sum(r["is_total"] for r in rows) == 6
    assert {r["fiscal_year"] for r in rows} == {None}
    assert {r["era_raw"] for d, r in all_rows(b) if d != c.DAM} == {"令和６年３月"}
    assert {r["era_raw"] for d, r in all_rows(b) if d == c.DAM} == {None}
    seen = set()
    for d, r in all_rows(b):
        k = (d, r["table_id"], r["row_key"], r["col_key"])
        assert k not in seen
        seen.add(k)
    units = {(d, r["unit"]) for d, r in all_rows(b)}
    assert (c.JORYO, "千m3") in units and (c.KANI, "m3") in units and (c.KANI, "箇所") in units


def test_provenance():
    b = built()
    assert {r["verified_by"] for _, r in all_rows(b)} == {"claude(text)"}   # PDF を検査していなければ auto に上げない


def test_provenance_when_pdf_checked():
    backed = c.run_checks(c.SPEC)
    rows = c.to_rows(c.SPEC, backed, {}, True, {})
    by = {(r["table_id"], r["row_key"], r["col_key"]): r for x in rows.values() for r in x}
    assert by[("x1", "奄美市", "合計")]["verified_by"] == "auto:xtext+arith" and by[("x1", "奄美市", "合計")]["confidence"] == 1.0
    assert by[("x2", "大和村", "簡易水道の箇所数")]["verified_by"] == "claude(text)"
    assert by[("x2", "大和村", "表流水（取水箇所）")]["verified_by"] == "claude(text)"
    assert by[("x2", "宇検村", "計（取水量）")]["verified_by"] == "auto:xtext+arith"
    assert by[("p5_t1", "大和ダム", "洪水調節容量の有効貯水容量に対する割合")]["verified_by"] == "auto:xtext+arith"
    assert by[("p6_text", "大川ダム", "有効貯水量")]["verified_by"] == "claude(text)"
    assert by[("p6_text", "大川ダム", "有効貯水量")]["extractor"] == "manual:pdftext" and by[("x1", "奄美市", "ダム")]["extractor"] == "pdfplumber"
    assert sum(r["verified_by"] == "auto:xtext+arith" for x in rows.values() for r in x) == 43


def mutate(doc, table, row, col, new):
    spec = copy.deepcopy(c.SPEC)
    hit = [s for s in spec if (s["doc"], s["table_id"], s["row_key"], s["col_key"]) == (doc, table, row, col)]
    assert len(hit) == 1
    hit[0]["value_raw"] = new
    return spec


@pytest.mark.parametrize("args", [
    (c.JORYO, "x1", "奄美市", "自流", "3,292"),
    (c.JORYO, "x1", "龍郷町", "合計", "1,230"),
    (c.KANI, "x2", "瀬戸内町", "地下水（取水量）", "32,251"),
    (c.KANI, "x2", "宇検村", "計（取水量）", "337,261"),
    (c.DAM, "p5_t1", "大和ダム", "洪水調節容量", "518"),
    (c.DAM, "p5_t1", "大和ダム", "有効貯水容量", "722"),
    (c.DAM, "p5_t1", "大和ダム", "水害対策に使える容量の有効貯水容量に対する割合", "89.1"),
])
def test_a_changed_value_stops_the_build(args):
    with pytest.raises(doccells.IdentityError):
        built(mutate(*args))


def test_bad_number_shape_stops():
    with pytest.raises(ValueError, match="値の形"):
        built(mutate(c.JORYO, "x1", "奄美市", "自流", "3291,0"))


def test_no_series_for_doc_series_where():
    src = (c.ROOT / "web/src/lib/cube/doc-series-where.ts").read_text(encoding="utf-8")
    where = src.split('DOC_SERIES_WHERE =\n  "')[1].split('";')[0]
    con = sqlite3.connect(":memory:")
    con.executescript((c.ROOT / "scripts/schema_cells.sql").read_text(encoding="utf-8"))
    con.execute("ALTER TABLE cells ADD COLUMN superseded INTEGER DEFAULT 0")
    for d, x in built()["docs"].items():
        doccells.replace_doc_cells(con, d, x["rows"])
    assert con.execute("SELECT count(*) FROM cells").fetchone()[0] == 57
    assert con.execute(f"SELECT count(*) FROM cells WHERE {where}").fetchone()[0] == 0


def test_notes_are_facts_and_block_nothing():
    b = built()
    assert {d: len(x["notes"]) for d, x in b["docs"].items()} == {c.JORYO: 2, c.KANI: 3, c.DAM: 2}
    for d, x in b["docs"].items():
        have = {r["table_id"] for r in x["rows"]}
        for n in x["notes"]:
            assert n["blocks_timeseries"] == 0 and n["kind"] in doccells.NOTE_KINDS and set(n["table_ids"]) & have
    assert "337,260" in "".join(n["text"] for n in b["docs"][c.KANI]["notes"])


def test_documents_and_license():
    for x in built()["docs"].values():
        d = x["document"]
        assert d["license"] == doccells.LICENSE_PREF_KAGOSHIMA and d["fiscal_year"] is None and d["publisher"] == "鹿児島県"
    assert {s["source_id"] for s in c.DOCS.values()} == set(c.SOURCES) and sum(len(s["docs"]) for s in c.SOURCES.values()) == 3


def test_write_touches_only_own_doc_ids(tmp_path):
    con = sqlite3.connect(tmp_path / "x.sqlite")
    con.executescript((c.ROOT / "scripts/schema_cells.sql").read_text(encoding="utf-8"))
    con.execute("ALTER TABLE cells ADD COLUMN superseded INTEGER DEFAULT 0")
    con.execute("INSERT INTO documents (doc_id) VALUES ('other')")
    con.execute("INSERT INTO cells (doc_id, row_key) VALUES ('other','r')")
    con.commit()
    for d, x in built()["docs"].items():
        doccells.write_doc(con, d, x["document"], x["rows"], x["notes"])
    assert con.execute("SELECT count(*) FROM cells WHERE doc_id='other'").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM cells").fetchone()[0] == 58
    assert con.execute("SELECT count(*) FROM notes").fetchone()[0] == 7


@needs_pdf
def test_pdf_matches_spec_and_bbox():
    pytest.importorskip("pdfplumber")
    b = c.build()
    assert b["stats"]["pdf_checked"] is True and not b["warnings"]
    rows = [r for _, r in all_rows(b)]
    assert all(r["source_bbox"] for r in rows if r["table_id"] != c.T_P6)
    assert sum(r["verified_by"] == "auto:xtext+arith" for r in rows) == 43


@needs_pdf
def test_pdf_mismatch_stops():
    pytest.importorskip("pdfplumber")
    spec = mutate(c.JORYO, "x1", "奄美市", "ダム", "933")
    for s in spec:   # 検算を保ったまま PDF とだけ食い違わせる
        if (s["doc"], s["row_key"], s["col_key"]) == (c.JORYO, "奄美市", "合計"):
            s["value_raw"] = "5,833"
    with pytest.raises(ValueError, match="SPEC と違う"):
        c.build(spec=spec)
    spec = mutate(c.DAM, "p6_text", "大川ダム", "有効貯水量", "2,181")
    with pytest.raises(ValueError, match="現れない"):
        c.build(spec=spec)


def test_without_pdfs_warns_and_write_requires_them(tmp_path):
    b = c.build(root=tmp_path)
    assert b["stats"]["pdf_checked"] is False and any("PDF が無い" in w for w in b["warnings"])
    with pytest.raises(SystemExit, match="書き込みには必須"):
        c.build(root=tmp_path, require_pdfs=True)
