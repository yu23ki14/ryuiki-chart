"""c99（奄美の行政文書 → documents / notes）のテスト。PDF は取りに行かない。DB は合成と、あれば手元の原本・サンプルを読み取り専用で見る。"""
import pathlib
import sqlite3

import pytest

import c99_amami_gov_docs as c99
import doccells as dc
from tests.test_doccells import SCHEMA

ROOT = pathlib.Path(__file__).resolve().parents[2]
IDS = [d["doc_id"] for d in c99.DOCS]


def test_static_definitions():
    assert len(IDS) == len(set(IDS)) == 14
    for d in c99.DOCS:
        assert d["url"].startswith("https://") and d["license"] and d["title"] and d["publisher"]
        assert d["local_path"].startswith("amami_doc/") and d["fiscal_year"]
        assert d["doc_id"] in c99.NOTES
    assert {d["source_id"] for d in c99.DOCS} == {s[0] for s in c99.SOURCES}
    assert len({d["local_path"] for d in c99.DOCS}) == 14


def test_notes_are_facts_only_and_never_block_series():
    for doc_id, notes in c99.NOTES.items():
        assert doc_id in IDS and notes
        for n in notes:
            assert n["kind"] in dc.NOTE_KINDS and n["text"] and n["reason"]
            assert n["blocks_timeseries"] == 0


def test_unlicensed_docs_are_metadata_only_and_not_redistributable():
    unlicensed = {d["source_id"] for d in c99.DOCS if d["license"] == c99.NO_LICENSE}
    assert unlicensed == {c99.SRC_STRATEGY, c99.SRC_TOURISM}
    for sid, _n, _p, _u, lic, redis in c99.SOURCES:
        assert redis == (0 if sid in unlicensed else 1) and lic


def test_write_all_touches_only_own_docs():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    dc.write_doc(con, "other", dict(title="t", doc_sha256="x"), [{"table_id": "t", "row_key": "r", "col_key": "c"}],
                 [{"kind": "footnote", "text": "keep", "page": 1}])
    before = [con.execute(f"SELECT * FROM {t} WHERE doc_id='other'").fetchall() for t in ("documents", "cells", "notes")]
    fetched = {i: (None, f"{n:064x}", 3) for n, i in enumerate(IDS)}
    c99.write_all(con, fetched)
    c99.write_all(con, fetched)  # 冪等
    assert con.execute("SELECT count(*) FROM documents").fetchone()[0] == 15
    assert con.execute("SELECT count(*) FROM cells WHERE doc_id!='other'").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM notes WHERE doc_id!='other'").fetchone()[0] == sum(map(len, c99.NOTES.values()))
    assert con.execute("SELECT count(*) FROM notes WHERE blocks_timeseries!=0").fetchone()[0] == 0
    assert before == [con.execute(f"SELECT * FROM {t} WHERE doc_id='other'").fetchall() for t in ("documents", "cells", "notes")]
    assert con.execute("SELECT count(*) FROM documents WHERE doc_id!='other' AND (url='' OR doc_sha256='' OR license='')").fetchone()[0] == 0


def _real_cells():
    p = ROOT / "data/db/cells.sqlite"
    if not p.exists():
        return None
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    n = con.execute(f"SELECT count(*) FROM documents WHERE doc_id IN ({','.join('?' * len(IDS))})", IDS).fetchone()[0]
    return con if n else None


def test_real_db_rows_when_loaded():
    con = _real_cells()
    if con is None:
        pytest.skip("原本（または c99 を書いたあとの DB）が無い")
    q = ",".join("?" * len(IDS))
    assert con.execute(f"SELECT count(*) FROM documents WHERE doc_id IN ({q})", IDS).fetchone()[0] == 14
    assert con.execute(f"SELECT count(*) FROM cells WHERE doc_id IN ({q})", IDS).fetchone()[0] == 0
    assert con.execute(f"SELECT count(*) FROM documents WHERE doc_id IN ({q}) AND (url IS NULL OR url='' OR doc_sha256 IS NULL "
                       "OR doc_sha256='' OR license IS NULL OR license='' OR n_pages IS NULL)", IDS).fetchone()[0] == 0
    assert con.execute(f"SELECT count(*) FROM notes WHERE doc_id IN ({q}) AND blocks_timeseries!=0", IDS).fetchone()[0] == 0
