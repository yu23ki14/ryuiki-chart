"""s01 のサンプルに広報誌の号を一式で入れる部分（docs/plans/TATSUGO_KOHO.md §8.2）。"""
import sqlite3

import pytest

import m13_tatsugo_koho as m13
import s01_build_sample as s01
from tests.test_m13_tatsugo_koho import build, cat, catalog, cells  # noqa: F401  fixture の再利用


def _written(cells, catalog):
    m13.write(cells, build(catalog))
    cells.row_factory = sqlite3.Row
    return cells


def test_closure_has_no_orphans_and_excludes_other_issues(cells, catalog):
    con = _written(cells, catalog)
    out = s01.select_periodical_rowids(con, ["tatsugo_koho_201808"])
    assert len(out["periodical_issues"]) == 1 and len(out["periodical_issue_files"]) == 2
    assert len(out["document_articles"]) == 5 and len(out["document_article_topics"]) == 5  # 3 + 2 ページ
    assert len(out["documents"]) == 2 and len(out["notes"]) == 2
    assert len(out["periodical_series"]) == 1
    # 選んだ行の外部キーが選んだ行の中で閉じる
    ids = lambda t, col: {r[0] for r in con.execute(f"SELECT {col} FROM {t} WHERE rowid IN ({','.join(map(str, out[t]))})")}
    assert ids("document_articles", "doc_id") <= ids("documents", "doc_id") == ids("periodical_issue_files", "doc_id")
    assert ids("document_article_topics", "article_id") == ids("document_articles", "article_id")


def test_missing_issue_and_missing_tables_stop(cells, catalog):
    con = _written(cells, catalog)
    with pytest.raises(SystemExit, match="原本に無い"):
        s01.select_periodical_rowids(con, ["tatsugo_koho_209912"])
    bare = sqlite3.connect(":memory:")
    bare.executescript("CREATE TABLE documents (doc_id TEXT); CREATE TABLE notes (doc_id TEXT);")
    with pytest.raises(SystemExit, match="m13"):
        s01.select_periodical_rowids(bare, ["x"])


def test_exclude_periodical_docs_keeps_other_documents(cells, catalog):
    con = _written(cells, catalog)
    all_rowids = s01.select_wholesale_rowids(con, "documents")
    kept = s01.exclude_periodical_docs(con, "documents", all_rowids)
    assert [r[0] for r in con.execute(f"SELECT doc_id FROM documents WHERE rowid IN ({','.join(map(str, kept))})")] == ["other_doc"]
    notes_kept = s01.exclude_periodical_docs(con, "notes", s01.select_wholesale_rowids(con, "notes"))
    assert len(notes_kept) == 1


def test_sample_coverage_lists_distinct_periodical_issues():
    import pathlib
    import yaml
    cov = yaml.safe_load((pathlib.Path(__file__).resolve().parents[2] / "data" / "sample" / "coverage.yaml").read_text(encoding="utf-8"))
    ids = cov["periodical_closure"]["issue_ids"]
    assert len(ids) == len(set(ids)) >= 4
    assert {"tatsugo_koho_201808", "tatsugo_koho_201904"} <= set(ids)  # 分割号・合併号を含む
