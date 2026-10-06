"""テスト用の小さな sqlite フィクスチャを作る。

`scripts/reconcile/common.py`（指紋計算）のテスト用に、集計テーブルの「形」を縮小再現する:

- `t_pk`      : `PRIMARY KEY` 宣言あり（`redlist_map` / `watershed_meta` 相当）。
- `t_dims`    : `CREATE TABLE ... AS SELECT` 相当。宣言型を持つ次元列
                （`site`, `year`）だけでは一意にならず、宣言型を持たない列
                （`kind`）が無いと一意にならない（`meas_year` の `kind` 相当）。
- `t_dupe`    : 完全に重複する行がある。
                `('g1', NULL)` と `('g1', 'x')` はキーの最初の要素が等しいので、
                これらを含む集合を素朴に `sorted()` すると `None < 'x'` の比較で
                `TypeError` になる（b02 の回帰テスト用）。
"""
import sqlite3

T_PK_ROWS = [
    ("a", "Alpha"),
    ("b", "Beta"),
    ("c", "Gamma"),
]

T_DIMS_ROWS = [
    ("s1", 2020, "daily", 10, 1.5),
    ("s1", 2020, "annual", 1, 1.5),
    ("s1", 2021, "daily", 12, 2.0),
    ("s2", 2020, "daily", 5, 3.0),
]

T_DUPE_ROWS = [
    ("x", 1),
    ("x", 1),  # t_pk と違い、こちらは全列が完全に重複する行
    ("y", 2),
]

def make_fixture_db(path, *, include_dupe: bool = True) -> None:
    """`t_pk` / `t_dims` を作る。`include_dupe=True`（既定）なら、どんな列の
    組み合わせでも一意なキーが作れない `t_dupe` も足す。
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE t_pk (raw TEXT PRIMARY KEY, label TEXT)"
        )
        conn.execute("CREATE TABLE t_dims (site TEXT, year INTEGER, kind, n, avg)")
        conn.executemany("INSERT INTO t_pk VALUES (?,?)", T_PK_ROWS)
        conn.executemany("INSERT INTO t_dims VALUES (?,?,?,?,?)", T_DIMS_ROWS)
        if include_dupe:
            conn.execute("CREATE TABLE t_dupe (a TEXT, b INTEGER)")
            conn.executemany("INSERT INTO t_dupe VALUES (?,?)", T_DUPE_ROWS)
        conn.commit()
    finally:
        conn.close()


