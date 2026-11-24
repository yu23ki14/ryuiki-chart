"""広報誌（Issue #130）の出典宣言と、cells.sqlite にある records の表を r01 が数えること。"""
import hashlib
import json
import sqlite3

import pytest

from registry import build_source_access as bsa
from registry import common
from tests.test_registry_source_access import _build, _doc, _reg


def _cells_with_koho(n_articles):
    cells = sqlite3.connect(":memory:")
    cells.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY)")
    cells.execute("CREATE TABLE cells (doc_id TEXT, superseded INTEGER DEFAULT 0)")
    cells.execute("CREATE TABLE periodical_issues (issue_id TEXT PRIMARY KEY, source_id TEXT)")
    cells.execute("CREATE TABLE document_articles (article_id TEXT PRIMARY KEY, source_id TEXT)")
    cells.execute("INSERT INTO periodical_issues VALUES ('i1', 'tatsugo_koho_amami')")
    cells.executemany("INSERT INTO document_articles VALUES (?, 'tatsugo_koho_amami')", [(f"a{i}",) for i in range(n_articles)])
    return cells


def _empty_registry():
    registry = sqlite3.connect(":memory:")
    registry.execute("CREATE TABLE taxon_assessment (source_id TEXT)")
    registry.execute("CREATE TABLE place (place_id TEXT, place_kind TEXT)")
    registry.execute("CREATE TABLE place_source_ref (place_id TEXT, key_space TEXT, source_edition_id TEXT)")
    registry.execute("CREATE TABLE source_edition (edition_id TEXT, source_id TEXT)")
    return registry


def test_gather_counts_reads_cells_source_tables_and_records_check_uses_them():
    ryuiki, registry = sqlite3.connect(":memory:"), _empty_registry()
    counts = bsa.gather_counts(ryuiki, registry, _cells_with_koho(3))
    assert counts["by_source"]["document_articles"] == {"tatsugo_koho_amami": 3}
    assert counts["by_source"]["periodical_issues"] == {"tatsugo_koho_amami": 1}
    doc = _doc(tatsugo_koho_amami={"records": ["periodical_issues", "document_articles"]})
    doc["record_sets"].update(periodical_issues="periodical_issues", document_articles="document_articles")
    rows = _build(_reg("tatsugo_koho_amami"), {}, doc, counts)
    r = dict(zip(bsa.COLUMNS, rows[0]))
    assert r["state"] == "queryable" and r["n_source_rows"] == 4
    assert json.loads(r["record_set_rows"]) == {"periodical_issues": 1, "document_articles": 3}
    # 記事が 0 行（m13 が未実行）なら宣言が古いとして止まる
    empty = bsa.gather_counts(ryuiki, registry, _cells_with_koho(0))
    with pytest.raises(bsa.AccessError, match="document_articles"):
        _build(_reg("tatsugo_koho_amami"), {}, doc, empty)


def test_real_access_yaml_declares_tatsugo_koho():
    doc = bsa.load_access_yaml()
    assert doc["sources"]["tatsugo_koho_amami"]["records"] == ["periodical_issues", "document_articles"]
    assert doc["record_sets"]["document_articles"] == "document_articles"
    assert doc["record_sets"]["periodical_issues"] == "periodical_issues"
    bsa.validate_static(doc, bsa._manifest_targets())


def test_cells_source_counts_fingerprint(tmp_path):
    """cells.sqlite の広報誌の表（出典の列を持つ表）の件数が変われば指紋が変わる。そういう表が無ければ何も混ぜない。"""
    db = tmp_path / "cells.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY)")
    conn.commit()

    def fp():
        h = hashlib.sha256()
        common._hash_cells_source_counts(h, db)
        return h.hexdigest()

    none = fp()
    assert none == hashlib.sha256().hexdigest()  # 何も混ぜていない（既存の指紋を変えない）
    conn.execute("CREATE TABLE document_articles (article_id TEXT PRIMARY KEY, source_id TEXT)")
    conn.execute("INSERT INTO document_articles VALUES ('a', 's')")
    conn.commit()
    one = fp()
    conn.execute("UPDATE document_articles SET source_id='t'")
    conn.commit()
    assert len({none, one, fp()}) == 3
