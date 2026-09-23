"""b10（`scripts/b10_project_documents_v1.py`）用の、本物の `data/db/cells.sqlite`/
`ryuiki.sqlite` を要さない小さな sqlite フィクスチャ。

b10 が実際に `SELECT` する列だけを持つ最小限の形にしてある
（`scripts/tests/occurrence_fixtures.py` と同じ方針）。
"""
from __future__ import annotations

import sqlite3

# cells: doc_id, table_id, page_no, row_key, col_key, value, value_type, unit,
# fiscal_year, is_total, superseded の11列だけ（b10 の SQL が参照する列）。
_CELLS_COLUMNS = (
    "doc_id", "table_id", "page_no", "row_key", "col_key",
    "value", "value_type", "unit", "fiscal_year", "is_total", "superseded",
)

_DOCUMENTS_COLUMNS = ("doc_id", "title", "publisher", "url", "license")

_NOTES_COLUMNS = ("doc_id", "blocks_timeseries")

_QUALITY_TRANSITIONS_COLUMNS = ("from_stage", "to_stage", "occurred_at")


def make_cells_db(path, cells=None, documents=None, notes=None) -> None:
    """`cells.sqlite` 相当（`cells`/`documents`/`notes` の3テーブル）を作る。"""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """CREATE TABLE cells (
                doc_id TEXT, table_id TEXT, page_no INTEGER, row_key TEXT, col_key TEXT,
                value TEXT, value_type TEXT, unit TEXT, fiscal_year INTEGER,
                is_total INTEGER, superseded INTEGER
            )"""
        )
        conn.execute(
            "CREATE TABLE documents (doc_id TEXT, title TEXT, publisher TEXT, url TEXT, license TEXT)"
        )
        conn.execute("CREATE TABLE notes (doc_id TEXT, blocks_timeseries INTEGER)")
        if cells:
            placeholders = ", ".join("?" for _ in _CELLS_COLUMNS)
            conn.executemany(f"INSERT INTO cells VALUES ({placeholders})", cells)
        if documents:
            placeholders = ", ".join("?" for _ in _DOCUMENTS_COLUMNS)
            conn.executemany(f"INSERT INTO documents VALUES ({placeholders})", documents)
        if notes:
            placeholders = ", ".join("?" for _ in _NOTES_COLUMNS)
            conn.executemany(f"INSERT INTO notes VALUES ({placeholders})", notes)
        conn.commit()
    finally:
        conn.close()


def make_ryuiki_db(path, quality_transitions=None) -> None:
    """`ryuiki.sqlite` 相当（`quality_transitions` だけ）を作る。"""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE quality_transitions (from_stage TEXT, to_stage TEXT, occurred_at TEXT)"
        )
        if quality_transitions:
            placeholders = ", ".join("?" for _ in _QUALITY_TRANSITIONS_COLUMNS)
            conn.executemany(
                f"INSERT INTO quality_transitions VALUES ({placeholders})", quality_transitions
            )
        conn.commit()
    finally:
        conn.close()
