"""b02 が「候補側」（と、行レベル突合をするときのベースライン側の実データ）を
sqlite / JSON のどちらでも同じインタフェースで読めるようにする薄いラッパ。

ADR-0016 Phase B は「v2 のキューブから v1 の派生テーブル相当を射影したもの」を
候補として想定しているが、このリポジトリにはまだそれが無い。射影が sqlite で
出てくるか JSON で出てくるかも決めていないので、両方受けられるようにする
（拡張子で自動判定: `.json` は JSON、それ以外は sqlite として開く）。

JSON の形（1ファイルに複数テーブル）:

    {
      "<table_name>": {
        "columns": ["col_a", "col_b", ...],
        "rows": [[v_a, v_b, ...], ...]
      },
      ...
    }

sqlite 側は読み取り専用でしか開かない。
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
from typing import Iterator, Sequence


def _sqlite_type_rank(value) -> int:
    """SQLite の既定の型順序（ASC）: NULL(0) < INTEGER/REAL(1) < TEXT(2) < BLOB(3)。"""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return 1
    if isinstance(value, str):
        return 2
    if isinstance(value, (bytes, bytearray)):
        return 3
    return 4  # 未知の型（保険。実データでは起きない想定）


def sqlite_sort_key(row: Sequence) -> tuple:
    """SQLite の `ORDER BY` 既定の型順序で行やキータプルを比較可能にする。

    2つの用途がある:
    - `JsonSource.fetch_rows` の `order_by` を、SQLite 側の物理ソート順
      （`SqliteSource.fetch_rows` が発行する `ORDER BY`）と一致させる。
      素朴に `sorted(rows, key=lambda r: tuple(...))` すると、(a) キー列に
      NULL があると `int`/`str`/`None` の混在比較で `TypeError` になる、
      (b) 型が揃っていても Python の比較順序は SQLite の型順序と一致しない
      場合があり、**同じ論理データでも並び順が変わって `content_hash` が
      ずれる**（レビュー指摘）。
    - `b02_derived_compare.py` がキー集合の差分（ベースライン/候補にしか
      無い行）を安定した順序でレポートに出すときの `sorted()` の `key=`。
      同じ理由（NULL・型混在で `TypeError` になる）で素朴な `sorted()` は使えない。

    ランクが同じ値同士だけを直接比較する（例: 数値どうし）ので、
    `int` と `float` のように相互比較できる型のペアはランク内で正しく順序が付く。
    """
    return tuple((_sqlite_type_rank(v), v) for v in row)


_SYSTEM_TABLE_GLOB = "sqlite_*"


class DataSource:
    def tables(self) -> list[str]:
        raise NotImplementedError

    def has_table(self, table: str) -> bool:
        raise NotImplementedError

    def columns(self, table: str) -> list[str]:
        raise NotImplementedError

    def row_count(self, table: str) -> int:
        raise NotImplementedError

    def fetch_rows(
        self, table: str, columns: Sequence[str], order_by: Sequence[str] | None = None
    ) -> Iterator[tuple]:
        """`columns` の並びで行を返す。`order_by` を渡すとその列順で昇順ソートする
        （突合のキー順ソートに使う。タイは起きない前提 — 呼び出し側がキーの一意性を
        検証済みであること）。
        """
        raise NotImplementedError

    def close(self) -> None:
        pass


class SqliteSource(DataSource):
    """既存の（読み取り専用）sqlite3 接続をラップする。

    b01 はキー導出（`common.derive_key`）に生の `sqlite3.Connection` を使うので、
    同じ接続をここでも使い回す（ファイルを2回開かない）。新規にファイルを開きたい
    だけなら `open_sqlite_source()` を使う。
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._tables = sorted(
            r[0]
            for r in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT GLOB ?",
                (_SYSTEM_TABLE_GLOB,),
            )
        )

    def tables(self) -> list[str]:
        return list(self._tables)

    def has_table(self, table: str) -> bool:
        return table in self._tables

    def columns(self, table: str) -> list[str]:
        return [r[1] for r in self._conn.execute(f'PRAGMA table_info("{table}")')]

    def row_count(self, table: str) -> int:
        return self._conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

    def fetch_rows(self, table, columns, order_by=None):
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

    def close(self) -> None:
        self._conn.close()


class JsonSource(DataSource):
    def __init__(self, path):
        p = pathlib.Path(path)
        with p.open(encoding="utf-8") as f:
            self._data = json.load(f)

    def tables(self) -> list[str]:
        return sorted(self._data.keys())

    def has_table(self, table: str) -> bool:
        return table in self._data

    def columns(self, table: str) -> list[str]:
        return list(self._data[table]["columns"])

    def row_count(self, table: str) -> int:
        return len(self._data[table]["rows"])

    def fetch_rows(self, table, columns, order_by=None):
        spec = self._data[table]
        cols = spec["columns"]
        idx = {c: i for i, c in enumerate(cols)}
        missing = [c for c in columns if c not in idx]
        if missing:
            raise KeyError(f"{table}: JSON ソースに列が無い: {missing}")
        rows = spec["rows"]
        if order_by:
            order_idx = [idx[c] for c in order_by]
            rows = sorted(rows, key=lambda r: sqlite_sort_key([r[i] for i in order_idx]))
        want_idx = [idx[c] for c in columns]
        for r in rows:
            yield tuple(r[i] for i in want_idx)


def open_sqlite_source(path) -> SqliteSource:
    """sqlite ファイルを新規に読み取り専用で開いて `SqliteSource` にする。"""
    p = pathlib.Path(path)
    if not p.exists():
        raise FileNotFoundError(f"sqlite ファイルが無い: {p}")
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    return SqliteSource(conn)


def open_source(path) -> DataSource:
    """拡張子で sqlite / JSON を自動判定して開く（候補側・ベースライン実データ側の
    どちらにも使える汎用オープナ。b02 が使う）。
    """
    path = str(path)
    if path.endswith(".json"):
        return JsonSource(path)
    return open_sqlite_source(path)
