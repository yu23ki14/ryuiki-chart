"""b10（`scripts/b10_project_documents_v1.py`）用の、本物の `data/db/cells.sqlite`/
`ryuiki.sqlite` を要さない小さな sqlite フィクスチャ。

b10 が実際に `SELECT` する列だけを持つ最小限の形にしてある
（`scripts/tests/migrate_fixtures.py` と同じ方針）。
"""
from __future__ import annotations

import sqlite3

# cells: doc_id, table_id, page_no, row_key, col_key, value, value_type, unit,
# fiscal_year, is_total, superseded の11列だけ（b10 の SQL が参照する列）。
# INSERT で列名を明示するために使う（位置だけに頼ると、呼び出し側のタプルの
# 並びとここでの列宣言の並びがずれても検出されない）。
_CELLS_COLUMNS = (
    "doc_id", "table_id", "page_no", "row_key", "col_key",
    "value", "value_type", "unit", "fiscal_year", "is_total", "superseded",
)

_DOCUMENTS_COLUMNS = ("doc_id", "title", "publisher", "url", "license")

_NOTES_COLUMNS = ("doc_id", "blocks_timeseries")

_QUALITY_TRANSITIONS_COLUMNS = ("from_stage", "to_stage", "occurred_at")


def _insert_all(conn: sqlite3.Connection, table: str, columns: tuple[str, ...], rows) -> None:
    collist = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(f"INSERT INTO {table} ({collist}) VALUES ({placeholders})", rows)


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
            _insert_all(conn, "cells", _CELLS_COLUMNS, cells)
        if documents:
            _insert_all(conn, "documents", _DOCUMENTS_COLUMNS, documents)
        if notes:
            _insert_all(conn, "notes", _NOTES_COLUMNS, notes)
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
            _insert_all(conn, "quality_transitions", _QUALITY_TRANSITIONS_COLUMNS, quality_transitions)
        conn.commit()
    finally:
        conn.close()
