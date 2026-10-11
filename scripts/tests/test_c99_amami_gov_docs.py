"""c99（奄美の行政文書 → documents / notes）のテスト。PDF は取りに行かない。DB は合成と、あれば手元の原本・サンプルを読み取り専用で見る。"""
import pathlib
import sqlite3

import pytest

import c99_amami_gov_docs as c99
import doccells as dc
from tests.test_doccells import SCHEMA

ROOT = pathlib.Path(__file__).resolve().parents[2]
IDS = [d[0] for d in c99.DOCS]


def test_static_definitions():
    assert len(IDS) == len(set(IDS)) == 14
    for d in c99.DOCS:
        doc_id, sid, title, pub, url, name, fy, lic, _ = d
        assert url.startswith("https://") and lic and title and pub and fy and sid in c99.SOURCES
    assert len({d[5] for d in c99.DOCS}) == 14
    assert {d[1] for d in c99.DOCS} == set(c99.SOURCES)


def test_notes_page_kind_and_never_block_series():
    for d in c99.DOCS:
        for n in c99.doc_notes(d):
            assert n["kind"] in (c99.SC, c99.FN) and n["text"] and n["reason"]
            assert n["blocks_timeseries"] == 0
            if n["page"] is None:  # PDF の外の事実は取得元の URL を本文に書く
                assert "https://" in n["text"], n
    for doc_id in ("moe_amami_mongoose_plan_r3_r7",):
        texts = [n["text"] for d in c99.DOCS if d[0] == doc_id for n in c99.doc_notes(d)]
        assert texts == ["計画期間は2021年4月1日から2026年3月31日まで（5年間）。"]


def test_unlicensed_docs_are_metadata_only_and_not_redistributable():
    unlicensed = {d[1] for d in c99.DOCS if d[7] == c99.NO_LICENSE}
    assert unlicensed == {"amami_biodiversity_strategy_amami", "amami_tourism_plans_amami"}
    for sid in c99.SOURCES:
        lic, redis = c99.source_license(sid)
        assert redis == (0 if sid in unlicensed else 1)
    for d in c99.DOCS:
        auto = [n for n in c99.doc_notes(d) if n["reason"] == "ライセンス表記なし"]
        assert len(auto) == (1 if d[7] == c99.NO_LICENSE else 0)


def test_registry_declares_licenses_and_sources():
    import yaml
    lic = yaml.safe_load((ROOT / "registry/source/license.yaml").read_text(encoding="utf-8"))
    raws = {m["raw"] for m in lic["mappings"]}
    assert {d[7] for d in c99.DOCS} <= raws
    acc = yaml.safe_load((ROOT / "registry/source/access.yaml").read_text(encoding="utf-8"))
    assert set(c99.SOURCES) <= set(acc["sources"])
    assert all(acc["sources"][s]["reason"] == "pdf_document" for s in c99.SOURCES)


def test_write_all_touches_only_own_docs():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    dc.write_doc(con, "other", dict(title="t", doc_sha256="x"), [{"table_id": "t", "row_key": "r", "col_key": "c"}],
                 [{"kind": "footnote", "text": "keep", "page": 1}])
    before = [con.execute(f"SELECT * FROM {t} WHERE doc_id='other'").fetchall() for t in ("documents", "cells", "notes")]
    fetched = {i: (None, f"{n:064x}", 3, "2026-10-11T00:00:00") for n, i in enumerate(IDS)}
    c99.write_all(con, fetched)
    c99.write_all(con, fetched)  # 冪等
    assert con.execute("SELECT count(*) FROM documents").fetchone()[0] == 15
    assert con.execute("SELECT count(*) FROM cells WHERE doc_id!='other'").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM notes WHERE doc_id!='other'").fetchone()[0] == sum(len(c99.doc_notes(d)) for d in c99.DOCS)
    assert con.execute("SELECT count(*) FROM notes WHERE blocks_timeseries!=0").fetchone()[0] == 0
    assert before == [con.execute(f"SELECT * FROM {t} WHERE doc_id='other'").fetchall() for t in ("documents", "cells", "notes")]
    assert con.execute("SELECT count(*) FROM documents WHERE doc_id!='other' AND (url='' OR doc_sha256='' OR license='' OR fetched_at IS NULL)").fetchone()[0] == 0


def test_pdf_page_count_rejects_broken_files(tmp_path):
    bad = tmp_path / "x.pdf"
    bad.write_bytes(b"<html>not a pdf</html>")
    with pytest.raises(ValueError):
        dc.pdf_page_count(bad)
    pytest.importorskip("pdfplumber")
    trunc = tmp_path / "y.pdf"
    trunc.write_bytes(b"%PDF-1.4\n garbage")
    with pytest.raises(ValueError):
        dc.pdf_page_count(trunc)


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
