"""`common.compute_fingerprint`（`scripts/migrate/common.py` の段階間の指紋と、
決定論テストの `table_content_hash`）が行を読むための、読み取り専用 sqlite の薄いラッパ。

v1 との突合（b01/b02）は Issue #48 PR-5 で消え、JSON ソース・複数テーブルの列挙・
`ORDER BY` の型順序を再現する比較キーも一緒に消えた。残すのは `compute_fingerprint` が
実際に呼ぶ `columns`・`fetch_rows` だけ。
"""
from __future__ import annotations

import sqlite3
from typing import Sequence


class SqliteSource:
    """既存の（読み取り専用）sqlite3 接続をラップする。書き込みはしない。"""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def columns(self, table: str) -> list[str]:
        return [r[1] for r in self._conn.execute(f'PRAGMA table_info("{table}")')]

    def fetch_rows(self, table: str, columns: Sequence[str], order_by: Sequence[str] | None = None):
        """`columns` の並びで行を返す。`order_by` を渡すとその列順で昇順ソートする
        （キー順の安定化に使う。タイは起きない前提 — 呼び出し側がキーの一意性を保証すること）。
        """
        available = set(self.columns(table))
        missing = [c for c in columns if c not in available]
        if missing:
            raise KeyError(f"{table}: 列が無い: {missing}")
        collist = ", ".join(f'"{c}"' for c in columns)
        sql = f'SELECT {collist} FROM "{table}"'
        if order_by:
            sql += " ORDER BY " + ", ".join(f'"{c}"' for c in order_by)
        for row in self._conn.execute(sql):
            yield tuple(row)
