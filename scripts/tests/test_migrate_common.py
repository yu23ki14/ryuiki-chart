"""scripts/migrate/common.py の単体テスト（`staged_table`）。

`scripts/tests/test_common.py` は `scripts/reconcile/common.py`（同名だが別モジュール）の
テストなので、`migrate/common.py` 用にこのファイルを分けている。
"""
import sqlite3

import pytest

from migrate import common


class _FailOnSQL:
    """`execute()` に渡す SQL 文字列が `trigger` を含んでいたら `exc` を投げる、
    `sqlite3.Connection` への薄いプロキシ。`execute` 以外は素通しする
    （`__getattr__` で実体の `commit`/`rollback` 等に委譲）——差し替えの
    途中（DROP の後・RENAME の前）で失敗させるテスト用。
    """

    def __init__(self, conn: sqlite3.Connection, trigger: str, exc: BaseException):
        self._conn = conn
        self._trigger = trigger
        self._exc = exc

    def execute(self, sql, *args, **kwargs):
        if self._trigger in sql:
            raise self._exc
        return self._conn.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_staged_table_swaps_to_production_name_on_success(tmp_path):
    db_path = tmp_path / "t.sqlite"
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    conn.execute("PRAGMA journal_mode=DELETE")
    with common.staged_table(conn, "foo", "CREATE TABLE {table} (a INTEGER)") as staging:
        conn.executemany(f'INSERT INTO "{staging}" VALUES (?)', [(1,), (2,), (3,)])
    tables = sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    assert tables == ["foo"]
    assert conn.execute("SELECT * FROM foo ORDER BY a").fetchall() == [(1,), (2,), (3,)]
    conn.close()


def test_staged_table_failure_inside_with_block_preserves_previous_table(tmp_path):
    db_path = tmp_path / "t.sqlite"
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    conn.execute("PRAGMA journal_mode=DELETE")
    with common.staged_table(conn, "foo", "CREATE TABLE {table} (a INTEGER)") as staging:
        conn.executemany(f'INSERT INTO "{staging}" VALUES (?)', [(1,), (2,)])
    before = conn.execute("SELECT * FROM foo ORDER BY a").fetchall()

    with pytest.raises(ValueError, match="boom in with-block"):
        with common.staged_table(conn, "foo", "CREATE TABLE {table} (a INTEGER)") as staging:
            conn.executemany(f'INSERT INTO "{staging}" VALUES (?)', [(9,)])
            raise ValueError("boom in with-block")

    tables = sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    assert tables == ["foo"], "作業用テーブルが残っている"
    assert conn.execute("SELECT * FROM foo ORDER BY a").fetchall() == before
    conn.close()


def test_staged_table_failure_between_drop_and_rename_preserves_previous_table(tmp_path):
    """コードレビュー指摘: 差し替え（DROP + RENAME）の途中で失敗しても、
    前回の本番テーブルがそのまま残る（明示の BEGIN〜COMMIT で1トランザクション
    にしたことの直接確認。実際のプロセスクラッシュの代わりに、DROP の後
    ALTER TABLE の直前で例外を起こす）。
    """
    db_path = tmp_path / "t.sqlite"
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    conn.execute("PRAGMA journal_mode=DELETE")

    # 1回目は正常に成功させ、「前回の本番テーブル」を作る。
    with common.staged_table(conn, "foo", "CREATE TABLE {table} (a INTEGER)") as staging:
        conn.executemany(f'INSERT INTO "{staging}" VALUES (?)', [(1,), (2,)])
    before = conn.execute("SELECT * FROM foo ORDER BY a").fetchall()

    # 2回目: DROP の後・RENAME の前で失敗させる。
    proxy = _FailOnSQL(conn, "ALTER TABLE", RuntimeError("boom mid-swap"))
    with pytest.raises(RuntimeError, match="boom mid-swap"):
        with common.staged_table(proxy, "foo", "CREATE TABLE {table} (a INTEGER)") as staging:
            conn.executemany(f'INSERT INTO "{staging}" VALUES (?)', [(9,), (8,), (7,)])

    tables = sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    after = conn.execute("SELECT * FROM foo ORDER BY a").fetchall()
    assert tables == ["foo"], "本番テーブルが消えたまま、あるいは作業用テーブルが残っている"
    assert after == before, "前回の本番テーブルが変わってしまった"
    conn.close()
