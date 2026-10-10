"""doccells（AMAMI_STEP2C §2）のテスト。合成の行だけを使う。"""
import sqlite3

import pytest

import doccells as dc

SCHEMA = """
CREATE TABLE documents (doc_id TEXT PRIMARY KEY, title TEXT, publisher TEXT, url TEXT, local_path TEXT,
  doc_sha256 TEXT, n_pages INTEGER, fiscal_year INTEGER, license TEXT, fetched_at TEXT);
CREATE TABLE cells (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT NOT NULL, doc_sha256 TEXT, page_no INTEGER,
  table_id TEXT, row_key TEXT, col_key TEXT, value_raw TEXT, value TEXT, value_type TEXT, unit TEXT,
  fiscal_year INTEGER, era_raw TEXT, source_text TEXT, source_bbox TEXT, notes_ref TEXT,
  is_total INTEGER DEFAULT 0, merged INTEGER DEFAULT 0, unreadable_reason TEXT, confidence REAL,
  extractor TEXT, verified_by TEXT, extracted_at TEXT, superseded INTEGER DEFAULT 0);
CREATE TABLE notes (note_id TEXT PRIMARY KEY, doc_id TEXT, table_ids TEXT, kind TEXT, text TEXT, page INTEGER,
  blocks_timeseries INTEGER, reason TEXT);
CREATE TABLE extraction_log (ts TEXT, doc_id TEXT, page_no INTEGER, table_id TEXT, role TEXT, attempt INTEGER,
  verdict TEXT, failures TEXT, note TEXT);
"""


@pytest.fixture
def con():
    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA)
    return c


def cell(doc, rk, v):
    return {"doc_id": doc, "table_id": "t", "row_key": rk, "col_key": "y", "value_raw": str(v),
            "value": str(v), "value_type": "int", "fiscal_year": 2020}


def test_parse_count():
    assert dc.parse_count("5(1)") == (5, 1)
    assert dc.parse_count("５（１）") == (5, 1)
    assert dc.parse_count("1,796") == (1796, None)
    assert dc.parse_count("0") == (0, None)
    for blank in ("", None, "-", "－", " "):
        assert dc.parse_count(blank) == (None, None)
    with pytest.raises(ValueError):
        dc.parse_count("abc")


def test_era_to_year_fullwidth():
    assert dc.era_to_year("Ｒ１") == 2019
    assert dc.era_to_year("R２") == 2020
    assert dc.era_to_year("R元") == 2019
    assert dc.era_to_year("H２３") == 2011
    assert dc.era_to_year("R7") == 2025
    assert dc.era_to_year("令和４年度") == 2022
    assert dc.era_to_year("2024") == 2024


def test_replace_doc_cells_touches_only_own_doc(con):
    dc.replace_doc_cells(con, "a", [cell("a", "x", 1), cell("a", "y", 2)])
    dc.replace_doc_cells(con, "b", [cell("b", "x", 9)])
    n = dc.replace_doc_cells(con, "a", [cell("a", "z", 3)])
    assert n == 1
    assert con.execute("SELECT row_key FROM cells WHERE doc_id='a'").fetchall() == [("z",)]
    assert con.execute("SELECT count(*) FROM cells WHERE doc_id='b'").fetchone() == (1,)
    with pytest.raises(ValueError):
        dc.replace_doc_cells(con, "a", [cell("b", "x", 1)])
    with pytest.raises(TypeError):
        dc.replace_doc_cells(con, "a", [{"row_key": "x", "bogus": 1}])


def test_notes_ids_and_scope(con):
    ids = dc.put_notes(con, "a", [{"kind": "footnote", "text": "t1"},
                                  {"kind": "comparability", "text": "t2", "table_ids": ["p1_t2"],
                                   "blocks_timeseries": 1}])
    dc.put_notes(con, "b", [{"kind": "footnote", "text": "b"}])
    assert ids == ["a_n001", "a_n002"]
    dc.put_notes(con, "a", [{"kind": "footnote", "text": "new"}])
    assert con.execute("SELECT count(*) FROM notes WHERE doc_id='b'").fetchone() == (1,)
    assert con.execute("SELECT count(*) FROM notes WHERE doc_id='a'").fetchone() == (1,)
    with pytest.raises(ValueError):
        dc.put_notes(con, "a", [{"kind": "bogus", "text": "x"}])


def test_check_identity_declared_exceptions_exact():
    obs = {"H26": (10, 10), "H27": (7179, 3511)}
    assert dc.check_identity("t", obs, {"H27": (7179, 3511)}) == {"H27": (7179, 3511)}
    # 宣言が足りない
    with pytest.raises(dc.IdentityError, match="宣言にない"):
        dc.check_identity("t", obs, {})
    # 宣言が多い（実際は一致している）
    with pytest.raises(dc.IdentityError, match="食い違っていない"):
        dc.check_identity("t", obs, {"H27": (7179, 3511), "H26": (1, 2)})
    # 値が違う
    with pytest.raises(dc.IdentityError, match="値が違う"):
        dc.check_identity("t", obs, {"H27": (7179, 3512)})
    # 例外なし
    assert dc.check_identity("t", {"a": (1, 1)}) == {}


def test_write_doc_rolls_back_and_log_appends(con):
    doc = {"title": "T", "publisher": "P"}
    dc.write_doc(con, "a", doc, [cell("a", "x", 1)], [], [{"verdict": "pass", "note": "n"}])
    dc.write_doc(con, "a", doc, [cell("a", "x", 2)], [], [{"verdict": "pass"}])
    assert con.execute("SELECT count(*) FROM extraction_log").fetchone() == (2,)  # 追記のみ
    assert con.execute("SELECT value FROM cells WHERE doc_id='a'").fetchall() == [("2",)]
    with pytest.raises(ValueError):
        dc.write_doc(con, "a", doc, [cell("a", "x", 3)], [{"kind": "bogus", "text": "x"}])
    assert con.execute("SELECT value FROM cells WHERE doc_id='a'").fetchall() == [("2",)]  # 戻っている


def test_write_doc_refuses_open_caller_transaction(con):
    con.execute("INSERT INTO documents(doc_id) VALUES('x')")   # 呼び手のトランザクションが開いたまま
    with pytest.raises(RuntimeError, match="トランザクション"):
        dc.write_doc(con, "d", {"title": "t"}, [], [])
    assert con.in_transaction   # 呼び手の分には触れていない


def test_count_cell():
    base = dict(table_id="t", row_key="r")
    assert dc.count_cell("1,796", **base) == dict(base, value_raw="1,796", value="1796", value_type="int")
    c = dc.count_cell("5(1)", **base)
    assert (c["value"], c["value_type"]) == ("5", "int")
    assert dc.count_cell("－", **base)["value_type"] == "string" and dc.count_cell("－", **base)["value"] is None
    blank = dc.count_cell("", **base)
    assert (blank["value_raw"], blank["value"], blank["value_type"]) == (None, None, None)
    assert dc.count_cell("0", **base)["value"] == "0"


def test_commit_doc_opens_writes_closes(tmp_path, monkeypatch):
    import common
    db = tmp_path / "c.sqlite"
    c0 = sqlite3.connect(db)
    c0.executescript(SCHEMA)
    c0.close()
    monkeypatch.setattr(common, "cellsdb", lambda: sqlite3.connect(db))
    seen = []
    monkeypatch.setattr(common, "register", lambda **kw: seen.append(kw))
    n = dc.commit_doc("d", {"title": "t"}, [dc.count_cell("3", table_id="t", row_key="r")], [], source=dict(source_id="s"))
    assert n == 1 and seen == [dict(source_id="s", record_count=1)]
    assert sqlite3.connect(db).execute("SELECT count(*) FROM cells").fetchone() == (1,)
