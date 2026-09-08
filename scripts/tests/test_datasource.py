"""scripts/reconcile/datasource.py の単体テスト。

回帰テスト（レビュー指摘 #3）: `JsonSource.fetch_rows(..., order_by=...)` の
並べ替えが、NULL や型混在があっても `TypeError` を投げず、かつ
`SqliteSource`（＝本物の SQLite の `ORDER BY`）と同じ順序になること。
並び順がずれると、同じ論理データでも `common.compute_fingerprint` が作る
`content_hash` がベースラインと候補で食い違ってしまう（縮退モードは
ハッシュ一致だけが判定材料なので、CI の主経路に偽の不一致を持ち込む）。
"""
import json
import sqlite3

from reconcile import datasource


def _make_sqlite_source(tmp_path, name, columns_sql, rows):
    path = tmp_path / f"{name}.sqlite"
    conn = sqlite3.connect(str(path))
    conn.execute(f"CREATE TABLE t ({columns_sql})")
    placeholders = ",".join("?" for _ in rows[0])
    conn.executemany(f"INSERT INTO t VALUES ({placeholders})", rows)
    conn.commit()
    conn.close()
    ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    return datasource.SqliteSource(ro)


def _make_json_source(tmp_path, name, columns, rows):
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps({"t": {"columns": columns, "rows": [list(r) for r in rows]}}), encoding="utf-8")
    return datasource.JsonSource(path)


# grp, sub: 同じ grp の中で sub が NULL と非NULLに分かれる（キーの一部の
# 比較で None と str の比較が起きる、素朴な sorted() が壊れる形）。
ROWS = [
    ("g1", None, 10.0),
    ("g1", "x", 20.0),
    ("g2", None, 30.0),
    ("g2", "a", 5.0),
]
COLUMNS = ["grp", "sub", "val"]


def test_json_source_order_matches_sqlite_source_with_nulls(tmp_path):
    sqlite_source = _make_sqlite_source(tmp_path, "s", "grp TEXT, sub TEXT, val REAL", ROWS)
    json_source = _make_json_source(tmp_path, "j", COLUMNS, ROWS)

    sqlite_rows = list(sqlite_source.fetch_rows("t", COLUMNS, order_by=["grp", "sub"]))
    json_rows = list(json_source.fetch_rows("t", COLUMNS, order_by=["grp", "sub"]))

    assert sqlite_rows == json_rows


def test_json_source_order_by_does_not_raise_typeerror_on_null_key(tmp_path):
    json_source = _make_json_source(tmp_path, "j2", COLUMNS, ROWS)
    # 例外を投げずに完走することそのものが回帰の確認（以前は None と str の
    # 比較で TypeError になっていた）。
    rows = list(json_source.fetch_rows("t", COLUMNS, order_by=["grp", "sub"]))
    assert len(rows) == 4


def test_sqlite_sort_key_orders_null_before_values():
    keys = [("g1", "x"), ("g1", None), ("g2", None)]
    ordered = sorted(keys, key=datasource.sqlite_sort_key)
    # NULL は SQLite の既定順序で先頭に来る。同じ grp='g1' の中では
    # sub=None が sub='x' より先。
    assert ordered == [("g1", None), ("g1", "x"), ("g2", None)]


def test_sqlite_source_excludes_internal_tables(tmp_path):
    """回帰テスト（レビュー指摘 #7）。ANALYZE を打つと sqlite_stat1 等が
    `sqlite_master` に type='table' として現れるが、これは派生テーブルの
    一部ではないので `tables()` に含めてはいけない。
    """
    path = tmp_path / "analyzed.sqlite"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t_real (a TEXT PRIMARY KEY, b INTEGER)")
    conn.execute("INSERT INTO t_real VALUES ('x', 1)")
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()

    ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    source = datasource.SqliteSource(ro)
    assert source.tables() == ["t_real"]
